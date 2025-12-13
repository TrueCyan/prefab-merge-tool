"""
3-way merge view widget.
"""

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
    QPushButton,
    QFrame,
    QAbstractItemView,
    QComboBox,
)
from PySide6.QtGui import QColor, QBrush

from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
    DiffStatus,
    MergeConflict,
    MergeResult,
    ConflictResolution,
)
from prefab_diff_tool.core.loader import load_unity_file
from prefab_diff_tool.core.writer import MergeResultWriter, perform_text_merge
from prefab_diff_tool.models.tree_model import HierarchyTreeModel
from prefab_diff_tool.utils.colors import DiffColors


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

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._base_path: Optional[Path] = None
        self._ours_path: Optional[Path] = None
        self._theirs_path: Optional[Path] = None

        self._base_doc: Optional[UnityDocument] = None
        self._ours_doc: Optional[UnityDocument] = None
        self._theirs_doc: Optional[UnityDocument] = None

        self._merge_result: Optional[MergeResult] = None
        self._conflicts: list[MergeConflict] = []
        self._current_conflict_index: int = -1
        self._unsaved_changes: bool = False

        # Models for trees
        self._base_model = HierarchyTreeModel()
        self._ours_model = HierarchyTreeModel()
        self._theirs_model = HierarchyTreeModel()
        self._result_model = HierarchyTreeModel()

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main vertical splitter
        main_splitter = QSplitter()
        main_splitter.setOrientation(Qt.Orientation.Vertical)
        layout.addWidget(main_splitter)

        # Top: 3-way comparison
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(4, 4, 4, 4)
        top_layout.setSpacing(4)

        # BASE panel
        self._base_panel, self._base_tree = self._create_panel("BASE (공통 조상)")
        self._base_tree.setModel(self._base_model)
        self._base_tree.clicked.connect(self._on_base_tree_clicked)
        top_layout.addWidget(self._base_panel)

        # OURS panel
        self._ours_panel, self._ours_tree = self._create_panel("OURS (내 변경)")
        self._ours_tree.setModel(self._ours_model)
        self._ours_tree.clicked.connect(self._on_ours_tree_clicked)
        top_layout.addWidget(self._ours_panel)

        # THEIRS panel
        self._theirs_panel, self._theirs_tree = self._create_panel("THEIRS (상대 변경)")
        self._theirs_tree.setModel(self._theirs_model)
        self._theirs_tree.clicked.connect(self._on_theirs_tree_clicked)
        top_layout.addWidget(self._theirs_panel)

        main_splitter.addWidget(top_widget)

        # Bottom: Result and conflict resolution
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

        # Set initial sizes (60% top, 40% bottom)
        main_splitter.setSizes([600, 400])

    def _create_panel(self, title: str) -> tuple[QFrame, QTreeView]:
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

        return frame, tree

    def load_merge(self, base: Path, ours: Path, theirs: Path) -> None:
        """Load files for 3-way merge."""
        self._base_path = base
        self._ours_path = ours
        self._theirs_path = theirs

        try:
            # Load all three files
            self._base_doc = load_unity_file(base)
            self._ours_doc = load_unity_file(ours)
            self._theirs_doc = load_unity_file(theirs)

            # Perform 3-way merge
            self._perform_merge()

            # Update tree models
            self._base_model.set_document(self._base_doc)
            self._ours_model.set_document(self._ours_doc)
            self._theirs_model.set_document(self._theirs_doc)

            # Expand trees
            self._base_tree.expandAll()
            self._ours_tree.expandAll()
            self._theirs_tree.expandAll()

            # Update conflict table
            self._update_conflict_table()

        except Exception as e:
            print(f"Error loading merge: {e}")
            import traceback
            traceback.print_exc()

    def _perform_merge(self) -> None:
        """Perform 3-way merge and identify conflicts."""
        if not self._base_doc or not self._ours_doc or not self._theirs_doc:
            return

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
        all_comp_ids = set(base_components.keys()) | set(ours_components.keys()) | set(theirs_components.keys())

        # Check object-level conflicts
        for file_id in all_object_ids:
            in_base = file_id in base_objects
            in_ours = file_id in ours_objects
            in_theirs = file_id in theirs_objects

            # Conflict: both modified or one deleted while other modified
            if in_base and in_ours and in_theirs:
                # All three have it - check for property conflicts
                self._check_object_conflicts(
                    base_objects[file_id],
                    ours_objects[file_id],
                    theirs_objects[file_id],
                )
            elif in_base and not in_ours and not in_theirs:
                # Both deleted - no conflict (auto-merge: delete)
                pass
            elif in_base and in_ours and not in_theirs:
                # Theirs deleted - check if ours modified
                ours_objects[file_id].diff_status = DiffStatus.MODIFIED
            elif in_base and not in_ours and in_theirs:
                # Ours deleted - check if theirs modified
                theirs_objects[file_id].diff_status = DiffStatus.MODIFIED
            elif not in_base and in_ours and in_theirs:
                # Both added with same fileID - conflict
                self._conflicts.append(MergeConflict(
                    path=f"{ours_objects[file_id].get_path()} (both added)",
                    ours_value="added",
                    theirs_value="added",
                ))
            elif not in_base and in_ours:
                # Only ours added
                ours_objects[file_id].diff_status = DiffStatus.ADDED
            elif not in_base and in_theirs:
                # Only theirs added
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
        if isinstance(value, (list, dict)):
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
        """Sync selection across all three trees."""
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
            # Use text-based merge with conflict resolutions
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
                # Even with unresolved conflicts, write the file
                # (conflicts will be marked with conflict markers)
                self._unsaved_changes = False
                return True

        except Exception as e:
            print(f"Error saving merge result: {e}")
            import traceback
            traceback.print_exc()
            return False

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
