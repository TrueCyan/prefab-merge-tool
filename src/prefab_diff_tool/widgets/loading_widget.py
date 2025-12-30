"""
Loading progress widget for async operations.

Uses unityflow for GUID indexing with cached results.
Progress updates are decoupled from loading logic for zero overhead.
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from prefab_diff_tool.core.loader import load_unity_file
from prefab_diff_tool.core.unity_model import UnityDocument
from prefab_diff_tool.utils.guid_resolver import GuidResolver


@dataclass
class ProgressState:
    """Thread-safe progress state shared between worker and UI."""
    phase: str = "idle"
    current: int = 0
    total: int = 0
    message: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def update(self, phase: str, current: int, total: int, message: str) -> None:
        """Update progress state (called from worker thread)."""
        with self._lock:
            self.phase = phase
            self.current = current
            self.total = total
            self.message = message

    def get(self) -> tuple[str, int, int, str]:
        """Get current state (called from UI thread)."""
        with self._lock:
            return self.phase, self.current, self.total, self.message


class WeightedProgress:
    """
    Tracks progress across multiple weighted phases.

    Each phase has a weight representing its expected duration relative to others.
    Progress within each phase is mapped to the overall progress bar smoothly.
    """

    def __init__(self, phases: list[tuple[str, float]]):
        """
        Initialize with phase definitions.

        Args:
            phases: List of (phase_name, weight) tuples.
                   Weights are relative (e.g., [("A", 1), ("B", 3)] means B takes 3x longer)
        """
        self._phases = phases
        self._phase_names = [p[0] for p in phases]
        self._weights = [p[1] for p in phases]
        self._total_weight = sum(self._weights)

        # Calculate phase boundaries (0.0 to 1.0)
        self._phase_starts: list[float] = []
        self._phase_ends: list[float] = []
        cumulative = 0.0
        for weight in self._weights:
            self._phase_starts.append(cumulative / self._total_weight)
            cumulative += weight
            self._phase_ends.append(cumulative / self._total_weight)

        self._current_phase = 0
        self._phase_progress = 0.0  # 0.0 to 1.0 within current phase

    def set_phase(self, phase_index: int) -> None:
        """Move to a specific phase."""
        if 0 <= phase_index < len(self._phases):
            self._current_phase = phase_index
            self._phase_progress = 0.0

    def set_phase_by_name(self, name: str) -> None:
        """Move to a phase by name."""
        if name in self._phase_names:
            self.set_phase(self._phase_names.index(name))

    def update_phase_progress(self, current: int, total: int) -> None:
        """Update progress within the current phase."""
        if total > 0:
            self._phase_progress = min(1.0, current / total)
        else:
            self._phase_progress = 0.0

    def complete_phase(self) -> None:
        """Mark current phase as complete and move to next."""
        self._phase_progress = 1.0
        if self._current_phase < len(self._phases) - 1:
            self._current_phase += 1
            self._phase_progress = 0.0

    def get_overall_progress(self) -> float:
        """Get overall progress as 0.0 to 1.0."""
        if self._current_phase >= len(self._phases):
            return 1.0

        phase_start = self._phase_starts[self._current_phase]
        phase_end = self._phase_ends[self._current_phase]
        phase_range = phase_end - phase_start

        return phase_start + (phase_range * self._phase_progress)

    def get_percent(self) -> int:
        """Get overall progress as 0-100 percentage."""
        return int(self.get_overall_progress() * 100)

    def get_current_phase_name(self) -> str:
        """Get name of current phase."""
        if self._current_phase < len(self._phase_names):
            return self._phase_names[self._current_phase]
        return "Complete"


class IndexingWorker(QThread):
    """Worker thread for GUID indexing."""

    progress = Signal(int, int, str)  # current, total, message
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        guid_resolver: GuidResolver,
        parent: Optional[QThread] = None,
    ):
        super().__init__(parent)
        self._resolver = guid_resolver
        self._cancelled = False

    def run(self) -> None:
        """Run indexing in background thread."""
        try:
            self._resolver.index_project(
                progress_callback=self._on_progress,
            )
            if not self._cancelled:
                self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current: int, total: int, message: str) -> None:
        """Handle progress updates from resolver."""
        if not self._cancelled:
            self.progress.emit(current, total, message)

    def cancel(self) -> None:
        """Request cancellation."""
        self._cancelled = True


class FileLoadingWorker(QThread):
    """
    Worker thread for loading Unity files with progress tracking.

    Progress updates are decoupled from loading logic:
    - Worker updates ProgressState (zero overhead, just memory write)
    - UI polls ProgressState on a timer (independent of loading speed)

    Uses unityflow's CachedGUIDIndex for fast indexed lookups.
    """

    # Signals only for state changes, not progress updates
    file_loaded = Signal(object, int)  # document, file_index
    indexing_started = Signal()
    finished = Signal()
    error = Signal(str)

    # Legacy signals kept for compatibility but not used for frequent updates
    progress_detailed = Signal(int, str, str)
    progress = Signal(int, int, str)

    # Simplified phases - unityflow handles caching internally
    PHASE_WEIGHTS = [
        ("file_loading", 20),   # 파일 파싱
        ("guid_indexing", 80),  # unityflow 인덱싱 (캐시 포함)
    ]

    def __init__(
        self,
        file_paths: list[Path],
        unity_root: Optional[Path] = None,
        parent: Optional[QThread] = None,
    ):
        super().__init__(parent)
        self._file_paths = file_paths
        self._unity_root = unity_root
        self._documents: list[Optional[UnityDocument]] = []
        self._cancelled = False
        self._guid_resolver: Optional[GuidResolver] = None
        self._weighted_progress = WeightedProgress(self.PHASE_WEIGHTS)

        # Shared progress state - UI polls this instead of receiving signals
        self.progress_state = ProgressState()

    def _update_progress(self, phase_progress: tuple[int, int], message: str) -> None:
        """Update progress state (no signal emission, zero overhead)."""
        current, total = phase_progress
        self._weighted_progress.update_phase_progress(current, total)
        percent = self._weighted_progress.get_percent()
        phase_name = self._weighted_progress.get_current_phase_name()

        # Just update shared state - no signal emission
        self.progress_state.update(phase_name, percent, 100, message)

    def run(self) -> None:
        """Load files and index project in background."""
        try:
            # Phase 1: File loading
            self._weighted_progress.set_phase_by_name("file_loading")
            num_files = len(self._file_paths)

            for i, path in enumerate(self._file_paths):
                if self._cancelled:
                    return

                self._update_progress((i, num_files), f"파일 로딩 중: {path.name}")
                doc = load_unity_file(path, unity_root=self._unity_root)
                self._documents.append(doc)
                self.file_loaded.emit(doc, i)

                # Use first document's project root for indexing
                if i == 0 and doc.project_root:
                    self._guid_resolver = GuidResolver()
                    self._guid_resolver.set_project_root(
                        Path(doc.project_root), auto_index=False
                    )

            self._weighted_progress.complete_phase()

            # Phase 2: GUID indexing using unityflow
            if self._guid_resolver and not self._cancelled:
                self.indexing_started.emit()
                self._run_indexing()

            if not self._cancelled:
                self.finished.emit()

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))

    def _run_indexing(self) -> None:
        """Run GUID indexing using unityflow's CachedGUIDIndex."""
        if not self._guid_resolver:
            return

        self._weighted_progress.set_phase_by_name("guid_indexing")
        self._update_progress((0, 1), "에셋 인덱싱 중... (캐시 확인)")

        # unityflow handles caching, scanning, and indexing internally
        # This will be fast if cache is valid, slower on first run
        self._guid_resolver.index_project(
            progress_callback=self._on_indexing_progress,
            include_package_cache=True,
        )

        self._weighted_progress.complete_phase()

    def _on_indexing_progress(self, current: int, total: int, message: str) -> None:
        """Handle progress updates from guid_resolver."""
        if not self._cancelled:
            self._update_progress((current, total), message)

    def cancel(self) -> None:
        """Request cancellation."""
        self._cancelled = True

    def get_documents(self) -> list[Optional[UnityDocument]]:
        """Get loaded documents."""
        return self._documents

    def get_guid_resolver(self) -> Optional[GuidResolver]:
        """Get the GUID resolver with indexed cache."""
        return self._guid_resolver


class LoadingProgressWidget(QWidget):
    """Widget showing loading progress with phase information.

    Can poll a ProgressState for updates (decoupled from worker thread).
    """

    cancelled = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._progress_state: Optional[ProgressState] = None
        self._poll_timer: Optional[QTimer] = None
        self._setup_ui()

    def start_polling(self, progress_state: ProgressState, interval_ms: int = 50) -> None:
        """Start polling progress state for updates.

        Args:
            progress_state: Shared state to poll
            interval_ms: Poll interval in milliseconds (default 50ms = 20fps)
        """
        self._progress_state = progress_state

        # Ensure progress bar is in determinate mode
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p%")  # Qt native format - always synced with value
        self._phase_label.setText("[시작]")
        self._status.setText("로딩 준비 중...")

        # Stop any existing timer
        if self._poll_timer:
            self._poll_timer.stop()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_progress)
        self._poll_timer.start(interval_ms)

    def stop_polling(self, error: bool = False) -> None:
        """Stop polling for updates.

        Args:
            error: If True, don't update to 100% (loading failed)
        """
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None

        # Set final state - show 100% if completed successfully
        if not error:
            self.update_progress_detailed(100, "Complete", "완료")
        elif self._progress_state:
            # On error, just show current state
            phase, percent, total, message = self._progress_state.get()
            self.update_progress_detailed(percent, phase, message)

    def _poll_progress(self) -> None:
        """Poll progress state and update UI."""
        if self._progress_state:
            phase, percent, total, message = self._progress_state.get()
            self.update_progress_detailed(percent, phase, message)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        # Title
        self._title = QLabel("Loading...")
        self._title.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

        # Phase indicator
        self._phase_label = QLabel("")
        self._phase_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._phase_label)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 4px;
                background: #2d2d2d;
                height: 24px;
                text-align: center;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2a82da, stop:1 #4aa3f0
                );
                border-radius: 3px;
            }
        """)
        layout.addWidget(self._progress_bar)

        # Status message (detailed)
        self._status = QLabel("")
        self._status.setStyleSheet("color: #888; font-size: 11px;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

    def set_title(self, title: str) -> None:
        """Set the title text."""
        self._title.setText(title)

    def update_progress(self, current: int, total: int, message: str) -> None:
        """Update progress display (legacy interface)."""
        if total > 0:
            percent = min(100, int((current / total) * 100))
            self._progress_bar.setValue(percent)
            # Use Qt native format - text always matches bar value
            self._progress_bar.setFormat("%p%")
        else:
            self._progress_bar.setMaximum(0)  # Indeterminate mode

        self._status.setText(message)

    def update_progress_detailed(
        self, percent: int, phase_name: str, message: str
    ) -> None:
        """Update progress with phase information."""
        # Ensure bar is in determinate mode (max=100)
        if self._progress_bar.maximum() != 100:
            self._progress_bar.setMaximum(100)

        # setValue and format use Qt native %p% - guarantees sync
        self._progress_bar.setValue(min(100, percent))
        self._progress_bar.setFormat("%p%")

        # Translate phase names to Korean
        phase_display = {
            "idle": "대기",
            "file_loading": "파일 로딩",
            "guid_indexing": "인덱싱",
            "Complete": "완료",
        }.get(phase_name, phase_name)

        self._phase_label.setText(f"[{phase_display}]")
        if message:
            self._status.setText(message)

    def set_indeterminate(self, indeterminate: bool = True) -> None:
        """Set indeterminate (pulsing) mode."""
        if indeterminate:
            self._progress_bar.setMaximum(0)
        else:
            self._progress_bar.setMaximum(100)


class LoadingDialog(QDialog):
    """Modal dialog showing loading progress.

    Supports polling a worker's ProgressState for decoupled progress updates.
    """

    def __init__(
        self,
        title: str = "Loading",
        parent: Optional[QWidget] = None,
        cancellable: bool = False,
    ):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._cancellable = cancellable
        self._cancelled = False
        self._setup_ui()

    def connect_worker(self, worker: FileLoadingWorker) -> None:
        """Connect to a worker's progress state for polling updates.

        Args:
            worker: The FileLoadingWorker to monitor
        """
        self._progress_widget.start_polling(worker.progress_state)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)

    def _on_worker_finished(self) -> None:
        """Handle worker completion."""
        self._progress_widget.stop_polling()
        self.accept()

    def _on_worker_error(self, error_msg: str) -> None:
        """Handle worker error."""
        self._progress_widget.stop_polling(error=True)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Progress widget
        self._progress_widget = LoadingProgressWidget()
        layout.addWidget(self._progress_widget)

        # Cancel button (optional)
        if self._cancellable:
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            self._cancel_btn = QPushButton("Cancel")
            self._cancel_btn.clicked.connect(self._on_cancel)
            button_layout.addWidget(self._cancel_btn)
            button_layout.addStretch()
            layout.addLayout(button_layout)

    def set_title(self, title: str) -> None:
        """Set progress title."""
        self._progress_widget.set_title(title)

    def update_progress(self, current: int, total: int, message: str) -> None:
        """Update progress display."""
        self._progress_widget.update_progress(current, total, message)

    def update_progress_detailed(
        self, percent: int, phase_name: str, message: str
    ) -> None:
        """Update progress with phase information."""
        self._progress_widget.update_progress_detailed(percent, phase_name, message)

    def set_indeterminate(self, indeterminate: bool = True) -> None:
        """Set indeterminate mode."""
        self._progress_widget.set_indeterminate(indeterminate)

    def _on_cancel(self) -> None:
        """Handle cancel button click."""
        self._cancelled = True
        self.reject()

    def was_cancelled(self) -> bool:
        """Check if dialog was cancelled."""
        return self._cancelled

    def closeEvent(self, event) -> None:
        """Prevent closing during non-cancellable operations."""
        if self._cancellable:
            self._cancelled = True
            event.accept()
        else:
            event.ignore()
