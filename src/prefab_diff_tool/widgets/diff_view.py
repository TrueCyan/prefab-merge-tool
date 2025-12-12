"""
2-way diff view widget.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QTreeView,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from PySide6.QtGui import QColor, QBrush

from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
    DiffStatus,
    DiffResult,
    DiffSummary,
    Change,
)
from prefab_diff_tool.core.loader import load_unity_file
from prefab_diff_tool.models.tree_model import HierarchyTreeModel, NodeType
from prefab_diff_tool.utils.colors import DiffColors


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
    +------------------+----------------------------+
    |  Hierarchy       |  Inspector                 |
    |  (TreeView)      |  (Property comparison)     |
    |                  |                            |
    |  - Added         |  Component 1               |
    |  - Removed       |  +- prop1: A -> B          |
    |  - Modified      |  +- prop2: unchanged       |
    +------------------+----------------------------+
    """

    # Signals
    change_selected = Signal(str)  # Emits path of selected change

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._left_path: Optional[Path] = None
        self._right_path: Optional[Path] = None
        self._left_doc: Optional[UnityDocument] = None
        self._right_doc: Optional[UnityDocument] = None
        self._diff_result: Optional[DiffResult] = None
        self._changes: list[Change] = []
        self._current_change_index: int = -1

        # Models
        self._left_model = HierarchyTreeModel()
        self._right_model = HierarchyTreeModel()

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main splitter
        splitter = QSplitter()
        layout.addWidget(splitter)

        # Left side: Two hierarchy trees side-by-side
        hierarchy_container = QWidget()
        hierarchy_layout = QVBoxLayout(hierarchy_container)
        hierarchy_layout.setContentsMargins(4, 4, 4, 4)

        hierarchy_label = QLabel("계층 구조 비교")
        hierarchy_label.setStyleSheet("font-weight: bold;")
        hierarchy_layout.addWidget(hierarchy_label)

        # Side-by-side tree views
        tree_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left tree
        left_tree_container = QWidget()
        left_tree_layout = QVBoxLayout(left_tree_container)
        left_tree_layout.setContentsMargins(0, 0, 0, 0)

        self._left_label = QLabel("왼쪽 (이전)")
        self._left_label.setStyleSheet("color: #888;")
        left_tree_layout.addWidget(self._left_label)

        self._left_tree = QTreeView()
        self._left_tree.setHeaderHidden(True)
        self._left_tree.setModel(self._left_model)
        self._left_tree.clicked.connect(self._on_left_tree_clicked)
        left_tree_layout.addWidget(self._left_tree)

        tree_splitter.addWidget(left_tree_container)

        # Right tree
        right_tree_container = QWidget()
        right_tree_layout = QVBoxLayout(right_tree_container)
        right_tree_layout.setContentsMargins(0, 0, 0, 0)

        self._right_label = QLabel("오른쪽 (새)")
        self._right_label.setStyleSheet("color: #888;")
        right_tree_layout.addWidget(self._right_label)

        self._right_tree = QTreeView()
        self._right_tree.setHeaderHidden(True)
        self._right_tree.setModel(self._right_model)
        self._right_tree.clicked.connect(self._on_right_tree_clicked)
        right_tree_layout.addWidget(self._right_tree)

        tree_splitter.addWidget(right_tree_container)

        hierarchy_layout.addWidget(tree_splitter)
        splitter.addWidget(hierarchy_container)

        # Right side: Inspector panel with property comparison
        inspector_container = QWidget()
        inspector_layout = QVBoxLayout(inspector_container)
        inspector_layout.setContentsMargins(4, 4, 4, 4)

        inspector_label = QLabel("속성 비교")
        inspector_label.setStyleSheet("font-weight: bold;")
        inspector_layout.addWidget(inspector_label)

        self._inspector_table = QTableWidget()
        self._inspector_table.setColumnCount(3)
        self._inspector_table.setHorizontalHeaderLabels(["속성", "왼쪽", "오른쪽"])
        self._inspector_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._inspector_table.setAlternatingRowColors(True)
        self._inspector_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        inspector_layout.addWidget(self._inspector_table)

        splitter.addWidget(inspector_container)

        # Set initial splitter sizes (50% tree, 50% inspector)
        splitter.setSizes([500, 500])

    def load_diff(self, left: Path, right: Path) -> None:
        """Load and compare two files."""
        self._left_path = left
        self._right_path = right

        # Update labels
        self._left_label.setText(f"왼쪽: {left.name}")
        self._right_label.setText(f"오른쪽: {right.name}")

        try:
            # Load both files
            self._left_doc = load_unity_file(left)
            self._right_doc = load_unity_file(right)

            # Perform diff
            self._perform_diff()

            # Update tree models
            self._left_model.set_document(self._left_doc)
            self._right_model.set_document(self._right_doc)

            # Expand trees
            self._left_tree.expandAll()
            self._right_tree.expandAll()

        except Exception as e:
            print(f"Error loading diff: {e}")
            import traceback
            traceback.print_exc()

    def _perform_diff(self) -> None:
        """Perform diff between left and right documents."""
        if not self._left_doc or not self._right_doc:
            return

        self._changes = []
        summary = DiffSummary()

        # Build lookup maps
        left_objects = {go.file_id: go for go in self._left_doc.iter_all_objects()}
        right_objects = {go.file_id: go for go in self._right_doc.iter_all_objects()}

        left_components = self._left_doc.all_components
        right_components = self._right_doc.all_components

        # Find added objects (in right but not in left)
        for file_id, go in right_objects.items():
            if file_id not in left_objects:
                go.diff_status = DiffStatus.ADDED
                summary.added_objects += 1
                self._changes.append(Change(
                    path=go.get_path(),
                    status=DiffStatus.ADDED,
                    right_value=go.name,
                    object_id=file_id,
                ))

        # Find removed objects (in left but not in right)
        for file_id, go in left_objects.items():
            if file_id not in right_objects:
                go.diff_status = DiffStatus.REMOVED
                summary.removed_objects += 1
                self._changes.append(Change(
                    path=go.get_path(),
                    status=DiffStatus.REMOVED,
                    left_value=go.name,
                    object_id=file_id,
                ))

        # Find added components
        for file_id, comp in right_components.items():
            if file_id not in left_components:
                comp.diff_status = DiffStatus.ADDED
                summary.added_components += 1

        # Find removed components
        for file_id, comp in left_components.items():
            if file_id not in right_components:
                comp.diff_status = DiffStatus.REMOVED
                summary.removed_components += 1

        # Compare existing objects and their properties
        for file_id in left_objects.keys() & right_objects.keys():
            left_go = left_objects[file_id]
            right_go = right_objects[file_id]

            # Compare components
            left_comps = {c.file_id: c for c in left_go.components}
            right_comps = {c.file_id: c for c in right_go.components}

            has_changes = False
            for comp_id in left_comps.keys() & right_comps.keys():
                left_comp = left_comps[comp_id]
                right_comp = right_comps[comp_id]

                # Compare properties
                left_props = {p.path: p for p in left_comp.properties}
                right_props = {p.path: p for p in right_comp.properties}

                for prop_path in left_props.keys() | right_props.keys():
                    left_prop = left_props.get(prop_path)
                    right_prop = right_props.get(prop_path)

                    if left_prop and right_prop:
                        if left_prop.value != right_prop.value:
                            right_prop.diff_status = DiffStatus.MODIFIED
                            right_prop.old_value = left_prop.value
                            left_comp.diff_status = DiffStatus.MODIFIED
                            right_comp.diff_status = DiffStatus.MODIFIED
                            has_changes = True
                            summary.modified_properties += 1

                            self._changes.append(Change(
                                path=f"{right_go.get_path()}.{right_comp.type_name}.{prop_path}",
                                status=DiffStatus.MODIFIED,
                                left_value=left_prop.value,
                                right_value=right_prop.value,
                                object_id=file_id,
                                component_type=right_comp.type_name,
                            ))

            if has_changes:
                left_go.diff_status = DiffStatus.MODIFIED
                right_go.diff_status = DiffStatus.MODIFIED
                summary.modified_objects += 1

        self._diff_result = DiffResult(
            left=self._left_doc,
            right=self._right_doc,
            changes=self._changes,
            summary=summary,
        )

    def _on_left_tree_clicked(self, index) -> None:
        """Handle left tree selection."""
        data = index.data(Qt.ItemDataRole.UserRole)
        if data:
            self._show_properties(data, "left")

            # Try to find and select corresponding item in right tree
            if isinstance(data, (UnityGameObject, UnityComponent)):
                right_index = self._right_model.find_index_by_file_id(data.file_id)
                if right_index.isValid():
                    self._right_tree.setCurrentIndex(right_index)
                    self._right_tree.scrollTo(right_index)

    def _on_right_tree_clicked(self, index) -> None:
        """Handle right tree selection."""
        data = index.data(Qt.ItemDataRole.UserRole)
        if data:
            self._show_properties(data, "right")

            # Try to find and select corresponding item in left tree
            if isinstance(data, (UnityGameObject, UnityComponent)):
                left_index = self._left_model.find_index_by_file_id(data.file_id)
                if left_index.isValid():
                    self._left_tree.setCurrentIndex(left_index)
                    self._left_tree.scrollTo(left_index)

    def _show_properties(
        self,
        item: UnityGameObject | UnityComponent,
        side: str,
    ) -> None:
        """Show properties of the selected item in the inspector."""
        self._inspector_table.setRowCount(0)

        if isinstance(item, UnityGameObject):
            # Show GameObject info
            self._add_property_row("Name", item.name, "")
            self._add_property_row("FileID", item.file_id, "")
            self._add_property_row("Layer", str(item.layer), "")
            self._add_property_row("Tag", item.tag, "")
            self._add_property_row("Active", str(item.is_active), "")

            # Show components
            for comp in item.components:
                self._add_separator_row(comp.script_name or comp.type_name)
                self._show_component_properties(comp, side)

        elif isinstance(item, UnityComponent):
            self._show_component_properties(item, side)

    def _show_component_properties(
        self,
        comp: UnityComponent,
        side: str,
    ) -> None:
        """Show component properties with diff highlighting."""
        # Find corresponding component in other document
        other_comp = None
        if side == "left" and self._right_doc:
            other_comp = self._right_doc.get_component(comp.file_id)
        elif side == "right" and self._left_doc:
            other_comp = self._left_doc.get_component(comp.file_id)

        other_props = {}
        if other_comp:
            other_props = {p.path: p for p in other_comp.properties}

        for prop in comp.properties:
            left_val = ""
            right_val = ""
            is_changed = False

            if side == "left":
                left_val = self._format_value(prop.value)
                other_prop = other_props.get(prop.path)
                if other_prop:
                    right_val = self._format_value(other_prop.value)
                    is_changed = prop.value != other_prop.value
            else:
                right_val = self._format_value(prop.value)
                other_prop = other_props.get(prop.path)
                if other_prop:
                    left_val = self._format_value(other_prop.value)
                    is_changed = prop.value != other_prop.value

            self._add_property_row(prop.name, left_val, right_val, is_changed)

    def _format_value(self, value) -> str:
        """Format a value for display."""
        if value is None:
            return "<null>"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, dict)):
            import json
            try:
                return json.dumps(value, ensure_ascii=False, indent=None)[:100]
            except Exception:
                return str(value)[:100]
        return str(value)[:100]

    def _add_property_row(
        self,
        name: str,
        left_val: str,
        right_val: str,
        is_changed: bool = False,
    ) -> None:
        """Add a row to the properties table."""
        row = self._inspector_table.rowCount()
        self._inspector_table.insertRow(row)

        name_item = QTableWidgetItem(name)
        left_item = QTableWidgetItem(left_val)
        right_item = QTableWidgetItem(right_val)

        if is_changed:
            bg_color = QColor(DiffColors.MODIFIED_BG_DARK)
            for item in [name_item, left_item, right_item]:
                item.setBackground(QBrush(bg_color))

        self._inspector_table.setItem(row, 0, name_item)
        self._inspector_table.setItem(row, 1, left_item)
        self._inspector_table.setItem(row, 2, right_item)

    def _add_separator_row(self, label: str) -> None:
        """Add a separator/header row."""
        row = self._inspector_table.rowCount()
        self._inspector_table.insertRow(row)

        item = QTableWidgetItem(f"=== {label} ===")
        item.setBackground(QBrush(QColor(60, 60, 60)))
        font = item.font()
        font.setBold(True)
        item.setFont(font)

        self._inspector_table.setItem(row, 0, item)
        self._inspector_table.setSpan(row, 0, 1, 3)

    def get_summary(self) -> DiffViewSummary:
        """Get summary for status bar."""
        if self._diff_result and self._diff_result.summary:
            s = self._diff_result.summary
            return DiffViewSummary(
                added=s.added_objects + s.added_components,
                removed=s.removed_objects + s.removed_components,
                modified=s.modified_objects,
            )
        return DiffViewSummary()

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

            # Find and select in tree
            if change.object_id:
                right_index = self._right_model.find_index_by_file_id(change.object_id)
                if right_index.isValid():
                    self._right_tree.setCurrentIndex(right_index)
                    self._right_tree.scrollTo(right_index)

                left_index = self._left_model.find_index_by_file_id(change.object_id)
                if left_index.isValid():
                    self._left_tree.setCurrentIndex(left_index)
                    self._left_tree.scrollTo(left_index)

            self.change_selected.emit(change.path)

    def expand_all(self) -> None:
        """Expand all tree items."""
        self._left_tree.expandAll()
        self._right_tree.expandAll()

    def collapse_all(self) -> None:
        """Collapse all tree items."""
        self._left_tree.collapseAll()
        self._right_tree.collapseAll()
