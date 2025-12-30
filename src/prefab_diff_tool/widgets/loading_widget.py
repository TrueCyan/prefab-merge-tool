"""
Loading progress widget for async operations.

Uses weighted phases for accurate progress display based on expected duration.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
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
    Worker thread for loading Unity files with accurate progress tracking.

    Uses weighted phases based on expected duration:
    - File loading: 5% (fast, just parsing)
    - Cache loading: 5% (loading from SQLite)
    - Meta scanning: 10% (finding .meta files)
    - Change detection: 10% (checking mtimes)
    - GUID indexing: 60% (processing .meta files)
    - Cache saving: 10% (writing to SQLite)
    """

    # Detailed progress signal: (percent, phase_name, detail_message)
    progress_detailed = Signal(int, str, str)

    # Legacy progress signal for compatibility
    progress = Signal(int, int, str)

    file_loaded = Signal(object, int)  # document, file_index
    indexing_started = Signal()
    finished = Signal()
    error = Signal(str)

    # Phase weights based on expected duration (17만 assets 기준)
    # Total time ~15초 기준으로 비율 산정
    PHASE_WEIGHTS = [
        ("file_loading", 5),      # ~0.5초: 프리팹 파일 파싱
        ("cache_loading", 10),    # ~1.5초: SQLite에서 캐시 로드
        ("meta_scanning", 10),    # ~1.5초: .meta 파일 탐색
        ("change_detection", 10), # ~1.5초: mtime 비교
        ("guid_indexing", 55),    # ~8초: 변경된 파일 처리
        ("cache_saving", 10),     # ~1.5초: SQLite 저장
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
        self._progress = WeightedProgress(self.PHASE_WEIGHTS)

    def _emit_progress(self, phase_progress: tuple[int, int], message: str) -> None:
        """Emit progress signals."""
        current, total = phase_progress
        self._progress.update_phase_progress(current, total)
        percent = self._progress.get_percent()
        phase_name = self._progress.get_current_phase_name()

        self.progress_detailed.emit(percent, phase_name, message)
        # Legacy signal - emit as percentage out of 100
        self.progress.emit(percent, 100, message)

    def run(self) -> None:
        """Load files and index project in background."""
        try:
            # Phase 1: File loading
            self._progress.set_phase_by_name("file_loading")
            num_files = len(self._file_paths)

            for i, path in enumerate(self._file_paths):
                if self._cancelled:
                    return

                self._emit_progress((i, num_files), f"파일 로딩 중: {path.name}")
                doc = load_unity_file(path, unity_root=self._unity_root)
                self._documents.append(doc)
                self.file_loaded.emit(doc, i)

                # Use first document's project root for indexing
                if i == 0 and doc.project_root:
                    self._guid_resolver = GuidResolver()
                    # Don't auto-index yet, we'll do it manually with progress
                    self._guid_resolver.set_project_root(
                        Path(doc.project_root), auto_index=False
                    )

            self._progress.complete_phase()

            # Phase 2-6: GUID indexing with detailed progress
            if self._guid_resolver and not self._cancelled:
                self.indexing_started.emit()
                self._run_indexing_with_progress()

            if not self._cancelled:
                self.finished.emit()

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))

    def _run_indexing_with_progress(self) -> None:
        """Run GUID indexing with detailed phase progress."""
        resolver = self._guid_resolver
        if not resolver or not resolver._project_root:
            return

        # Phase 2: Cache loading (already done in set_project_root, but report it)
        self._progress.set_phase_by_name("cache_loading")
        cache_count = len(resolver._cache)
        if cache_count > 0:
            self._emit_progress((1, 1), f"캐시 로드 완료: {cache_count:,}개 에셋")
        else:
            self._emit_progress((1, 1), "캐시 초기화 중...")
        self._progress.complete_phase()

        if self._cancelled:
            return

        # Phase 3: Meta file scanning
        self._progress.set_phase_by_name("meta_scanning")
        self._emit_progress((0, 1), ".meta 파일 검색 중...")

        import os
        meta_files: list[Path] = []
        assets_path = resolver._project_root / "Assets"
        packages_path = resolver._project_root / "Packages"

        search_paths = []
        if assets_path.exists():
            search_paths.append(assets_path)
        if packages_path.exists():
            search_paths.append(packages_path)

        # Progress updates every N directories (avoid time.time() overhead)
        scanned_dirs = 0
        update_interval = 50  # Update every 50 directories

        for search_path in search_paths:
            for root, dirs, files in os.walk(search_path):
                if self._cancelled:
                    return
                for filename in files:
                    if filename.endswith(".meta"):
                        meta_files.append(Path(root) / filename)
                scanned_dirs += 1

                # Simple counter-based updates (no time.time() overhead)
                if scanned_dirs % update_interval == 0:
                    found = len(meta_files)
                    self._emit_progress(
                        (found, max(found * 2, 1000)),
                        f".meta 파일 검색 중... {found:,}개 발견"
                    )

        total_meta = len(meta_files)
        self._emit_progress((1, 1), f".meta 파일 {total_meta:,}개 발견")
        self._progress.complete_phase()

        if self._cancelled or total_meta == 0:
            resolver._indexed = True
            return

        # Phase 4: Change detection
        self._progress.set_phase_by_name("change_detection")
        files_to_process = meta_files
        guids_to_delete: list[str] = []

        if resolver._db_cache:
            self._emit_progress((0, 1), "변경 사항 확인 중...")

            # Progress callback for change detection
            def on_change_progress(current: int, total: int, message: str) -> None:
                self._emit_progress((current, total), message)

            # Get stale entries with progress
            files_to_process, guids_to_delete = resolver._db_cache.get_stale_entries(
                meta_files, progress_callback=on_change_progress
            )

            # Delete stale entries
            if guids_to_delete:
                self._emit_progress(
                    (1, 2), f"삭제된 파일 정리 중... {len(guids_to_delete):,}개"
                )
                resolver._db_cache.delete_guids(guids_to_delete)
                for guid in guids_to_delete:
                    resolver._cache.pop(guid, None)
                    resolver._path_cache.pop(guid, None)

        num_to_process = len(files_to_process)
        if num_to_process == 0:
            self._emit_progress((1, 1), f"캐시 최신 상태: {len(resolver._cache):,}개 에셋")
        elif num_to_process < total_meta:
            self._emit_progress(
                (1, 1), f"변경된 파일 {num_to_process:,}개 발견 (전체 {total_meta:,}개 중)"
            )
        else:
            self._emit_progress((1, 1), f"전체 인덱싱 필요: {total_meta:,}개 파일")

        self._progress.complete_phase()

        if self._cancelled:
            return

        # Phase 5: GUID indexing
        self._progress.set_phase_by_name("guid_indexing")

        if num_to_process == 0:
            self._emit_progress((1, 1), "인덱싱 불필요 (캐시 사용)")
            self._progress.complete_phase()
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            max_workers = min(32, (os.cpu_count() or 1) + 4)
            processed = 0
            new_entries: list[tuple[str, str, Path, Path, float]] = []

            # More frequent updates for smooth progress
            update_interval = max(1, num_to_process // 200)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_path = {
                    executor.submit(
                        resolver._process_meta_file_with_mtime, meta_file
                    ): meta_file
                    for meta_file in files_to_process
                }

                for future in as_completed(future_to_path):
                    if self._cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        return

                    result = future.result()
                    if result:
                        guid, asset_name, asset_path, meta_path, mtime = result
                        resolver._cache[guid] = asset_name
                        resolver._path_cache[guid] = asset_path
                        new_entries.append(
                            (guid, asset_name, asset_path, meta_path, mtime)
                        )

                    processed += 1

                    if processed % update_interval == 0 or processed == num_to_process:
                        self._emit_progress(
                            (processed, num_to_process),
                            f"인덱싱 중... {processed:,}/{num_to_process:,}"
                        )

            self._progress.complete_phase()

            if self._cancelled:
                return

            # Phase 6: Cache saving
            self._progress.set_phase_by_name("cache_saving")

            if resolver._db_cache and new_entries:
                self._emit_progress((0, 1), f"캐시 저장 중... {len(new_entries):,}개 항목")

                # Batch save with progress for large datasets
                batch_size = 10000
                total_entries = len(new_entries)

                if total_entries <= batch_size:
                    resolver._db_cache.set_many(new_entries)
                    self._emit_progress((1, 1), "캐시 저장 완료")
                else:
                    saved = 0
                    for i in range(0, total_entries, batch_size):
                        if self._cancelled:
                            return
                        batch = new_entries[i:i + batch_size]
                        resolver._db_cache.set_many(batch)
                        saved += len(batch)
                        self._emit_progress(
                            (saved, total_entries),
                            f"캐시 저장 중... {saved:,}/{total_entries:,}"
                        )

                resolver._db_cache.set_last_index_time()
            else:
                self._emit_progress((1, 1), "저장할 변경 사항 없음")

            self._progress.complete_phase()

        resolver._indexed = True
        self._emit_progress((1, 1), f"완료: {len(resolver._cache):,}개 에셋 인덱싱됨")

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
    """Widget showing loading progress with phase information."""

    cancelled = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._setup_ui()

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
            self._progress_bar.setFormat(f"{percent}%")
        else:
            self._progress_bar.setMaximum(0)  # Indeterminate mode

        self._status.setText(message)

    def update_progress_detailed(
        self, percent: int, phase_name: str, message: str
    ) -> None:
        """Update progress with phase information."""
        self._progress_bar.setValue(min(100, percent))
        self._progress_bar.setFormat(f"{percent}%")

        # Translate phase names to Korean
        phase_display = {
            "file_loading": "파일 로딩",
            "cache_loading": "캐시 로드",
            "meta_scanning": "파일 탐색",
            "change_detection": "변경 감지",
            "guid_indexing": "인덱싱",
            "cache_saving": "캐시 저장",
        }.get(phase_name, phase_name)

        self._phase_label.setText(f"[{phase_display}]")
        self._status.setText(message)

    def set_indeterminate(self, indeterminate: bool = True) -> None:
        """Set indeterminate (pulsing) mode."""
        if indeterminate:
            self._progress_bar.setMaximum(0)
        else:
            self._progress_bar.setMaximum(100)


class LoadingDialog(QDialog):
    """Modal dialog showing loading progress."""

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
