"""
Qt tree model for displaying Unity hierarchy.
"""

from enum import IntEnum
from typing import Any, Optional, Union

from PySide6.QtCore import (
    Qt,
    QModelIndex,
    QAbstractItemModel,
    QPersistentModelIndex,
    QSize,
)
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QPixmap, QPainter

from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
    DiffStatus,
)
from prefab_diff_tool.utils.colors import DiffColors, DIFF_SYMBOLS


# Unicode icons for different object types (emoji-based for cross-platform compatibility)
HIERARCHY_ICONS = {
    # GameObject types
    "gameobject": "📦",
    "gameobject_inactive": "📦",  # Could use dimmed version
    "prefab": "💠",
    "prefab_instance": "🔷",
    # Common component types
    "Transform": "📐",
    "RectTransform": "📐",
    "Camera": "📷",
    "Light": "💡",
    "AudioSource": "🔊",
    "MeshRenderer": "🎨",
    "SkinnedMeshRenderer": "🎭",
    "Animator": "🎬",
    "Rigidbody": "⚙️",
    "Collider": "📦",
    "Canvas": "🖼️",
    "MonoBehaviour": "📜",
    "default_component": "🔧",
}


class NodeType(IntEnum):
    """Type of node in the hierarchy tree."""
    ROOT = 0
    GAME_OBJECT = 1
    COMPONENT = 2


class TreeNode:
    """Wrapper for tree items with parent tracking."""

    def __init__(
        self,
        data: Union[UnityGameObject, UnityComponent, None],
        node_type: NodeType,
        parent: Optional["TreeNode"] = None,
    ):
        self.data = data
        self.node_type = node_type
        self.parent = parent
        self.children: list["TreeNode"] = []
        self._row: int = 0

    @property
    def row(self) -> int:
        """Get this node's row in its parent's children list."""
        return self._row

    @row.setter
    def row(self, value: int) -> None:
        self._row = value

    @property
    def name(self) -> str:
        """Get display name for this node."""
        if self.data is None:
            return "Root"
        if isinstance(self.data, UnityGameObject):
            return self.data.name
        if isinstance(self.data, UnityComponent):
            # Use script name for MonoBehaviour, otherwise type name
            return self.data.script_name or self.data.type_name
        return "Unknown"

    @property
    def icon(self) -> str:
        """Get icon for this node."""
        if self.data is None:
            return ""
        if isinstance(self.data, UnityGameObject):
            # Show special icon for nested prefab instances
            if self.data.is_prefab_instance:
                return HIERARCHY_ICONS.get("prefab_instance", "🔷")
            if not self.data.is_active:
                return HIERARCHY_ICONS.get("gameobject_inactive", "📦")
            return HIERARCHY_ICONS.get("gameobject", "📦")
        if isinstance(self.data, UnityComponent):
            type_name = self.data.type_name
            # Check for specific component types
            if type_name in HIERARCHY_ICONS:
                return HIERARCHY_ICONS[type_name]
            # Check for collider types
            if "Collider" in type_name:
                return HIERARCHY_ICONS.get("Collider", "📦")
            return HIERARCHY_ICONS.get("default_component", "🔧")
        return ""

    @property
    def display_text(self) -> str:
        """Get display text with diff status indicator."""
        status = self.diff_status
        prefix = DIFF_SYMBOLS.get(status.value, "")
        if prefix:
            return f"{prefix} {self.name}"
        return self.name

    @property
    def file_id(self) -> str:
        """Get fileID of this node."""
        if self.data is None:
            return ""
        return self.data.file_id

    @property
    def diff_status(self) -> DiffStatus:
        """Get diff status of this node."""
        if self.data is None:
            return DiffStatus.UNCHANGED
        return self.data.diff_status


class HierarchyTreeModel(QAbstractItemModel):
    """
    Qt model for displaying Unity hierarchy in a tree view.

    Structure:
    - Root (invisible)
      - GameObject (e.g., "Player")
        - Component (e.g., "Transform")
        - Component (e.g., "PlayerController")
        - GameObject (child, e.g., "Body")
          - Component (e.g., "Transform")
          - ...
    """

    def __init__(self, parent: Optional[Any] = None):
        super().__init__(parent)
        self._document: Optional[UnityDocument] = None
        self._root = TreeNode(None, NodeType.ROOT)
        self._show_components = False  # Unity Hierarchy style: GameObjects only
        # Cache for O(1) file_id -> QModelIndex lookup
        self._index_cache: dict[str, QModelIndex] = {}

    def set_document(self, document: Optional[UnityDocument]) -> None:
        """Set the Unity document to display."""
        self.beginResetModel()
        self._document = document
        self._root = TreeNode(None, NodeType.ROOT)
        self._index_cache.clear()

        if document:
            self._build_tree(document.root_objects, self._root, QModelIndex())

        self.endResetModel()

    def set_show_components(self, show: bool) -> None:
        """Toggle showing components in the tree."""
        if self._show_components != show:
            self.beginResetModel()
            self._show_components = show
            self._index_cache.clear()
            if self._document:
                self._root = TreeNode(None, NodeType.ROOT)
                self._build_tree(self._document.root_objects, self._root, QModelIndex())
            self.endResetModel()

    def _build_tree(
        self,
        game_objects: list[UnityGameObject],
        parent_node: TreeNode,
        parent_index: QModelIndex,
    ) -> None:
        """Recursively build tree nodes from GameObjects and cache indices."""
        for idx, go in enumerate(game_objects):
            go_node = TreeNode(go, NodeType.GAME_OBJECT, parent_node)
            go_node.row = len(parent_node.children)
            parent_node.children.append(go_node)

            # Create and cache the index for this node
            node_index = self.createIndex(go_node.row, 0, go_node)
            if go.file_id:
                self._index_cache[go.file_id] = node_index

            # Add components as children (if enabled)
            if self._show_components:
                for comp in go.components:
                    comp_node = TreeNode(comp, NodeType.COMPONENT, go_node)
                    comp_node.row = len(go_node.children)
                    go_node.children.append(comp_node)
                    # Cache component index
                    comp_index = self.createIndex(comp_node.row, 0, comp_node)
                    if comp.file_id:
                        self._index_cache[comp.file_id] = comp_index

            # Add child GameObjects
            self._build_tree(go.children, go_node, node_index)

    def _get_node(self, index: QModelIndex) -> TreeNode:
        """Get TreeNode from index."""
        if index.isValid():
            node = index.internalPointer()
            if node:
                return node
        return self._root

    # === QAbstractItemModel interface ===

    def index(
        self,
        row: int,
        column: int,
        parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex(),
    ) -> QModelIndex:
        """Create index for the given row, column, parent."""
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_node = self._get_node(parent)

        if row < len(parent_node.children):
            child_node = parent_node.children[row]
            return self.createIndex(row, column, child_node)

        return QModelIndex()

    def parent(
        self, index: Union[QModelIndex, QPersistentModelIndex]
    ) -> QModelIndex:
        """Get parent index of the given index."""
        if not index.isValid():
            return QModelIndex()

        child_node = self._get_node(index)
        parent_node = child_node.parent

        if parent_node is None or parent_node == self._root:
            return QModelIndex()

        return self.createIndex(parent_node.row, 0, parent_node)

    def rowCount(
        self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()
    ) -> int:
        """Get number of children for the parent index."""
        parent_node = self._get_node(parent)
        return len(parent_node.children)

    def columnCount(
        self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()
    ) -> int:
        """Always return 1 column for tree view."""
        return 1

    def data(
        self,
        index: Union[QModelIndex, QPersistentModelIndex],
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Get data for the given index and role."""
        if not index.isValid():
            return None

        node = self._get_node(index)

        if role == Qt.ItemDataRole.DisplayRole:
            # Include icon in display text for visual clarity
            icon = node.icon
            name = node.display_text
            if icon:
                return f"{icon} {name}"
            return name

        elif role == Qt.ItemDataRole.ToolTipRole:
            return self._get_tooltip(node)

        elif role == Qt.ItemDataRole.ForegroundRole:
            return self._get_foreground(node)

        elif role == Qt.ItemDataRole.BackgroundRole:
            return self._get_background(node)

        elif role == Qt.ItemDataRole.FontRole:
            return self._get_font(node)

        elif role == Qt.ItemDataRole.SizeHintRole:
            # Provide consistent row height
            return QSize(-1, 24)

        elif role == Qt.ItemDataRole.UserRole:
            # Return the actual data object
            return node.data

        elif role == Qt.ItemDataRole.UserRole + 1:
            # Return node type
            return node.node_type

        elif role == Qt.ItemDataRole.UserRole + 2:
            # Return diff status
            return node.diff_status

        return None

    def flags(
        self, index: Union[QModelIndex, QPersistentModelIndex]
    ) -> Qt.ItemFlag:
        """Get item flags."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Get header data."""
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and section == 0
        ):
            return "Hierarchy"
        return None

    # === Helper methods for display ===

    def _get_tooltip(self, node: TreeNode) -> str:
        """Generate tooltip for a node."""
        if node.data is None:
            return ""

        lines = [f"FileID: {node.file_id}"]

        if isinstance(node.data, UnityGameObject):
            go = node.data
            lines.append(f"Path: {go.get_path()}")
            lines.append(f"Layer: {go.layer}")
            lines.append(f"Tag: {go.tag}")
            lines.append(f"Active: {go.is_active}")
            lines.append(f"Components: {len(go.components)}")
            lines.append(f"Children: {len(go.children)}")

        elif isinstance(node.data, UnityComponent):
            comp = node.data
            lines.append(f"Type: {comp.type_name}")
            if comp.script_name:
                lines.append(f"Script: {comp.script_name}")
            if comp.script_guid:
                lines.append(f"GUID: {comp.script_guid}")
            lines.append(f"Properties: {len(comp.properties)}")

        return "\n".join(lines)

    def _get_foreground(self, node: TreeNode) -> Optional[QBrush]:
        """Get foreground color based on diff status."""
        status = node.diff_status

        if status == DiffStatus.ADDED:
            return QBrush(QColor(DiffColors.ADDED_FG))
        elif status == DiffStatus.REMOVED:
            return QBrush(QColor(DiffColors.REMOVED_FG))
        elif status == DiffStatus.MODIFIED:
            return QBrush(QColor(DiffColors.MODIFIED_FG))

        # Default color for components (slightly dimmer)
        if node.node_type == NodeType.COMPONENT:
            return QBrush(QColor(180, 180, 180))

        return None

    def _get_background(self, node: TreeNode) -> Optional[QBrush]:
        """Get background color based on diff status."""
        status = node.diff_status

        if status == DiffStatus.ADDED:
            return QBrush(QColor(DiffColors.ADDED_BG_DARK))
        elif status == DiffStatus.REMOVED:
            return QBrush(QColor(DiffColors.REMOVED_BG_DARK))
        elif status == DiffStatus.MODIFIED:
            return QBrush(QColor(DiffColors.MODIFIED_BG_DARK))

        return None

    def _get_font(self, node: TreeNode) -> Optional[QFont]:
        """Get font based on node type and status."""
        if node.diff_status != DiffStatus.UNCHANGED:
            font = QFont()
            font.setBold(True)
            return font

        if node.node_type == NodeType.COMPONENT:
            font = QFont()
            font.setItalic(True)
            return font

        return None

    # === Navigation helpers ===

    def find_index_by_file_id(self, file_id: str) -> QModelIndex:
        """Find index of a node by its fileID. O(1) lookup using cache."""
        # Use cache for O(1) lookup
        cached_index = self._index_cache.get(file_id)
        if cached_index is not None and cached_index.isValid():
            return cached_index
        return QModelIndex()

    def get_changed_indices(self) -> list[QModelIndex]:
        """Get list of all indices with changes (non-UNCHANGED status)."""
        indices = []
        self._collect_changed(self._root, QModelIndex(), indices)
        return indices

    def _collect_changed(
        self,
        parent_node: TreeNode,
        parent_index: QModelIndex,
        indices: list[QModelIndex],
    ) -> None:
        """Recursively collect changed node indices."""
        for i, child in enumerate(parent_node.children):
            if child.diff_status != DiffStatus.UNCHANGED:
                indices.append(self.index(i, 0, parent_index))

            child_index = self.index(i, 0, parent_index)
            self._collect_changed(child, child_index, indices)
