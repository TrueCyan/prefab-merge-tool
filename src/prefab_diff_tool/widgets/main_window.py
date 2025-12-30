"""
Main application window.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSettings, QUrl, QMimeData
from PySide6.QtGui import QAction, QKeySequence, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QFileDialog,
    QMessageBox,
    QStatusBar,
    QLabel,
    QStackedWidget,
    QWidget,
    QVBoxLayout,
    QToolBar,
    QToolButton,
)

from prefab_diff_tool import __version__
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

    def __init__(self, parent: Optional[QWidget] = None, unity_root: Optional[Path] = None):
        super().__init__(parent)

        self.setWindowTitle("prefab-diff-tool")
        self.setMinimumSize(1200, 800)

        # Unity project root (for GUID resolution)
        self._unity_root = unity_root

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

        # Enable drag and drop
        self.setAcceptDrops(True)

        # Setup UI
        self._setup_menu_bar()
        self._setup_toolbar()
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

        debug_action = QAction("디버그 정보(&D)...", self)
        debug_action.triggered.connect(self._on_debug_info)
        help_menu.addAction(debug_action)

        help_menu.addSeparator()

        about_action = QAction("정보(&A)...", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
    
    def _setup_toolbar(self) -> None:
        """Setup the navigation toolbar."""
        self._toolbar = QToolBar("Navigation")
        self._toolbar.setMovable(False)
        self._toolbar.setStyleSheet(
            "QToolBar { background: #353535; border: none; padding: 2px; spacing: 4px; }"
            "QToolButton { background: #454545; border: 1px solid #555; border-radius: 4px; "
            "padding: 4px 8px; color: #ddd; font-size: 11px; }"
            "QToolButton:hover { background: #505050; }"
            "QToolButton:pressed { background: #404040; }"
            "QToolButton:disabled { color: #666; background: #3a3a3a; }"
        )
        self.addToolBar(self._toolbar)

        # Previous change button
        self._prev_btn = QToolButton()
        self._prev_btn.setText("◀ 이전")
        self._prev_btn.setToolTip("이전 변경으로 이동 (P)")
        self._prev_btn.clicked.connect(self._on_prev_change)
        self._toolbar.addWidget(self._prev_btn)

        # Next change button
        self._next_btn = QToolButton()
        self._next_btn.setText("다음 ▶")
        self._next_btn.setToolTip("다음 변경으로 이동 (N)")
        self._next_btn.clicked.connect(self._on_next_change)
        self._toolbar.addWidget(self._next_btn)

        self._toolbar.addSeparator()

        # Accept all ours button (merge mode only)
        self._all_ours_btn = QToolButton()
        self._all_ours_btn.setText("모두 Ours")
        self._all_ours_btn.setToolTip("모든 충돌을 Ours로 해결")
        self._all_ours_btn.clicked.connect(self._on_accept_all_ours)
        self._all_ours_btn.setVisible(False)
        self._toolbar.addWidget(self._all_ours_btn)

        # Accept all theirs button (merge mode only)
        self._all_theirs_btn = QToolButton()
        self._all_theirs_btn.setText("모두 Theirs")
        self._all_theirs_btn.setToolTip("모든 충돌을 Theirs로 해결")
        self._all_theirs_btn.clicked.connect(self._on_accept_all_theirs)
        self._all_theirs_btn.setVisible(False)
        self._toolbar.addWidget(self._all_theirs_btn)

        # Next conflict button (merge mode only)
        self._next_conflict_btn = QToolButton()
        self._next_conflict_btn.setText("다음 충돌 ▶")
        self._next_conflict_btn.setToolTip("다음 미해결 충돌로 이동")
        self._next_conflict_btn.clicked.connect(self._on_next_conflict)
        self._next_conflict_btn.setVisible(False)
        self._toolbar.addWidget(self._next_conflict_btn)

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

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Handle drag enter event."""
        if event.mimeData().hasUrls():
            # Check if any URL is a supported file
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if self._is_supported_file(path):
                        event.acceptProposedAction()
                        return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle drop event."""
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        # Collect valid files
        files: list[Path] = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if self._is_supported_file(path):
                    files.append(path)

        if not files:
            event.ignore()
            return

        event.acceptProposedAction()

        # Handle based on number of files
        if len(files) == 1:
            self.open_file(files[0])
        elif len(files) == 2:
            self.open_diff(files[0], files[1])
        elif len(files) >= 3:
            # For 3+ files, use first 3 for merge (base, ours, theirs)
            # Ask user for output file
            output, _ = QFileDialog.getSaveFileName(
                self, "출력 파일 선택", str(files[1]), UNITY_FILE_FILTER
            )
            if output:
                self.open_merge(files[0], files[1], files[2], Path(output))

    def _is_supported_file(self, path: Path) -> bool:
        """Check if the file has a supported Unity extension."""
        supported_extensions = {".prefab", ".unity", ".asset", ".anim", ".controller", ".mat"}
        return path.suffix.lower() in supported_extensions

    # === Public methods ===
    
    def open_file(self, path: Path) -> None:
        """Open a single file for viewing - prompts for second file to compare."""
        self._current_files = [path]
        self._status_label.setText(f"파일: {path.name}")

        # Ask for second file to compare with
        other, _ = QFileDialog.getOpenFileName(
            self,
            f"비교할 파일 선택 ({path.name}와 비교)",
            str(path.parent),
            UNITY_FILE_FILTER,
        )
        if other:
            self.open_diff(path, Path(other))
        else:
            # If user cancels, show the file alone using self-comparison
            self.open_diff(path, path)
    
    def open_diff(self, left: Path, right: Path) -> None:
        """Open two files for diff comparison."""
        self._current_files = [left, right]

        # Create diff view if needed
        if not self._diff_view:
            self._diff_view = DiffView(unity_root=self._unity_root)
            self._diff_view.change_selected.connect(self._on_change_selected)
            self._stack.addWidget(self._diff_view)

        # Load files
        self._diff_view.load_diff(left, right)
        self._stack.setCurrentWidget(self._diff_view)

        # Show diff toolbar buttons, hide merge buttons
        self._all_ours_btn.setVisible(False)
        self._all_theirs_btn.setVisible(False)
        self._next_conflict_btn.setVisible(False)

        self.setWindowTitle(f"Diff: {left.name} ↔ {right.name}")
        self._status_label.setText(f"{left.name} ↔ {right.name}")
        self._update_summary()
    
    def open_merge(self, base: Path, ours: Path, theirs: Path, output: Path) -> None:
        """Open files for 3-way merge."""
        self._current_files = [base, ours, theirs]
        self._output_file = output

        # Create merge view if needed
        if not self._merge_view:
            self._merge_view = MergeView(unity_root=self._unity_root)
            self._merge_view.conflict_resolved.connect(self._on_conflict_resolved)
            self._stack.addWidget(self._merge_view)

        # Load files
        self._merge_view.load_merge(base, ours, theirs)
        self._stack.setCurrentWidget(self._merge_view)

        # Show merge toolbar buttons
        self._all_ours_btn.setVisible(True)
        self._all_theirs_btn.setVisible(True)
        self._next_conflict_btn.setVisible(True)

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

    def _on_accept_all_ours(self) -> None:
        """Accept all Ours for merge conflicts."""
        if self._merge_view:
            self._merge_view.accept_all_ours()
            self._update_summary()

    def _on_accept_all_theirs(self) -> None:
        """Accept all Theirs for merge conflicts."""
        if self._merge_view:
            self._merge_view.accept_all_theirs()
            self._update_summary()

    def _on_next_conflict(self) -> None:
        """Navigate to next unresolved conflict."""
        if self._merge_view:
            self._merge_view.goto_next_unresolved_conflict()

    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "prefab-diff-tool 정보",
            f"<h3>prefab-diff-tool v{__version__}</h3>"
            "<p>Unity 프리팹 파일을 위한 시각적 Diff/Merge 도구</p>"
            "<p>License: MIT</p>"
            "<p><a href='https://github.com/TrueCyan/prefab-diff-tool'>GitHub</a></p>",
        )

    def _on_debug_info(self) -> None:
        """Show debug information dialog."""
        from prefab_diff_tool.utils.vcs_detector import get_vcs_info

        vcs_info = get_vcs_info()

        info_text = f"""<h3>디버그 정보</h3>
<h4>Unity 프로젝트</h4>
<pre>unity_root: {self._unity_root}</pre>

<h4>현재 파일</h4>
<pre>{chr(10).join(str(f) for f in self._current_files) or '(없음)'}</pre>

<h4>Git</h4>
<pre>GIT_WORK_TREE: {vcs_info['git']['GIT_WORK_TREE']}
GIT_DIR: {vcs_info['git']['GIT_DIR']}
detected: {vcs_info['git']['detected_workspace']}</pre>

<h4>Perforce</h4>
<pre>P4ROOT: {vcs_info['perforce']['P4ROOT']}
P4CLIENT: {vcs_info['perforce']['P4CLIENT']}
detected: {vcs_info['perforce']['detected_workspace']}</pre>
"""
        QMessageBox.information(self, "디버그 정보", info_text)

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
