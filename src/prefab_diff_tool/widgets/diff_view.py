"""
2-way diff view widget.
"""

import logging
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from unityflow import UnityYAMLDocument
from unityflow.semantic_diff import semantic_diff, ChangeType

from prefab_diff_tool.core.unity_model import (
    Change,
    DiffResult,
    DiffStatus,
    DiffSummary,
    UnityDocument,
    UnityGameObject,
)
from prefab_diff_tool.models.tree_model import HierarchyTreeModel
from prefab_diff_tool.utils.guid_resolver import GuidResolver
from prefab_diff_tool.widgets.inspector_widget import InspectorWidget
from prefab_diff_tool.widgets.loading_widget import (
    FileLoadingWorker,
    LoadingProgressWidget,
)


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
    loading_started = Signal()
    loading_finished = Signal()

    def __init__(self, parent: Optional[QWidget] = None, unity_root: Optional[Path] = None):
        super().__init__(parent)

        self._left_path: Optional[Path] = None
        self._right_path: Optional[Path] = None
        self._left_doc: Optional[UnityDocument] = None
        self._right_doc: Optional[UnityDocument] = None
        self._diff_result: Optional[DiffResult] = None
        self._changes: list[Change] = []
        self._current_change_index: int = -1
        self._guid_resolver: Optional[GuidResolver] = None
        self._unity_root: Optional[Path] = unity_root

        self._left_model = HierarchyTreeModel()
        self._right_model = HierarchyTreeModel()

        # Loading worker
        self._loading_worker: Optional[FileLoadingWorker] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Stacked widget for loading/content switching
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Loading page
        self._loading_widget = LoadingProgressWidget()
        self._loading_widget.set_title("Loading files...")
        self._stack.addWidget(self._loading_widget)

        # Content page
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Main splitter
        splitter = QSplitter()
        content_layout.addWidget(splitter)

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

        # Synchronize scrolling between left and right trees
        self._sync_scroll_enabled = True
        self._left_tree.verticalScrollBar().valueChanged.connect(self._on_left_scroll)
        self._right_tree.verticalScrollBar().valueChanged.connect(self._on_right_scroll)

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

        # Add content widget to stack
        self._stack.addWidget(content_widget)

        # Show content by default
        self._stack.setCurrentIndex(1)

    def load_diff(self, left: Path, right: Path) -> None:
        """Load and compare two files asynchronously."""
        self._left_path = left
        self._right_path = right

        self._left_label.setText(f"왼쪽: {left.name}")
        self._right_label.setText(f"오른쪽: {right.name}")

        # Show loading screen
        self._loading_widget.set_title("Loading files...")
        self._loading_widget.update_progress(0, 3, "Preparing to load...")
        self._stack.setCurrentIndex(0)
        self.loading_started.emit()

        # Cancel any existing worker
        if self._loading_worker and self._loading_worker.isRunning():
            self._loading_worker.cancel()
            self._loading_worker.wait()

        # Start async loading with polling-based progress
        self._loading_worker = FileLoadingWorker([left, right], unity_root=self._unity_root)
        self._loading_widget.start_polling(self._loading_worker.progress_state)
        self._loading_worker.file_loaded.connect(self._on_file_loaded)
        self._loading_worker.indexing_started.connect(self._on_indexing_started)
        self._loading_worker.finished.connect(self._on_loading_finished)
        self._loading_worker.error.connect(self._on_loading_error)
        self._loading_worker.start()

    def _on_loading_progress(self, current: int, total: int, message: str) -> None:
        """Handle loading progress updates."""
        self._loading_widget.update_progress(current, total, message)

    def _on_file_loaded(self, doc: UnityDocument, index: int) -> None:
        """Handle individual file loaded."""
        if index == 0:
            self._left_doc = doc
        elif index == 1:
            self._right_doc = doc

    def _on_indexing_started(self) -> None:
        """Handle indexing phase start."""
        self._loading_widget.set_title("Indexing assets...")

    def _on_loading_finished(self) -> None:
        """Handle loading completion."""
        # Stop polling
        self._loading_widget.stop_polling()

        try:
            # Get GUID resolver from worker
            if self._loading_worker:
                self._guid_resolver = self._loading_worker.get_guid_resolver()

            # Perform diff
            self._perform_diff()

            # Update UI
            self._left_model.set_document(self._left_doc)
            self._right_model.set_document(self._right_doc)

            # Set document for Inspector to resolve internal references
            self._inspector.set_document(self._right_doc)

            # Expand all trees
            self._left_tree.expandAll()
            self._right_tree.expandAll()

            # Switch to content view
            self._stack.setCurrentIndex(1)
            self.loading_finished.emit()

        except Exception as e:
            print(f"Error finalizing diff: {e}")
            import traceback
            traceback.print_exc()
            self._stack.setCurrentIndex(1)
            self.loading_finished.emit()

    def _on_loading_error(self, error: str) -> None:
        """Handle loading error."""
        # Stop polling (don't show 100% on error)
        self._loading_widget.stop_polling(error=True)

        print(f"Error loading diff: {error}")
        self._loading_widget.update_progress(0, 1, f"Error: {error}")
        # Switch to content view after a delay
        QTimer.singleShot(2000, lambda: self._stack.setCurrentIndex(1))
        self.loading_finished.emit()

    def _perform_diff(self) -> None:
        """Perform semantic diff between left and right documents."""
        if not self._left_doc or not self._right_doc:
            return

        self._changes = []
        summary = DiffSummary()

        # Load raw UnityYAMLDocument for semantic diff
        try:
            left_raw = UnityYAMLDocument.load(self._left_doc.file_path)
            right_raw = UnityYAMLDocument.load(self._right_doc.file_path)
            semantic_result = semantic_diff(left_raw, right_raw)
        except Exception as e:
            logger.warning(f"Semantic diff failed, falling back to basic diff: {e}")
            self._perform_basic_diff()
            return

        # Build lookup maps for UI model
        left_objects = {go.file_id: go for go in self._left_doc.iter_all_objects()}
        right_objects = {go.file_id: go for go in self._right_doc.iter_all_objects()}
        left_components = self._left_doc.all_components
        right_components = self._right_doc.all_components

        # Track which objects/components have been modified
        modified_objects: set[str] = set()
        modified_components: set[str] = set()

        # Process semantic diff property changes
        for change in semantic_result.property_changes:
            # Map ChangeType to DiffStatus
            if change.change_type == ChangeType.ADDED:
                status = DiffStatus.ADDED
                summary.modified_properties += 1
            elif change.change_type == ChangeType.REMOVED:
                status = DiffStatus.REMOVED
                summary.modified_properties += 1
            else:  # MODIFIED
                status = DiffStatus.MODIFIED
                summary.modified_properties += 1

            # Create change record using correct attribute names
            component_type = change.class_name or ""
            go_name = change.game_object_name or ""
            file_id = str(change.file_id) if change.file_id else ""

            self._changes.append(Change(
                path=f"{go_name}.{component_type}.{change.property_path}",
                status=status,
                left_value=change.old_value,
                right_value=change.new_value,
                object_id=file_id,
                component_type=component_type,
            ))

            # Mark component as modified
            if file_id:
                modified_components.add(file_id)
                if file_id in right_components:
                    right_components[file_id].diff_status = DiffStatus.MODIFIED
                if file_id in left_components:
                    left_components[file_id].diff_status = DiffStatus.MODIFIED

        # Update object diff status based on component changes
        for comp_id in modified_components:
            # Find owner GameObject and mark it
            for go in right_objects.values():
                for comp in go.components:
                    if comp.file_id == comp_id:
                        if go.file_id not in modified_objects:
                            go.diff_status = DiffStatus.MODIFIED
                            modified_objects.add(go.file_id)
                            summary.modified_objects += 1
                        break

            for go in left_objects.values():
                for comp in go.components:
                    if comp.file_id == comp_id:
                        go.diff_status = DiffStatus.MODIFIED
                        break

        # Check for added/removed objects (not covered by property changes)
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

        # Check for added/removed components
        for file_id, comp in right_components.items():
            if file_id not in left_components:
                comp.diff_status = DiffStatus.ADDED
                summary.added_components += 1

        for file_id, comp in left_components.items():
            if file_id not in right_components:
                comp.diff_status = DiffStatus.REMOVED
                summary.removed_components += 1

        self._diff_result = DiffResult(
            left=self._left_doc,
            right=self._right_doc,
            changes=self._changes,
            summary=summary,
        )

    def _perform_basic_diff(self) -> None:
        """Fallback to basic diff when semantic diff is not available."""
        self._changes = []
        summary = DiffSummary()

        left_objects = {go.file_id: go for go in self._left_doc.iter_all_objects()}
        right_objects = {go.file_id: go for go in self._right_doc.iter_all_objects()}

        left_components = self._left_doc.all_components
        right_components = self._right_doc.all_components

        # Find added objects
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

        # Find removed objects
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

        # Find added/removed components
        for file_id, comp in right_components.items():
            if file_id not in left_components:
                comp.diff_status = DiffStatus.ADDED
                summary.added_components += 1

        for file_id, comp in left_components.items():
            if file_id not in right_components:
                comp.diff_status = DiffStatus.REMOVED
                summary.removed_components += 1

        # Compare existing objects
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

    def _on_left_scroll(self, value: int) -> None:
        """Sync right tree scroll when left tree scrolls."""
        if self._sync_scroll_enabled:
            self._sync_scroll_enabled = False
            self._right_tree.verticalScrollBar().setValue(value)
            self._sync_scroll_enabled = True

    def _on_right_scroll(self, value: int) -> None:
        """Sync left tree scroll when right tree scrolls."""
        if self._sync_scroll_enabled:
            self._sync_scroll_enabled = False
            self._left_tree.verticalScrollBar().setValue(value)
            self._sync_scroll_enabled = True

    def _on_left_tree_clicked(self, index) -> None:
        """Handle left tree selection - show GameObject in inspector (uses right doc for display)."""
        data = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, UnityGameObject):
            # Always use right document for display (unified style)
            right_obj = None
            if self._right_doc:
                right_obj = self._right_doc.get_object(data.file_id)
            # If object exists in right doc, display that; otherwise show left
            if right_obj:
                self._inspector.set_document(self._right_doc)
                self._inspector.set_game_object(right_obj, data)
            else:
                self._inspector.set_document(self._left_doc)
                self._inspector.set_game_object(data, None)

            # Sync selection with right tree
            right_index = self._right_model.find_index_by_file_id(data.file_id)
            if right_index.isValid():
                self._right_tree.setCurrentIndex(right_index)

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

            # Sync selection with left tree (scroll is auto-synced)
            left_index = self._left_model.find_index_by_file_id(data.file_id)
            if left_index.isValid():
                self._left_tree.setCurrentIndex(left_index)

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
        """Select and scroll to a change, updating inspector with scroll to modified property."""
        if 0 <= index < len(self._changes):
            change = self._changes[index]

            if change.object_id:
                # Select and scroll in trees
                right_index = self._right_model.find_index_by_file_id(change.object_id)
                if right_index.isValid():
                    self._right_tree.setCurrentIndex(right_index)
                    self._right_tree.scrollTo(right_index)

                left_index = self._left_model.find_index_by_file_id(change.object_id)
                if left_index.isValid():
                    self._left_tree.setCurrentIndex(left_index)

                # Update inspector with the selected object
                if self._right_doc:
                    right_obj = self._right_doc.get_object(change.object_id)
                    if right_obj:
                        other_obj = None
                        if self._left_doc:
                            other_obj = self._left_doc.get_object(change.object_id)
                        self._inspector.set_document(self._right_doc)
                        self._inspector.set_game_object(right_obj, other_obj)

                        # If change has component_type, scroll to first modified property
                        if change.component_type:
                            # Find the component with modifications
                            for comp in right_obj.components:
                                if comp.type_name == change.component_type or (
                                    comp.script_name and comp.script_name == change.component_type
                                ):
                                    QTimer.singleShot(0, lambda fid=comp.file_id: self._inspector.scroll_to_component(fid))
                                    break

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
                # Use QTimer.singleShot to defer scrolling until after layout is complete
                if is_component_ref:
                    QTimer.singleShot(0, lambda fid=file_id: self._inspector.scroll_to_component(fid))
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
                # Use QTimer.singleShot to defer scrolling until after layout is complete
                if is_component_ref:
                    QTimer.singleShot(0, lambda fid=file_id: self._inspector.scroll_to_component(fid))

    def _on_external_reference_clicked(self, guid: str) -> None:
        """Handle external reference click - open file explorer to show the asset."""
        if not guid:
            return

        if not self._guid_resolver:
            QMessageBox.warning(
                self,
                "에셋을 열 수 없음",
                "GUID 리졸버가 초기화되지 않았습니다.\n프로젝트 루트를 찾을 수 없습니다.",
            )
            return

        # Resolve GUID to file path
        asset_path = self._guid_resolver.resolve_path(guid)

        if not asset_path:
            QMessageBox.warning(
                self,
                "에셋을 열 수 없음",
                f"GUID를 경로로 변환할 수 없습니다.\n\n"
                f"GUID: {guid}\n\n"
                "이 에셋이 GUID 캐시에 등록되지 않았을 수 있습니다.\n"
                "(예: 외부 패키지, Unity 빌트인 에셋 등)",
            )
            return

        if not asset_path.exists():
            QMessageBox.warning(
                self,
                "에셋을 열 수 없음",
                f"파일이 존재하지 않습니다.\n\n경로: {asset_path}",
            )
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
