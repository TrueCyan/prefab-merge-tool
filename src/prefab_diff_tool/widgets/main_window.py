"""
Main application window.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QFileDialog,
    QMessageBox,
    QStatusBar,
    QLabel,
    QStackedWidget,
    QWidget,
    QVBoxLayout,
)

from prefab_diff_tool.widgets.diff_view import DiffView
from prefab_diff_tool.widgets.merge_view import MergeView


# Supported Unity file extensions
UNITY_FILE_FILTER = (
    "Unity Files (*.prefab *.unity *.asset *.anim *.controller *.mat);;"
    "Prefabs (*.prefab);;"
    "Scenes (*.unity);;"
    "All Files (*)"
)


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self.setWindowTitle("prefab-diff-tool")
        self.setMinimumSize(1200, 800)
        
        # Restore window geometry
        self._load_settings()
        
        # Central widget with stacked views
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)
        
        # Welcome page
        self._welcome = self._create_welcome_page()
        self._stack.addWidget(self._welcome)
        
        # Diff view (created on demand)
        self._diff_view: Optional[DiffView] = None
        
        # Merge view (created on demand)
        self._merge_view: Optional[MergeView] = None
        
        # Current file paths
        self._current_files: list[Path] = []
        self._output_file: Optional[Path] = None
        
        # Setup UI
        self._setup_menu_bar()
        self._setup_status_bar()
    
    def _create_welcome_page(self) -> QWidget:
        """Create the welcome/empty state page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        label = QLabel(
            "<h2>prefab-diff-tool</h2>"
            "<p>Unity 프리팹 파일을 위한 시각적 Diff/Merge 도구</p>"
            "<br>"
            "<p>파일 → Diff 열기 또는 Merge 열기를 선택하세요</p>"
            "<p>또는 파일을 드래그 앤 드롭하세요</p>"
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888;")
        layout.addWidget(label)
        
        return page
    
    def _setup_menu_bar(self) -> None:
        """Setup the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("파일(&F)")
        
        # Open file
        open_action = QAction("파일 열기(&O)...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._on_open_file)
        file_menu.addAction(open_action)
        
        # Open diff
        diff_action = QAction("Diff 열기(&D)...", self)
        diff_action.setShortcut(QKeySequence("Ctrl+D"))
        diff_action.triggered.connect(self._on_open_diff)
        file_menu.addAction(diff_action)
        
        # Open merge
        merge_action = QAction("Merge 열기(&M)...", self)
        merge_action.setShortcut(QKeySequence("Ctrl+M"))
        merge_action.triggered.connect(self._on_open_merge)
        file_menu.addAction(merge_action)
        
        file_menu.addSeparator()
        
        # Save (for merge)
        self._save_action = QAction("저장(&S)", self)
        self._save_action.setShortcut(QKeySequence.StandardKey.Save)
        self._save_action.setEnabled(False)
        self._save_action.triggered.connect(self._on_save)
        file_menu.addAction(self._save_action)
        
        file_menu.addSeparator()
        
        # Exit
        exit_action = QAction("종료(&X)", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = menubar.addMenu("보기(&V)")
        
        # Navigate to next change
        next_action = QAction("다음 변경(&N)", self)
        next_action.setShortcut(QKeySequence("N"))
        next_action.triggered.connect(self._on_next_change)
        view_menu.addAction(next_action)
        
        # Navigate to previous change
        prev_action = QAction("이전 변경(&P)", self)
        prev_action.setShortcut(QKeySequence("P"))
        prev_action.triggered.connect(self._on_prev_change)
        view_menu.addAction(prev_action)
        
        view_menu.addSeparator()
        
        # Expand all
        expand_action = QAction("모두 펼치기", self)
        expand_action.setShortcut(QKeySequence("Ctrl+E"))
        expand_action.triggered.connect(self._on_expand_all)
        view_menu.addAction(expand_action)
        
        # Collapse all
        collapse_action = QAction("모두 접기", self)
        collapse_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        collapse_action.triggered.connect(self._on_collapse_all)
        view_menu.addAction(collapse_action)
        
        # Help menu
        help_menu = menubar.addMenu("도움말(&H)")
        
        about_action = QAction("정보(&A)...", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
    
    def _setup_status_bar(self) -> None:
        """Setup the status bar."""
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        
        # Status label
        self._status_label = QLabel("준비")
        self._status_bar.addWidget(self._status_label)
        
        # Change summary label (right side)
        self._summary_label = QLabel("")
        self._status_bar.addPermanentWidget(self._summary_label)
    
    def _load_settings(self) -> None:
        """Load saved settings."""
        settings = QSettings()
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = settings.value("windowState")
        if state:
            self.restoreState(state)
    
    def _save_settings(self) -> None:
        """Save settings."""
        settings = QSettings()
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
    
    def closeEvent(self, event) -> None:
        """Handle window close."""
        # Check for unsaved changes in merge mode
        if self._merge_view and self._merge_view.has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "저장되지 않은 변경",
                "저장되지 않은 변경사항이 있습니다. 종료하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        
        self._save_settings()
        event.accept()
    
    # === Public methods ===
    
    def open_file(self, path: Path) -> None:
        """Open a single file for viewing."""
        self._current_files = [path]
        self._status_label.setText(f"파일: {path.name}")
        # TODO: Implement single file view
        QMessageBox.information(self, "TODO", f"파일 보기 모드: {path}")
    
    def open_diff(self, left: Path, right: Path) -> None:
        """Open two files for diff comparison."""
        self._current_files = [left, right]
        
        # Create diff view if needed
        if not self._diff_view:
            self._diff_view = DiffView()
            self._diff_view.change_selected.connect(self._on_change_selected)
            self._stack.addWidget(self._diff_view)
        
        # Load files
        self._diff_view.load_diff(left, right)
        self._stack.setCurrentWidget(self._diff_view)
        
        self.setWindowTitle(f"Diff: {left.name} ↔ {right.name}")
        self._status_label.setText(f"{left.name} ↔ {right.name}")
        self._update_summary()
    
    def open_merge(self, base: Path, ours: Path, theirs: Path, output: Path) -> None:
        """Open files for 3-way merge."""
        self._current_files = [base, ours, theirs]
        self._output_file = output
        
        # Create merge view if needed
        if not self._merge_view:
            self._merge_view = MergeView()
            self._merge_view.conflict_resolved.connect(self._on_conflict_resolved)
            self._stack.addWidget(self._merge_view)
        
        # Load files
        self._merge_view.load_merge(base, ours, theirs)
        self._stack.setCurrentWidget(self._merge_view)
        
        self._save_action.setEnabled(True)
        self.setWindowTitle(f"Merge: {ours.name}")
        self._status_label.setText(f"Merge: {base.name} | {ours.name} | {theirs.name}")
        self._update_summary()
    
    # === Menu handlers ===
    
    def _on_open_file(self) -> None:
        """Handle File > Open."""
        path, _ = QFileDialog.getOpenFileName(
            self, "파일 열기", "", UNITY_FILE_FILTER
        )
        if path:
            self.open_file(Path(path))
    
    def _on_open_diff(self) -> None:
        """Handle File > Open Diff."""
        # First file
        left, _ = QFileDialog.getOpenFileName(
            self, "왼쪽 파일 선택 (이전 버전)", "", UNITY_FILE_FILTER
        )
        if not left:
            return
        
        # Second file
        right, _ = QFileDialog.getOpenFileName(
            self, "오른쪽 파일 선택 (새 버전)", "", UNITY_FILE_FILTER
        )
        if not right:
            return
        
        self.open_diff(Path(left), Path(right))
    
    def _on_open_merge(self) -> None:
        """Handle File > Open Merge."""
        # Base file
        base, _ = QFileDialog.getOpenFileName(
            self, "BASE 파일 선택 (공통 조상)", "", UNITY_FILE_FILTER
        )
        if not base:
            return
        
        # Ours file
        ours, _ = QFileDialog.getOpenFileName(
            self, "OURS 파일 선택 (내 변경)", "", UNITY_FILE_FILTER
        )
        if not ours:
            return
        
        # Theirs file
        theirs, _ = QFileDialog.getOpenFileName(
            self, "THEIRS 파일 선택 (상대 변경)", "", UNITY_FILE_FILTER
        )
        if not theirs:
            return
        
        # Output file
        output, _ = QFileDialog.getSaveFileName(
            self, "출력 파일 선택", ours, UNITY_FILE_FILTER
        )
        if not output:
            return
        
        self.open_merge(Path(base), Path(ours), Path(theirs), Path(output))
    
    def _on_save(self) -> None:
        """Handle File > Save (merge result)."""
        if self._merge_view and self._output_file:
            if self._merge_view.has_unresolved_conflicts():
                reply = QMessageBox.warning(
                    self,
                    "미해결 충돌",
                    "아직 해결되지 않은 충돌이 있습니다. 그래도 저장하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.No:
                    return

            success = self._merge_view.save_result(self._output_file)
            if success:
                self._status_label.setText(f"저장됨: {self._output_file.name}")
                QMessageBox.information(
                    self,
                    "저장 완료",
                    f"병합 결과가 저장되었습니다:\n{self._output_file}",
                )
            else:
                QMessageBox.critical(
                    self,
                    "저장 실패",
                    "병합 결과를 저장하는 중 오류가 발생했습니다.",
                )
    
    def _on_next_change(self) -> None:
        """Navigate to next change."""
        current = self._stack.currentWidget()
        if hasattr(current, "goto_next_change"):
            current.goto_next_change()
    
    def _on_prev_change(self) -> None:
        """Navigate to previous change."""
        current = self._stack.currentWidget()
        if hasattr(current, "goto_prev_change"):
            current.goto_prev_change()
    
    def _on_expand_all(self) -> None:
        """Expand all tree items."""
        current = self._stack.currentWidget()
        if hasattr(current, "expand_all"):
            current.expand_all()
    
    def _on_collapse_all(self) -> None:
        """Collapse all tree items."""
        current = self._stack.currentWidget()
        if hasattr(current, "collapse_all"):
            current.collapse_all()
    
    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "prefab-diff-tool 정보",
            "<h3>prefab-diff-tool v0.1.0</h3>"
            "<p>Unity 프리팹 파일을 위한 시각적 Diff/Merge 도구</p>"
            "<p>License: MIT</p>"
            "<p><a href='https://github.com/TrueCyan/prefab-diff-tool'>GitHub</a></p>",
        )
    
    # === Signal handlers ===
    
    def _on_change_selected(self, path: str) -> None:
        """Handle change selection in diff view."""
        self._status_label.setText(path)
    
    def _on_conflict_resolved(self, remaining: int) -> None:
        """Handle conflict resolution in merge view."""
        self._update_summary()
    
    def _update_summary(self) -> None:
        """Update the summary label in status bar."""
        current = self._stack.currentWidget()
        
        if current == self._diff_view and self._diff_view:
            summary = self._diff_view.get_summary()
            self._summary_label.setText(
                f"<span style='color:#28a745'>+{summary.added}</span> "
                f"<span style='color:#dc3545'>-{summary.removed}</span> "
                f"<span style='color:#ffc107'>~{summary.modified}</span>"
            )
        elif current == self._merge_view and self._merge_view:
            conflicts = self._merge_view.get_conflict_count()
            resolved = self._merge_view.get_resolved_count()
            self._summary_label.setText(
                f"충돌: {resolved}/{conflicts} 해결됨"
            )
        else:
            self._summary_label.setText("")
