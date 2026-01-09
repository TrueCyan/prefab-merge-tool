"""
3-way merge view widget.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from unityflow import UnityYAMLDocument
from unityflow.semantic_merge import semantic_three_way_merge, apply_resolution

from prefab_diff_tool.core.unity_model import (
    ConflictResolution,
    DiffStatus,
    MergeConflict,
    MergeResult,
    UnityComponent,
    UnityDocument,
    UnityGameObject,
)
from prefab_diff_tool.core.writer import perform_text_merge

logger = logging.getLogger(__name__)
from prefab_diff_tool.models.tree_model import HierarchyTreeModel
from prefab_diff_tool.widgets.inspector_widget import InspectorWidget
from prefab_diff_tool.widgets.loading_widget import (
    FileLoadingWorker,
    LoadingProgressWidget,
)


class MergeView(QWidget):
    """
    3-way merge view for resolving conflicts.

    Layout:
    +-------------+-------------+-------------+
    |    BASE     |    OURS     |   THEIRS    |
    +-------------+-------------+-------------+
    |           RESULT / Conflicts            |
    +-----------------------------------------+
    """

    # Signals
    conflict_resolved = Signal(int)  # Emits remaining conflict count
    loading_started = Signal()
    loading_finished = Signal()

    def __init__(self, parent: Optional[QWidget] = None, unity_root: Optional[Path] = None):
        super().__init__(parent)

        self._base_path: Optional[Path] = None
        self._ours_path: Optional[Path] = None
        self._theirs_path: Optional[Path] = None
        self._unity_root: Optional[Path] = unity_root

        self._base_doc: Optional[UnityDocument] = None
        self._ours_doc: Optional[UnityDocument] = None
        self._theirs_doc: Optional[UnityDocument] = None

        # Raw UnityYAMLDocument for semantic merge
        self._base_raw: Optional[UnityYAMLDocument] = None
        self._ours_raw: Optional[UnityYAMLDocument] = None
        self._theirs_raw: Optional[UnityYAMLDocument] = None
        self._merged_raw: Optional[UnityYAMLDocument] = None
        self._semantic_conflicts: list = []  # unityflow PropertyConflict objects

        self._merge_result: Optional[MergeResult] = None
        self._conflicts: list[MergeConflict] = []
        self._current_conflict_index: int = -1
        self._unsaved_changes: bool = False

        # Models for trees
        self._base_model = HierarchyTreeModel()
        self._ours_model = HierarchyTreeModel()
        self._theirs_model = HierarchyTreeModel()
        self._result_model = HierarchyTreeModel()

        # Loading worker
        self._loading_worker: Optional[FileLoadingWorker] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the UI layout - same structure as DiffView with Inspector."""
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

        # Main vertical splitter (top: hierarchy+inspector, bottom: conflicts)
        main_splitter = QSplitter()
        main_splitter.setOrientation(Qt.Orientation.Vertical)
        content_layout.addWidget(main_splitter)

        # Top section: Horizontal splitter (hierarchy | inspector)
        top_splitter = QSplitter()
        top_splitter.setOrientation(Qt.Orientation.Horizontal)

        # Left side: Hierarchy section with 3 trees
        hierarchy_container = QWidget()
        hierarchy_layout = QVBoxLayout(hierarchy_container)
        hierarchy_layout.setContentsMargins(4, 4, 4, 4)

        hierarchy_label = QLabel("Hierarchy")
        hierarchy_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #888; padding: 2px 0;")
        hierarchy_label.setFixedHeight(20)
        hierarchy_layout.addWidget(hierarchy_label)

        # Three-way tree splitter (BASE | OURS | THEIRS)
        tree_splitter = QSplitter(Qt.Orientation.Horizontal)

        # BASE tree
        base_tree_container = QWidget()
        base_tree_layout = QVBoxLayout(base_tree_container)
        base_tree_layout.setContentsMargins(0, 0, 0, 0)

        self._base_label = QLabel("BASE (공통 조상)")
        self._base_label.setStyleSheet("color: #888; font-size: 11px;")
        base_tree_layout.addWidget(self._base_label)

        self._base_tree = QTreeView()
        self._base_tree.setHeaderHidden(True)
        self._base_tree.setModel(self._base_model)
        self._base_tree.setIndentation(16)
        self._base_tree.clicked.connect(self._on_base_tree_clicked)
        base_tree_layout.addWidget(self._base_tree)

        tree_splitter.addWidget(base_tree_container)

        # OURS tree
        ours_tree_container = QWidget()
        ours_tree_layout = QVBoxLayout(ours_tree_container)
        ours_tree_layout.setContentsMargins(0, 0, 0, 0)

        self._ours_label = QLabel("OURS (내 변경)")
        self._ours_label.setStyleSheet("color: #888; font-size: 11px;")
        ours_tree_layout.addWidget(self._ours_label)

        self._ours_tree = QTreeView()
        self._ours_tree.setHeaderHidden(True)
        self._ours_tree.setModel(self._ours_model)
        self._ours_tree.setIndentation(16)
        self._ours_tree.clicked.connect(self._on_ours_tree_clicked)
        ours_tree_layout.addWidget(self._ours_tree)

        tree_splitter.addWidget(ours_tree_container)

        # THEIRS tree
        theirs_tree_container = QWidget()
        theirs_tree_layout = QVBoxLayout(theirs_tree_container)
        theirs_tree_layout.setContentsMargins(0, 0, 0, 0)

        self._theirs_label = QLabel("THEIRS (상대 변경)")
        self._theirs_label.setStyleSheet("color: #888; font-size: 11px;")
        theirs_tree_layout.addWidget(self._theirs_label)

        self._theirs_tree = QTreeView()
        self._theirs_tree.setHeaderHidden(True)
        self._theirs_tree.setModel(self._theirs_model)
        self._theirs_tree.setIndentation(16)
        self._theirs_tree.clicked.connect(self._on_theirs_tree_clicked)
        theirs_tree_layout.addWidget(self._theirs_tree)

        tree_splitter.addWidget(theirs_tree_container)

        # Synchronize scrolling between all three trees
        self._sync_scroll_enabled = True
        self._base_tree.verticalScrollBar().valueChanged.connect(self._on_base_scroll)
        self._ours_tree.verticalScrollBar().valueChanged.connect(self._on_ours_scroll)
        self._theirs_tree.verticalScrollBar().valueChanged.connect(self._on_theirs_scroll)

        hierarchy_layout.addWidget(tree_splitter)
        top_splitter.addWidget(hierarchy_container)

        # Right side: Inspector panel
        inspector_container = QWidget()
        inspector_layout = QVBoxLayout(inspector_container)
        inspector_layout.setContentsMargins(4, 4, 4, 4)

        inspector_label = QLabel("Inspector")
        inspector_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #888; padding: 2px 0;")
        inspector_label.setFixedHeight(20)
        inspector_layout.addWidget(inspector_label)

        self._inspector = InspectorWidget()
        inspector_layout.addWidget(self._inspector)

        top_splitter.addWidget(inspector_container)

        # Set initial splitter sizes (50% hierarchy, 50% inspector)
        top_splitter.setSizes([500, 500])

        main_splitter.addWidget(top_splitter)

        # Bottom: Conflict resolution section
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(4, 4, 4, 4)

        # Header with buttons
        header = QHBoxLayout()

        result_label = QLabel("충돌 목록")
        result_label.setStyleSheet("font-weight: bold;")
        header.addWidget(result_label)

        header.addStretch()

        # Conflict navigation
        self._conflict_label = QLabel("충돌: 0/0")
        header.addWidget(self._conflict_label)

        prev_btn = QPushButton("< 이전")
        prev_btn.clicked.connect(self._on_prev_conflict)
        header.addWidget(prev_btn)

        next_btn = QPushButton("다음 >")
        next_btn.clicked.connect(self._on_next_conflict)
        header.addWidget(next_btn)

        header.addSpacing(20)

        # Quick resolution buttons
        accept_ours_btn = QPushButton("모두 Ours")
        accept_ours_btn.setStyleSheet("background-color: #2d5a2d;")
        accept_ours_btn.clicked.connect(self._on_accept_all_ours)
        header.addWidget(accept_ours_btn)

        accept_theirs_btn = QPushButton("모두 Theirs")
        accept_theirs_btn.setStyleSheet("background-color: #5a2d2d;")
        accept_theirs_btn.clicked.connect(self._on_accept_all_theirs)
        header.addWidget(accept_theirs_btn)

        bottom_layout.addLayout(header)

        # Conflict table
        self._conflict_table = QTableWidget()
        self._conflict_table.setColumnCount(5)
        self._conflict_table.setHorizontalHeaderLabels([
            "경로", "BASE", "OURS", "THEIRS", "선택"
        ])
        self._conflict_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._conflict_table.setAlternatingRowColors(True)
        self._conflict_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._conflict_table.cellClicked.connect(self._on_conflict_row_clicked)
        bottom_layout.addWidget(self._conflict_table)

        main_splitter.addWidget(bottom_widget)

        # Set initial sizes (70% top, 30% bottom)
        main_splitter.setSizes([700, 300])

        # Add content widget to stack
        self._stack.addWidget(content_widget)

        # Show content by default
        self._stack.setCurrentIndex(1)

    def _on_base_scroll(self, value: int) -> None:
        """Sync other trees when base tree scrolls."""
        if self._sync_scroll_enabled:
            self._sync_scroll_enabled = False
            self._ours_tree.verticalScrollBar().setValue(value)
            self._theirs_tree.verticalScrollBar().setValue(value)
            self._sync_scroll_enabled = True

    def _on_ours_scroll(self, value: int) -> None:
        """Sync other trees when ours tree scrolls."""
        if self._sync_scroll_enabled:
            self._sync_scroll_enabled = False
            self._base_tree.verticalScrollBar().setValue(value)
            self._theirs_tree.verticalScrollBar().setValue(value)
            self._sync_scroll_enabled = True

    def _on_theirs_scroll(self, value: int) -> None:
        """Sync other trees when theirs tree scrolls."""
        if self._sync_scroll_enabled:
            self._sync_scroll_enabled = False
            self._base_tree.verticalScrollBar().setValue(value)
            self._ours_tree.verticalScrollBar().setValue(value)
            self._sync_scroll_enabled = True

    def load_merge(self, base: Path, ours: Path, theirs: Path) -> None:
        """Load files for 3-way merge asynchronously."""
        self._base_path = base
        self._ours_path = ours
        self._theirs_path = theirs

        # Show loading screen
        self._loading_widget.set_title("Loading files...")
        self._loading_widget.update_progress(0, 4, "Preparing to load...")
        self._stack.setCurrentIndex(0)
        self.loading_started.emit()

        # Cancel any existing worker
        if self._loading_worker and self._loading_worker.isRunning():
            self._loading_worker.cancel()
            self._loading_worker.wait()

        # Start async loading with polling-based progress
        self._loading_worker = FileLoadingWorker([base, ours, theirs], unity_root=self._unity_root)
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
            self._base_doc = doc
        elif index == 1:
            self._ours_doc = doc
        elif index == 2:
            self._theirs_doc = doc

    def _on_indexing_started(self) -> None:
        """Handle indexing phase start."""
        self._loading_widget.set_title("Indexing assets...")

    def _on_loading_finished(self) -> None:
        """Handle loading completion."""
        # Stop polling
        self._loading_widget.stop_polling()

        try:
            # Perform 3-way merge
            self._perform_merge()

            # Update tree models
            self._base_model.set_document(self._base_doc)
            self._ours_model.set_document(self._ours_doc)
            self._theirs_model.set_document(self._theirs_doc)

            # Set document for Inspector (use ours as primary)
            self._inspector.set_document(self._ours_doc)

            # Expand trees
            self._base_tree.expandAll()
            self._ours_tree.expandAll()
            self._theirs_tree.expandAll()

            # Update conflict table
            self._update_conflict_table()

            # Switch to content view
            self._stack.setCurrentIndex(1)
            self.loading_finished.emit()

        except Exception as e:
            print(f"Error finalizing merge: {e}")
            import traceback
            traceback.print_exc()
            self._stack.setCurrentIndex(1)
            self.loading_finished.emit()

    def _on_loading_error(self, error: str) -> None:
        """Handle loading error."""
        # Stop polling (don't show 100% on error)
        self._loading_widget.stop_polling(error=True)

        print(f"Error loading merge: {error}")
        self._loading_widget.update_progress(0, 1, f"Error: {error}")
        # Switch to content view after a delay
        QTimer.singleShot(2000, lambda: self._stack.setCurrentIndex(1))
        self.loading_finished.emit()

    def _perform_merge(self) -> None:
        """Perform semantic 3-way merge and identify conflicts."""
        if not self._base_doc or not self._ours_doc or not self._theirs_doc:
            return

        self._conflicts = []
        self._semantic_conflicts = []

        # Try semantic merge first
        try:
            self._base_raw = UnityYAMLDocument.load(self._base_doc.file_path)
            self._ours_raw = UnityYAMLDocument.load(self._ours_doc.file_path)
            self._theirs_raw = UnityYAMLDocument.load(self._theirs_doc.file_path)

            semantic_result = semantic_three_way_merge(
                self._base_raw,
                self._ours_raw,
                self._theirs_raw
            )

            self._merged_raw = semantic_result.merged_document
            self._semantic_conflicts = semantic_result.conflicts

            # Convert semantic conflicts to UI MergeConflict objects
            for conflict in semantic_result.conflicts:
                go_name = conflict.game_object_name or ""
                comp_type = conflict.class_name or ""
                prop_path = conflict.property_path or ""
                file_id = str(conflict.file_id) if conflict.file_id else ""

                self._conflicts.append(MergeConflict(
                    path=f"{go_name}.{comp_type}.{prop_path}",
                    base_value=conflict.base_value,
                    ours_value=conflict.ours_value,
                    theirs_value=conflict.theirs_value,
                    file_id=file_id,
                ))

            # Mark objects/components with conflicts in UI model
            self._mark_conflicts_in_ui_model()

        except Exception as e:
            logger.warning(f"Semantic merge failed, falling back to basic merge: {e}")
            self._perform_basic_merge()
            return

        # Create merge result
        self._merge_result = MergeResult(
            base=self._base_doc,
            ours=self._ours_doc,
            theirs=self._theirs_doc,
            conflicts=self._conflicts,
        )

        self._update_conflict_label()

    def _mark_conflicts_in_ui_model(self) -> None:
        """Mark conflicting objects/components in UI model based on semantic conflicts."""
        if not self._ours_doc or not self._theirs_doc:
            return

        ours_components = self._ours_doc.all_components
        theirs_components = self._theirs_doc.all_components
        ours_objects = {go.file_id: go for go in self._ours_doc.iter_all_objects()}
        theirs_objects = {go.file_id: go for go in self._theirs_doc.iter_all_objects()}

        for conflict in self._conflicts:
            file_id = conflict.file_id if hasattr(conflict, 'file_id') else ""
            if not file_id:
                continue

            # Mark components
            if file_id in ours_components:
                ours_components[file_id].diff_status = DiffStatus.MODIFIED
            if file_id in theirs_components:
                theirs_components[file_id].diff_status = DiffStatus.MODIFIED

            # Find and mark owner GameObjects
            for go in ours_objects.values():
                for comp in go.components:
                    if comp.file_id == file_id:
                        go.diff_status = DiffStatus.MODIFIED
                        break

            for go in theirs_objects.values():
                for comp in go.components:
                    if comp.file_id == file_id:
                        go.diff_status = DiffStatus.MODIFIED
                        break

    def _perform_basic_merge(self) -> None:
        """Fallback to basic merge when semantic merge is not available."""
        self._conflicts = []

        # Build lookup maps
        base_objects = {go.file_id: go for go in self._base_doc.iter_all_objects()}
        ours_objects = {go.file_id: go for go in self._ours_doc.iter_all_objects()}
        theirs_objects = {go.file_id: go for go in self._theirs_doc.iter_all_objects()}

        base_components = self._base_doc.all_components
        ours_components = self._ours_doc.all_components
        theirs_components = self._theirs_doc.all_components

        # Find all file_ids
        all_object_ids = set(base_objects.keys()) | set(ours_objects.keys()) | set(theirs_objects.keys())

        # Check object-level conflicts
        for file_id in all_object_ids:
            in_base = file_id in base_objects
            in_ours = file_id in ours_objects
            in_theirs = file_id in theirs_objects

            if in_base and in_ours and in_theirs:
                self._check_object_conflicts(
                    base_objects[file_id],
                    ours_objects[file_id],
                    theirs_objects[file_id],
                )
            elif in_base and in_ours and not in_theirs:
                ours_objects[file_id].diff_status = DiffStatus.MODIFIED
            elif in_base and not in_ours and in_theirs:
                theirs_objects[file_id].diff_status = DiffStatus.MODIFIED
            elif not in_base and in_ours and in_theirs:
                self._conflicts.append(MergeConflict(
                    path=f"{ours_objects[file_id].get_path()} (both added)",
                    ours_value="added",
                    theirs_value="added",
                ))
            elif not in_base and in_ours:
                ours_objects[file_id].diff_status = DiffStatus.ADDED
            elif not in_base and in_theirs:
                theirs_objects[file_id].diff_status = DiffStatus.ADDED

        # Create merge result
        self._merge_result = MergeResult(
            base=self._base_doc,
            ours=self._ours_doc,
            theirs=self._theirs_doc,
            conflicts=self._conflicts,
        )

        self._update_conflict_label()

    def _check_object_conflicts(
        self,
        base_go: UnityGameObject,
        ours_go: UnityGameObject,
        theirs_go: UnityGameObject,
    ) -> None:
        """Check for property-level conflicts in a GameObject."""
        # Compare components
        base_comps = {c.file_id: c for c in base_go.components}
        ours_comps = {c.file_id: c for c in ours_go.components}
        theirs_comps = {c.file_id: c for c in theirs_go.components}

        all_comp_ids = set(base_comps.keys()) | set(ours_comps.keys()) | set(theirs_comps.keys())

        for comp_id in all_comp_ids:
            base_comp = base_comps.get(comp_id)
            ours_comp = ours_comps.get(comp_id)
            theirs_comp = theirs_comps.get(comp_id)

            if base_comp and ours_comp and theirs_comp:
                self._check_component_conflicts(
                    base_go.get_path(),
                    base_comp,
                    ours_comp,
                    theirs_comp,
                )

    def _check_component_conflicts(
        self,
        go_path: str,
        base_comp: UnityComponent,
        ours_comp: UnityComponent,
        theirs_comp: UnityComponent,
    ) -> None:
        """Check for property-level conflicts in a component."""
        base_props = {p.path: p for p in base_comp.properties}
        ours_props = {p.path: p for p in ours_comp.properties}
        theirs_props = {p.path: p for p in theirs_comp.properties}

        all_prop_paths = set(base_props.keys()) | set(ours_props.keys()) | set(theirs_props.keys())

        for prop_path in all_prop_paths:
            base_prop = base_props.get(prop_path)
            ours_prop = ours_props.get(prop_path)
            theirs_prop = theirs_props.get(prop_path)

            base_val = base_prop.value if base_prop else None
            ours_val = ours_prop.value if ours_prop else None
            theirs_val = theirs_prop.value if theirs_prop else None

            # Check for conflict: both changed from base to different values
            ours_changed = ours_val != base_val
            theirs_changed = theirs_val != base_val

            if ours_changed and theirs_changed and ours_val != theirs_val:
                # Conflict!
                comp_name = ours_comp.script_name or ours_comp.type_name
                self._conflicts.append(MergeConflict(
                    path=f"{go_path}.{comp_name}.{prop_path}",
                    base_value=base_val,
                    ours_value=ours_val,
                    theirs_value=theirs_val,
                ))

                # Mark as modified
                if ours_prop:
                    ours_prop.diff_status = DiffStatus.MODIFIED
                if theirs_prop:
                    theirs_prop.diff_status = DiffStatus.MODIFIED
                ours_comp.diff_status = DiffStatus.MODIFIED
                theirs_comp.diff_status = DiffStatus.MODIFIED

    def _update_conflict_table(self) -> None:
        """Update the conflict table with current conflicts."""
        self._conflict_table.setRowCount(len(self._conflicts))

        for row, conflict in enumerate(self._conflicts):
            # Path
            path_item = QTableWidgetItem(conflict.path)
            self._conflict_table.setItem(row, 0, path_item)

            # Base value
            base_item = QTableWidgetItem(self._format_value(conflict.base_value))
            self._conflict_table.setItem(row, 1, base_item)

            # Ours value
            ours_item = QTableWidgetItem(self._format_value(conflict.ours_value))
            ours_item.setBackground(QBrush(QColor(45, 90, 45)))
            self._conflict_table.setItem(row, 2, ours_item)

            # Theirs value
            theirs_item = QTableWidgetItem(self._format_value(conflict.theirs_value))
            theirs_item.setBackground(QBrush(QColor(90, 45, 45)))
            self._conflict_table.setItem(row, 3, theirs_item)

            # Resolution combo
            combo = QComboBox()
            combo.addItems(["미해결", "Ours", "Theirs", "Base"])
            combo.setCurrentIndex(self._resolution_to_index(conflict.resolution))
            combo.currentIndexChanged.connect(
                lambda idx, r=row: self._on_resolution_changed(r, idx)
            )
            self._conflict_table.setCellWidget(row, 4, combo)

    def _format_value(self, value) -> str:
        """Format a value for display."""
        if value is None:
            return "<none>"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, dict):
            # Check if it's a Unity object reference
            if "fileID" in value:
                file_id = value.get("fileID", 0)
                guid = value.get("guid", "")
                if file_id == 0:
                    return "None"
                if guid:
                    return f"External ({guid[:8]}...)"
                return f"(ID: {file_id})"
            # Other dict
            import json
            try:
                return json.dumps(value, ensure_ascii=False)[:50]
            except Exception:
                return str(value)[:50]
        if isinstance(value, list):
            if len(value) == 0:
                return "[]"
            import json
            try:
                return json.dumps(value, ensure_ascii=False)[:50]
            except Exception:
                return str(value)[:50]
        return str(value)[:50]

    def _resolution_to_index(self, resolution: ConflictResolution) -> int:
        """Convert resolution enum to combo index."""
        return {
            ConflictResolution.UNRESOLVED: 0,
            ConflictResolution.USE_OURS: 1,
            ConflictResolution.USE_THEIRS: 2,
            ConflictResolution.USE_MANUAL: 3,
        }.get(resolution, 0)

    def _index_to_resolution(self, index: int) -> ConflictResolution:
        """Convert combo index to resolution enum."""
        return [
            ConflictResolution.UNRESOLVED,
            ConflictResolution.USE_OURS,
            ConflictResolution.USE_THEIRS,
            ConflictResolution.USE_MANUAL,
        ][index]

    def _on_resolution_changed(self, row: int, index: int) -> None:
        """Handle resolution combo change."""
        if 0 <= row < len(self._conflicts):
            self._conflicts[row].resolution = self._index_to_resolution(index)
            if index == 1:  # Ours
                self._conflicts[row].resolved_value = self._conflicts[row].ours_value
            elif index == 2:  # Theirs
                self._conflicts[row].resolved_value = self._conflicts[row].theirs_value
            elif index == 3:  # Base
                self._conflicts[row].resolved_value = self._conflicts[row].base_value

            self._unsaved_changes = True
            self._update_conflict_label()
            self.conflict_resolved.emit(self.get_unresolved_count())

    def _update_conflict_label(self) -> None:
        """Update the conflict count label."""
        total = len(self._conflicts)
        resolved = self.get_resolved_count()
        self._conflict_label.setText(f"충돌: {resolved}/{total} 해결됨")

    def _on_base_tree_clicked(self, index) -> None:
        """Handle base tree selection."""
        self._sync_tree_selection(index, "base")

    def _on_ours_tree_clicked(self, index) -> None:
        """Handle ours tree selection."""
        self._sync_tree_selection(index, "ours")

    def _on_theirs_tree_clicked(self, index) -> None:
        """Handle theirs tree selection."""
        self._sync_tree_selection(index, "theirs")

    def _sync_tree_selection(self, index, source: str) -> None:
        """Sync selection across all three trees and update Inspector."""
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data or not hasattr(data, "file_id"):
            return

        file_id = data.file_id

        # Select in other trees
        if source != "base":
            idx = self._base_model.find_index_by_file_id(file_id)
            if idx.isValid():
                self._base_tree.setCurrentIndex(idx)
                self._base_tree.scrollTo(idx)

        if source != "ours":
            idx = self._ours_model.find_index_by_file_id(file_id)
            if idx.isValid():
                self._ours_tree.setCurrentIndex(idx)
                self._ours_tree.scrollTo(idx)

        if source != "theirs":
            idx = self._theirs_model.find_index_by_file_id(file_id)
            if idx.isValid():
                self._theirs_tree.setCurrentIndex(idx)
                self._theirs_tree.scrollTo(idx)

        # Update Inspector with the selected object
        # Show OURS version as main, with BASE for comparison
        if isinstance(data, UnityGameObject):
            ours_obj = self._ours_doc.get_object(file_id) if self._ours_doc else None
            base_obj = self._base_doc.get_object(file_id) if self._base_doc else None

            if ours_obj:
                self._inspector.set_document(self._ours_doc)
                self._inspector.set_game_object(ours_obj, base_obj)
            elif base_obj:
                # Object only exists in base (deleted in ours)
                self._inspector.set_document(self._base_doc)
                self._inspector.set_game_object(base_obj, None)
            else:
                # Check theirs
                theirs_obj = self._theirs_doc.get_object(file_id) if self._theirs_doc else None
                if theirs_obj:
                    self._inspector.set_document(self._theirs_doc)
                    self._inspector.set_game_object(theirs_obj, None)

    def _on_conflict_row_clicked(self, row: int, col: int) -> None:
        """Handle conflict table row click."""
        self._current_conflict_index = row

    def save_result(self, output: Path) -> bool:
        """
        Save the merge result.

        Applies resolved conflict values and writes the merged document.

        Args:
            output: Path to write the merged file

        Returns:
            True if save was successful
        """
        if not self._base_path or not self._ours_path or not self._theirs_path:
            return False

        try:
            # Try semantic save first if we have semantic merge result
            if self._merged_raw and self._semantic_conflicts:
                return self._save_semantic_result(output)

            # Fallback to text-based merge
            success, conflict_count = perform_text_merge(
                base_path=self._base_path,
                ours_path=self._ours_path,
                theirs_path=self._theirs_path,
                output_path=output,
                conflicts=self._conflicts,
                normalize=True,
            )

            if success or self._all_conflicts_resolved():
                self._unsaved_changes = False
                return True
            else:
                self._unsaved_changes = False
                return True

        except Exception as e:
            logger.error(f"Error saving merge result: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _save_semantic_result(self, output: Path) -> bool:
        """Save using semantic merge with applied resolutions."""
        if not self._merged_raw:
            return False

        try:
            # Apply resolutions to semantic conflicts
            for i, ui_conflict in enumerate(self._conflicts):
                if not ui_conflict.is_resolved:
                    continue

                # Find matching semantic conflict
                if i < len(self._semantic_conflicts):
                    semantic_conflict = self._semantic_conflicts[i]

                    # Determine resolution value
                    if ui_conflict.resolution == ConflictResolution.USE_OURS:
                        resolution = "ours"
                    elif ui_conflict.resolution == ConflictResolution.USE_THEIRS:
                        resolution = "theirs"
                    elif ui_conflict.resolution == ConflictResolution.USE_MANUAL:
                        # Use base for manual/custom resolution
                        resolution = "base"
                    else:
                        continue

                    # Apply resolution to merged document
                    apply_resolution(self._merged_raw, semantic_conflict, resolution)

            # Save the merged document
            self._merged_raw.save(str(output))
            self._unsaved_changes = False
            return True

        except Exception as e:
            logger.error(f"Error saving semantic merge result: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to text-based merge
            return self._save_text_result(output)

    def _save_text_result(self, output: Path) -> bool:
        """Fallback to text-based merge save."""
        success, _ = perform_text_merge(
            base_path=self._base_path,
            ours_path=self._ours_path,
            theirs_path=self._theirs_path,
            output_path=output,
            conflicts=self._conflicts,
            normalize=True,
        )
        self._unsaved_changes = False
        return True

    def _all_conflicts_resolved(self) -> bool:
        """Check if all conflicts have been resolved."""
        return all(c.is_resolved for c in self._conflicts)

    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes."""
        return self._unsaved_changes

    def has_unresolved_conflicts(self) -> bool:
        """Check if there are unresolved conflicts."""
        return any(not c.is_resolved for c in self._conflicts)

    def get_conflict_count(self) -> int:
        """Get total number of conflicts."""
        return len(self._conflicts)

    def get_resolved_count(self) -> int:
        """Get number of resolved conflicts."""
        return sum(1 for c in self._conflicts if c.is_resolved)

    def get_unresolved_count(self) -> int:
        """Get number of unresolved conflicts."""
        return sum(1 for c in self._conflicts if not c.is_resolved)

    def _on_prev_conflict(self) -> None:
        """Navigate to previous conflict."""
        if not self._conflicts:
            return
        self._current_conflict_index = (self._current_conflict_index - 1) % len(self._conflicts)
        self._conflict_table.selectRow(self._current_conflict_index)

    def _on_next_conflict(self) -> None:
        """Navigate to next conflict."""
        if not self._conflicts:
            return
        self._current_conflict_index = (self._current_conflict_index + 1) % len(self._conflicts)
        self._conflict_table.selectRow(self._current_conflict_index)

    def _on_accept_all_ours(self) -> None:
        """Accept all 'ours' for conflicts."""
        for i, conflict in enumerate(self._conflicts):
            conflict.resolution = ConflictResolution.USE_OURS
            conflict.resolved_value = conflict.ours_value
            # Update combo
            combo = self._conflict_table.cellWidget(i, 4)
            if combo:
                combo.setCurrentIndex(1)

        self._unsaved_changes = True
        self._update_conflict_label()
        self.conflict_resolved.emit(0)

    def _on_accept_all_theirs(self) -> None:
        """Accept all 'theirs' for conflicts."""
        for i, conflict in enumerate(self._conflicts):
            conflict.resolution = ConflictResolution.USE_THEIRS
            conflict.resolved_value = conflict.theirs_value
            # Update combo
            combo = self._conflict_table.cellWidget(i, 4)
            if combo:
                combo.setCurrentIndex(2)

        self._unsaved_changes = True
        self._update_conflict_label()
        self.conflict_resolved.emit(0)

    def expand_all(self) -> None:
        """Expand all tree items."""
        self._base_tree.expandAll()
        self._ours_tree.expandAll()
        self._theirs_tree.expandAll()

    def collapse_all(self) -> None:
        """Collapse all tree items."""
        self._base_tree.collapseAll()
        self._ours_tree.collapseAll()
        self._theirs_tree.collapseAll()

    def accept_all_ours(self) -> None:
        """Public method to accept all ours - called from toolbar."""
        self._on_accept_all_ours()

    def accept_all_theirs(self) -> None:
        """Public method to accept all theirs - called from toolbar."""
        self._on_accept_all_theirs()

    def goto_next_unresolved_conflict(self) -> None:
        """Navigate to next unresolved conflict."""
        if not self._conflicts:
            return

        # Find next unresolved conflict starting from current
        start = (self._current_conflict_index + 1) % len(self._conflicts)
        for i in range(len(self._conflicts)):
            idx = (start + i) % len(self._conflicts)
            if not self._conflicts[idx].is_resolved:
                self._current_conflict_index = idx
                self._conflict_table.selectRow(idx)
                return

        # If all resolved, just go to next
        self._on_next_conflict()

    def goto_next_change(self) -> None:
        """Navigate to next change (alias for goto_next_conflict for toolbar consistency)."""
        self._on_next_conflict()

    def goto_prev_change(self) -> None:
        """Navigate to previous change (alias for goto_prev_conflict for toolbar consistency)."""
        self._on_prev_conflict()
