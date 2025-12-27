"""
2-way diff view widget.
"""

import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSplitter,
    QLabel,
    QTreeView,
)

from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    DiffStatus,
    DiffResult,
    DiffSummary,
    Change,
)
from prefab_diff_tool.core.loader import load_unity_file
from prefab_diff_tool.models.tree_model import HierarchyTreeModel
from prefab_diff_tool.widgets.inspector_widget import InspectorWidget
from prefab_diff_tool.utils.guid_resolver import GuidResolver


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
    +------------------+----------------------------+
    """

    change_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._left_path: Optional[Path] = None
        self._right_path: Optional[Path] = None
        self._left_doc: Optional[UnityDocument] = None
        self._right_doc: Optional[UnityDocument] = None
        self._diff_result: Optional[DiffResult] = None
        self._changes: list[Change] = []
        self._current_change_index: int = -1
        self._guid_resolver: Optional[GuidResolver] = None

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

        hierarchy_label = QLabel("Hierarchy")
        hierarchy_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #888; padding: 2px 0;")
        hierarchy_label.setFixedHeight(20)
        hierarchy_layout.addWidget(hierarchy_label)

        # Side-by-side tree views
        tree_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left tree
        left_tree_container = QWidget()
        left_tree_layout = QVBoxLayout(left_tree_container)
        left_tree_layout.setContentsMargins(0, 0, 0, 0)

        self._left_label = QLabel("왼쪽 (이전)")
        self._left_label.setStyleSheet("color: #888; font-size: 11px;")
        left_tree_layout.addWidget(self._left_label)

        self._left_tree = QTreeView()
        self._left_tree.setHeaderHidden(True)
        self._left_tree.setModel(self._left_model)
        self._left_tree.setIndentation(16)
        self._left_tree.clicked.connect(self._on_left_tree_clicked)
        left_tree_layout.addWidget(self._left_tree)

        tree_splitter.addWidget(left_tree_container)

        # Right tree
        right_tree_container = QWidget()
        right_tree_layout = QVBoxLayout(right_tree_container)
        right_tree_layout.setContentsMargins(0, 0, 0, 0)

        self._right_label = QLabel("오른쪽 (새)")
        self._right_label.setStyleSheet("color: #888; font-size: 11px;")
        right_tree_layout.addWidget(self._right_label)

        self._right_tree = QTreeView()
        self._right_tree.setHeaderHidden(True)
        self._right_tree.setModel(self._right_model)
        self._right_tree.setIndentation(16)
        self._right_tree.clicked.connect(self._on_right_tree_clicked)
        right_tree_layout.addWidget(self._right_tree)

        tree_splitter.addWidget(right_tree_container)

        hierarchy_layout.addWidget(tree_splitter)
        splitter.addWidget(hierarchy_container)

        # Right side: Unity-style Inspector panel
        inspector_container = QWidget()
        inspector_layout = QVBoxLayout(inspector_container)
        inspector_layout.setContentsMargins(4, 4, 4, 4)

        inspector_label = QLabel("Inspector")
        inspector_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #888; padding: 2px 0;")
        inspector_label.setFixedHeight(20)
        inspector_layout.addWidget(inspector_label)

        self._inspector = InspectorWidget()
        # Connect reference clicked signals for navigation
        self._inspector.reference_clicked.connect(self._on_reference_clicked)
        self._inspector.external_reference_clicked.connect(self._on_external_reference_clicked)
        inspector_layout.addWidget(self._inspector)

        splitter.addWidget(inspector_container)

        # Set initial splitter sizes (40% tree, 60% inspector)
        splitter.setSizes([400, 600])

    def load_diff(self, left: Path, right: Path) -> None:
        """Load and compare two files."""
        self._left_path = left
        self._right_path = right

        self._left_label.setText(f"왼쪽: {left.name}")
        self._right_label.setText(f"오른쪽: {right.name}")

        try:
            self._left_doc = load_unity_file(left)
            self._right_doc = load_unity_file(right)

            # Setup GUID resolver for external reference navigation
            if self._right_doc and self._right_doc.project_root:
                self._guid_resolver = GuidResolver()
                self._guid_resolver.set_project_root(Path(self._right_doc.project_root))

            self._perform_diff()

            self._left_model.set_document(self._left_doc)
            self._right_model.set_document(self._right_doc)

            # Set document for Inspector to resolve internal references
            self._inspector.set_document(self._right_doc)

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

            left_comps = {c.file_id: c for c in left_go.components}
            right_comps = {c.file_id: c for c in right_go.components}

            has_changes = False
            for comp_id in left_comps.keys() & right_comps.keys():
                left_comp = left_comps[comp_id]
                right_comp = right_comps[comp_id]

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
        """Handle left tree selection - show GameObject in inspector."""
        data = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, UnityGameObject):
            other_obj = None
            if self._right_doc:
                other_obj = self._right_doc.get_object(data.file_id)
            # Set document for resolving references (use left doc for left tree)
            self._inspector.set_document(self._left_doc)
            self._inspector.set_game_object(data, other_obj)

            # Sync selection with right tree
            right_index = self._right_model.find_index_by_file_id(data.file_id)
            if right_index.isValid():
                self._right_tree.setCurrentIndex(right_index)
                self._right_tree.scrollTo(right_index)

    def _on_right_tree_clicked(self, index) -> None:
        """Handle right tree selection - show GameObject in inspector."""
        data = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, UnityGameObject):
            other_obj = None
            if self._left_doc:
                other_obj = self._left_doc.get_object(data.file_id)
            # Set document for resolving references (use right doc for right tree)
            self._inspector.set_document(self._right_doc)
            self._inspector.set_game_object(data, other_obj)

            # Sync selection with left tree
            left_index = self._left_model.find_index_by_file_id(data.file_id)
            if left_index.isValid():
                self._left_tree.setCurrentIndex(left_index)
                self._left_tree.scrollTo(left_index)

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

    def _on_reference_clicked(self, file_id: str, guid: str) -> None:
        """Handle internal reference click - navigate to the referenced object."""
        if not file_id or file_id == "0":
            return

        # Determine the target file_id to navigate to
        # If the reference is to a Component, find its owner GameObject
        target_file_id = file_id
        is_component_ref = False

        # Check in right document first
        if self._right_doc:
            # Check if it's a GameObject
            if self._right_doc.all_objects.get(file_id):
                target_file_id = file_id
            # Check if it's a Component
            elif self._right_doc.all_components.get(file_id):
                is_component_ref = True
                owner = self._right_doc.get_component_owner(file_id)
                if owner:
                    target_file_id = owner.file_id
        # Fallback to left document
        elif self._left_doc:
            if self._left_doc.all_objects.get(file_id):
                target_file_id = file_id
            elif self._left_doc.all_components.get(file_id):
                is_component_ref = True
                owner = self._left_doc.get_component_owner(file_id)
                if owner:
                    target_file_id = owner.file_id

        # Try to find the object in the right tree first
        right_index = self._right_model.find_index_by_file_id(target_file_id)
        if right_index.isValid():
            self._right_tree.setCurrentIndex(right_index)
            self._right_tree.scrollTo(right_index)

            # Also sync with left tree if available
            left_index = self._left_model.find_index_by_file_id(target_file_id)
            if left_index.isValid():
                self._left_tree.setCurrentIndex(left_index)
                self._left_tree.scrollTo(left_index)

            # Update inspector with selected object
            data = right_index.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, UnityGameObject):
                other_obj = None
                if self._left_doc:
                    other_obj = self._left_doc.get_object(target_file_id)
                self._inspector.set_document(self._right_doc)
                self._inspector.set_game_object(data, other_obj)
                # If it was a component reference, scroll to that component
                if is_component_ref:
                    self._inspector.scroll_to_component(file_id)
            return

        # If not found in right, try left tree
        left_index = self._left_model.find_index_by_file_id(target_file_id)
        if left_index.isValid():
            self._left_tree.setCurrentIndex(left_index)
            self._left_tree.scrollTo(left_index)

            # Update inspector
            data = left_index.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, UnityGameObject):
                other_obj = None
                if self._right_doc:
                    other_obj = self._right_doc.get_object(target_file_id)
                self._inspector.set_document(self._left_doc)
                self._inspector.set_game_object(data, other_obj)
                # If it was a component reference, scroll to that component
                if is_component_ref:
                    self._inspector.scroll_to_component(file_id)

    def _on_external_reference_clicked(self, guid: str) -> None:
        """Handle external reference click - open file explorer to show the asset."""
        if not guid or not self._guid_resolver:
            return

        # Resolve GUID to file path
        asset_path = self._guid_resolver.resolve_path(guid)
        if not asset_path or not asset_path.exists():
            return

        # Open file explorer and select the file
        self._show_in_file_explorer(asset_path)

    def _show_in_file_explorer(self, path: Path) -> None:
        """Open file explorer and select/highlight the given file."""
        try:
            system = platform.system()
            if system == "Windows":
                # Windows: explorer /select,<path>
                subprocess.run(["explorer", "/select,", str(path)], check=False)
            elif system == "Darwin":
                # macOS: open -R <path>
                subprocess.run(["open", "-R", str(path)], check=False)
            else:
                # Linux: open parent folder (file selection not universally supported)
                parent = path.parent
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(parent)))
        except Exception:
            # Fallback: just open the parent folder
            parent = path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(parent)))
