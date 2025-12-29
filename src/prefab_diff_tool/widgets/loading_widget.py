"""
Loading progress widget for async operations.
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
    """Worker thread for loading Unity files."""

    progress = Signal(int, int, str)  # current, total, message
    file_loaded = Signal(object, int)  # document, file_index
    indexing_started = Signal()
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        file_paths: list[Path],
        parent: Optional[QThread] = None,
    ):
        super().__init__(parent)
        self._file_paths = file_paths
        self._documents: list[Optional[UnityDocument]] = []
        self._cancelled = False
        self._guid_resolver: Optional[GuidResolver] = None

    def run(self) -> None:
        """Load files and index project in background."""
        try:
            total_steps = len(self._file_paths) + 1  # files + indexing

            # Load each file
            for i, path in enumerate(self._file_paths):
                if self._cancelled:
                    return

                self.progress.emit(i, total_steps, f"Loading {path.name}...")
                doc = load_unity_file(path)
                self._documents.append(doc)
                self.file_loaded.emit(doc, i)

                # Use first document's project root for indexing
                if i == 0 and doc.project_root:
                    self._guid_resolver = GuidResolver()
                    self._guid_resolver.set_project_root(
                        Path(doc.project_root), auto_index=False
                    )

            # Index GUID mappings
            if self._guid_resolver and not self._cancelled:
                self.indexing_started.emit()
                self.progress.emit(
                    len(self._file_paths), total_steps, "Indexing assets..."
                )
                self._guid_resolver.index_project(
                    progress_callback=self._on_indexing_progress
                )

            if not self._cancelled:
                self.finished.emit()

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))

    def _on_indexing_progress(self, current: int, total: int, message: str) -> None:
        """Handle indexing progress."""
        if not self._cancelled:
            # Map indexing progress to overall progress
            base = len(self._file_paths)
            total_steps = base + 1
            if total > 0:
                fraction = current / total
                self.progress.emit(
                    int(base + fraction), total_steps, message
                )
            else:
                self.progress.emit(base, total_steps, message)

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
    """Widget showing loading progress."""

    cancelled = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Title
        self._title = QLabel("Loading...")
        self._title.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

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
                height: 20px;
                text-align: center;
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

        # Status message
        self._status = QLabel("")
        self._status.setStyleSheet("color: #888; font-size: 11px;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

    def set_title(self, title: str) -> None:
        """Set the title text."""
        self._title.setText(title)

    def update_progress(self, current: int, total: int, message: str) -> None:
        """Update progress display."""
        if total > 0:
            percent = int((current / total) * 100)
            self._progress_bar.setValue(percent)
            self._progress_bar.setFormat(f"{percent}%")
        else:
            self._progress_bar.setMaximum(0)  # Indeterminate mode

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
        self.setMinimumWidth(400)
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
