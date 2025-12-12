"""
3-way merge view widget.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QTreeView,
    QTableView,
    QPushButton,
    QFrame,
)


class MergeView(QWidget):
    """
    3-way merge view for resolving conflicts.
    
    Layout:
    ┌───────────┬───────────┬───────────┐
    │   BASE    │   OURS    │  THEIRS   │
    ├───────────┴───────────┴───────────┤
    │           RESULT / Conflicts       │
    └────────────────────────────────────┘
    """
    
    # Signals
    conflict_resolved = Signal(int)  # Emits remaining conflict count
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._base_path: Optional[Path] = None
        self._ours_path: Optional[Path] = None
        self._theirs_path: Optional[Path] = None
        
        self._conflicts: list = []
        self._unsaved_changes: bool = False
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Main vertical splitter
        main_splitter = QSplitter()
        main_splitter.setOrientation(2)  # Vertical
        layout.addWidget(main_splitter)
        
        # Top: 3-way comparison
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(4, 4, 4, 4)
        
        # BASE panel
        base_panel = self._create_panel("BASE (공통 조상)")
        top_layout.addWidget(base_panel)
        
        # OURS panel
        ours_panel = self._create_panel("OURS (내 변경)")
        top_layout.addWidget(ours_panel)
        
        # THEIRS panel
        theirs_panel = self._create_panel("THEIRS (상대 변경)")
        top_layout.addWidget(theirs_panel)
        
        main_splitter.addWidget(top_widget)
        
        # Bottom: Result and conflict resolution
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(4, 4, 4, 4)
        
        # Header with buttons
        header = QHBoxLayout()
        
        result_label = QLabel("병합 결과")
        result_label.setStyleSheet("font-weight: bold;")
        header.addWidget(result_label)
        
        header.addStretch()
        
        # Conflict navigation
        self._conflict_label = QLabel("충돌: 0/0")
        header.addWidget(self._conflict_label)
        
        prev_btn = QPushButton("◀ 이전")
        prev_btn.clicked.connect(self._on_prev_conflict)
        header.addWidget(prev_btn)
        
        next_btn = QPushButton("다음 ▶")
        next_btn.clicked.connect(self._on_next_conflict)
        header.addWidget(next_btn)
        
        header.addSpacing(20)
        
        # Quick resolution buttons
        accept_ours_btn = QPushButton("모두 Ours")
        accept_ours_btn.clicked.connect(self._on_accept_all_ours)
        header.addWidget(accept_ours_btn)
        
        accept_theirs_btn = QPushButton("모두 Theirs")
        accept_theirs_btn.clicked.connect(self._on_accept_all_theirs)
        header.addWidget(accept_theirs_btn)
        
        bottom_layout.addLayout(header)
        
        # Conflict list / Result tree
        self._result_tree = QTreeView()
        bottom_layout.addWidget(self._result_tree)
        
        main_splitter.addWidget(bottom_widget)
        
        # Set initial sizes (60% top, 40% bottom)
        main_splitter.setSizes([600, 400])
    
    def _create_panel(self, title: str) -> QFrame:
        """Create a panel for BASE/OURS/THEIRS."""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        
        label = QLabel(title)
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)
        
        tree = QTreeView()
        tree.setHeaderHidden(True)
        layout.addWidget(tree)
        
        return frame
    
    def load_merge(self, base: Path, ours: Path, theirs: Path) -> None:
        """Load files for 3-way merge."""
        self._base_path = base
        self._ours_path = ours
        self._theirs_path = theirs
        
        # TODO: Implement actual merge loading
        # 1. Load all three files using prefab-tool
        # 2. Perform 3-way diff
        # 3. Identify conflicts
        # 4. Update UI
        
        print(f"TODO: Load merge - base={base}, ours={ours}, theirs={theirs}")
    
    def save_result(self, output: Path) -> None:
        """Save the merge result."""
        # TODO: Generate merged document and save
        print(f"TODO: Save merge result to {output}")
        self._unsaved_changes = False
    
    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes."""
        return self._unsaved_changes
    
    def has_unresolved_conflicts(self) -> bool:
        """Check if there are unresolved conflicts."""
        return any(not c.is_resolved for c in self._conflicts) if self._conflicts else False
    
    def get_conflict_count(self) -> int:
        """Get total number of conflicts."""
        return len(self._conflicts)
    
    def get_resolved_count(self) -> int:
        """Get number of resolved conflicts."""
        return sum(1 for c in self._conflicts if hasattr(c, 'is_resolved') and c.is_resolved)
    
    def _on_prev_conflict(self) -> None:
        """Navigate to previous conflict."""
        # TODO: Implement
        pass
    
    def _on_next_conflict(self) -> None:
        """Navigate to next conflict."""
        # TODO: Implement
        pass
    
    def _on_accept_all_ours(self) -> None:
        """Accept all 'ours' for conflicts."""
        # TODO: Implement
        self._unsaved_changes = True
        self.conflict_resolved.emit(0)
    
    def _on_accept_all_theirs(self) -> None:
        """Accept all 'theirs' for conflicts."""
        # TODO: Implement
        self._unsaved_changes = True
        self.conflict_resolved.emit(0)
    
    def expand_all(self) -> None:
        """Expand all tree items."""
        self._result_tree.expandAll()
    
    def collapse_all(self) -> None:
        """Collapse all tree items."""
        self._result_tree.collapseAll()
