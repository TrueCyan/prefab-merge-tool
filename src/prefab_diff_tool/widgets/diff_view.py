"""
2-way diff view widget.
"""

from dataclasses import dataclass
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
)

from prefab_diff_tool.core.unity_model import DiffSummary


@dataclass
class DiffViewSummary:
    """Summary for status bar."""
    added: int = 0
    removed: int = 0
    modified: int = 0


class DiffView(QWidget):
    """
    Side-by-side diff view for comparing two Unity files.
    
    Layout:
    ┌─────────────────┬─────────────────────────┐
    │  Hierarchy      │  Inspector              │
    │  (TreeView)     │  (Property comparison)  │
    │                 │                         │
    │  - Added        │  Component 1            │
    │  - Removed      │  ├─ prop1: A → B        │
    │  - Modified     │  └─ prop2: unchanged    │
    └─────────────────┴─────────────────────────┘
    """
    
    # Signals
    change_selected = Signal(str)  # Emits path of selected change
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._left_path: Optional[Path] = None
        self._right_path: Optional[Path] = None
        self._changes: list = []
        self._current_change_index: int = -1
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Main splitter
        splitter = QSplitter()
        layout.addWidget(splitter)
        
        # Left side: Hierarchy tree
        hierarchy_container = QWidget()
        hierarchy_layout = QVBoxLayout(hierarchy_container)
        hierarchy_layout.setContentsMargins(4, 4, 4, 4)
        
        hierarchy_label = QLabel("계층 구조")
        hierarchy_label.setStyleSheet("font-weight: bold;")
        hierarchy_layout.addWidget(hierarchy_label)
        
        self._hierarchy_tree = QTreeView()
        self._hierarchy_tree.setHeaderHidden(True)
        hierarchy_layout.addWidget(self._hierarchy_tree)
        
        splitter.addWidget(hierarchy_container)
        
        # Right side: Inspector panel
        inspector_container = QWidget()
        inspector_layout = QVBoxLayout(inspector_container)
        inspector_layout.setContentsMargins(4, 4, 4, 4)
        
        inspector_label = QLabel("속성 비교")
        inspector_label.setStyleSheet("font-weight: bold;")
        inspector_layout.addWidget(inspector_label)
        
        self._inspector_table = QTableView()
        inspector_layout.addWidget(self._inspector_table)
        
        splitter.addWidget(inspector_container)
        
        # Set initial splitter sizes (40% tree, 60% inspector)
        splitter.setSizes([400, 600])
    
    def load_diff(self, left: Path, right: Path) -> None:
        """Load and compare two files."""
        self._left_path = left
        self._right_path = right
        
        # TODO: Implement actual diff loading
        # 1. Load both files using prefab-tool
        # 2. Convert to UnityDocument models
        # 3. Run diff algorithm
        # 4. Update tree and inspector views
        
        print(f"TODO: Load diff between {left} and {right}")
    
    def get_summary(self) -> DiffViewSummary:
        """Get summary for status bar."""
        # TODO: Calculate from actual diff result
        return DiffViewSummary(added=0, removed=0, modified=0)
    
    def goto_next_change(self) -> None:
        """Navigate to next change."""
        if not self._changes:
            return
        self._current_change_index = (self._current_change_index + 1) % len(self._changes)
        self._select_change(self._current_change_index)
    
    def goto_prev_change(self) -> None:
        """Navigate to previous change."""
        if not self._changes:
            return
        self._current_change_index = (self._current_change_index - 1) % len(self._changes)
        self._select_change(self._current_change_index)
    
    def _select_change(self, index: int) -> None:
        """Select and scroll to a change."""
        if 0 <= index < len(self._changes):
            change = self._changes[index]
            # TODO: Select in tree and scroll to view
            self.change_selected.emit(change.path)
    
    def expand_all(self) -> None:
        """Expand all tree items."""
        self._hierarchy_tree.expandAll()
    
    def collapse_all(self) -> None:
        """Collapse all tree items."""
        self._hierarchy_tree.collapseAll()
