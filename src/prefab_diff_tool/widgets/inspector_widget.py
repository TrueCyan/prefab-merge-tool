"""
Unity-style Inspector widget for displaying component properties.

Displays components and their properties in a collapsible, hierarchical view
similar to Unity's Inspector window.
"""

from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QFrame,
    QLabel,
    QHBoxLayout,
    QToolButton,
    QGridLayout,
    QSizePolicy,
)
from PySide6.QtGui import QColor, QPalette, QFont

from prefab_diff_tool.core.unity_model import (
    UnityGameObject,
    UnityComponent,
    UnityProperty,
    DiffStatus,
)
from prefab_diff_tool.utils.colors import DiffColors
from prefab_diff_tool.utils.naming import (
    nicify_variable_name,
    get_component_display_name,
)


class PropertyRowWidget(QWidget):
    """A single property row with name and value(s)."""

    def __init__(
        self,
        prop: UnityProperty,
        other_value: Any = None,
        show_diff: bool = True,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._prop = prop
        self._other_value = other_value
        self._show_diff = show_diff
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 2, 4, 2)  # Indent for nesting
        layout.setSpacing(8)

        # Property name (nicified)
        name_label = QLabel(nicify_variable_name(self._prop.name))
        name_label.setMinimumWidth(150)
        name_label.setStyleSheet("color: #b0b0b0;")
        layout.addWidget(name_label)

        # Values container
        values_layout = QHBoxLayout()
        values_layout.setSpacing(16)

        # Current value
        current_value = self._format_value(self._prop.value)
        value_label = QLabel(current_value)
        value_label.setWordWrap(True)
        value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Apply diff styling
        is_modified = self._prop.diff_status == DiffStatus.MODIFIED
        if is_modified and self._show_diff:
            value_label.setStyleSheet(
                f"background-color: {DiffColors.MODIFIED_BG_DARK.name()}; "
                f"color: {DiffColors.MODIFIED_FG.name()}; "
                "padding: 2px 4px; border-radius: 2px;"
            )

        values_layout.addWidget(value_label, 1)

        # Show old value if modified
        if is_modified and self._prop.old_value is not None and self._show_diff:
            arrow_label = QLabel("←")
            arrow_label.setStyleSheet("color: #666;")
            values_layout.addWidget(arrow_label)

            old_value = self._format_value(self._prop.old_value)
            old_label = QLabel(old_value)
            old_label.setWordWrap(True)
            old_label.setStyleSheet("color: #888; text-decoration: line-through;")
            old_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            values_layout.addWidget(old_label, 1)

        layout.addLayout(values_layout, 1)

    def _format_value(self, value: Any) -> str:
        """Format a value for display."""
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "✓" if value else "✗"
        if isinstance(value, float):
            # Format floats with reasonable precision
            return f"{value:.4g}"
        if isinstance(value, dict):
            # Handle Unity object references
            if "fileID" in value:
                file_id = value.get("fileID", 0)
                if file_id == 0:
                    return "None"
                guid = value.get("guid", "")
                if guid:
                    return f"{{fileID: {file_id}, guid: {guid[:8]}...}}"
                return f"{{fileID: {file_id}}}"
            # Compact dict display
            import json

            try:
                return json.dumps(value, ensure_ascii=False)[:80]
            except Exception:
                return str(value)[:80]
        if isinstance(value, list):
            if len(value) == 0:
                return "[]"
            if len(value) <= 3:
                items = ", ".join(str(v) for v in value)
                return f"[{items}]"
            return f"[{len(value)} items]"
        return str(value)[:100]


class ComponentWidget(QFrame):
    """
    A collapsible component section similar to Unity's Inspector.

    Shows component header with expand/collapse button and property list.
    """

    def __init__(
        self,
        component: UnityComponent,
        other_component: Optional[UnityComponent] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._component = component
        self._other_component = other_component
        self._is_expanded = True
        self._property_widgets: list[QWidget] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self.setStyleSheet(
            """
            ComponentWidget {
                background-color: #383838;
                border: 1px solid #555;
                border-radius: 4px;
                margin: 2px 0;
            }
        """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self._header = self._create_header()
        layout.addWidget(self._header)

        # Properties container
        self._properties_container = QWidget()
        self._properties_layout = QVBoxLayout(self._properties_container)
        self._properties_layout.setContentsMargins(0, 4, 0, 4)
        self._properties_layout.setSpacing(0)

        self._populate_properties()
        layout.addWidget(self._properties_container)

    def _create_header(self) -> QWidget:
        """Create the component header with icon, name, and expand button."""
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(8)

        # Expand/collapse button
        self._expand_btn = QToolButton()
        self._expand_btn.setArrowType(Qt.ArrowType.DownArrow)
        self._expand_btn.setAutoRaise(True)
        self._expand_btn.setFixedSize(16, 16)
        self._expand_btn.clicked.connect(self._toggle_expand)
        header_layout.addWidget(self._expand_btn)

        # Component icon (emoji for now, could be replaced with proper icons)
        icon_label = QLabel(self._get_component_icon())
        icon_label.setStyleSheet("font-size: 14px;")
        header_layout.addWidget(icon_label)

        # Component name
        display_name = get_component_display_name(
            self._component.type_name, self._component.script_name
        )
        name_label = QLabel(display_name)
        name_label.setStyleSheet("font-weight: bold; font-size: 13px;")

        # Apply diff status color
        status = self._component.diff_status
        if status == DiffStatus.ADDED:
            name_label.setStyleSheet(
                f"font-weight: bold; font-size: 13px; color: {DiffColors.ADDED_FG.name()};"
            )
        elif status == DiffStatus.REMOVED:
            name_label.setStyleSheet(
                f"font-weight: bold; font-size: 13px; color: {DiffColors.REMOVED_FG.name()};"
            )
        elif status == DiffStatus.MODIFIED:
            name_label.setStyleSheet(
                f"font-weight: bold; font-size: 13px; color: {DiffColors.MODIFIED_FG.name()};"
            )

        header_layout.addWidget(name_label)
        header_layout.addStretch()

        # Diff status badge
        if status != DiffStatus.UNCHANGED:
            badge = QLabel(self._get_status_badge(status))
            badge.setStyleSheet("font-size: 11px; color: #888;")
            header_layout.addWidget(badge)

        # Set header background based on status
        bg_color = "#404040"
        if status == DiffStatus.ADDED:
            bg_color = DiffColors.ADDED_BG_DARK.name()
        elif status == DiffStatus.REMOVED:
            bg_color = DiffColors.REMOVED_BG_DARK.name()
        elif status == DiffStatus.MODIFIED:
            bg_color = DiffColors.MODIFIED_BG_DARK.name()

        header.setStyleSheet(
            f"""
            background-color: {bg_color};
            border-bottom: 1px solid #555;
            border-radius: 4px 4px 0 0;
        """
        )

        return header

    def _get_component_icon(self) -> str:
        """Get an icon for the component type."""
        icons = {
            "Transform": "📐",
            "RectTransform": "📐",
            "MeshRenderer": "🎨",
            "MeshFilter": "🔲",
            "SkinnedMeshRenderer": "🎭",
            "Camera": "📷",
            "Light": "💡",
            "AudioSource": "🔊",
            "Rigidbody": "⚙️",
            "Rigidbody2D": "⚙️",
            "Collider": "📦",
            "BoxCollider": "📦",
            "SphereCollider": "⚪",
            "CapsuleCollider": "💊",
            "MeshCollider": "🔲",
            "Animator": "🎬",
            "Animation": "🎬",
            "Canvas": "🖼️",
            "Image": "🖼️",
            "Text": "📝",
            "Button": "🔘",
            "ParticleSystem": "✨",
            "SpriteRenderer": "🖼️",
            "MonoBehaviour": "📜",
        }
        return icons.get(self._component.type_name, "📦")

    def _get_status_badge(self, status: DiffStatus) -> str:
        """Get status badge text."""
        badges = {
            DiffStatus.ADDED: "[Added]",
            DiffStatus.REMOVED: "[Removed]",
            DiffStatus.MODIFIED: "[Modified]",
        }
        return badges.get(status, "")

    def _populate_properties(self) -> None:
        """Populate the properties list."""
        other_props = {}
        if self._other_component:
            other_props = {p.path: p for p in self._other_component.properties}

        # Group properties by category (based on path structure)
        grouped = self._group_properties(self._component.properties)

        for group_name, props in grouped.items():
            if group_name:
                # Add group header
                group_label = QLabel(group_name)
                group_label.setStyleSheet(
                    "color: #909090; font-size: 11px; padding: 4px 8px; "
                    "background-color: #353535;"
                )
                self._properties_layout.addWidget(group_label)

            for prop in props:
                other_value = None
                other_prop = other_props.get(prop.path)
                if other_prop:
                    other_value = other_prop.value

                row = PropertyRowWidget(prop, other_value)
                self._properties_layout.addWidget(row)
                self._property_widgets.append(row)

    def _group_properties(
        self, properties: list[UnityProperty]
    ) -> dict[str, list[UnityProperty]]:
        """Group properties by their parent path."""
        groups: dict[str, list[UnityProperty]] = {"": []}

        for prop in properties:
            parts = prop.path.split(".")
            if len(parts) > 1:
                # Property is nested, group by parent
                parent = nicify_variable_name(parts[0])
                if parent not in groups:
                    groups[parent] = []
                groups[parent].append(prop)
            else:
                # Top-level property
                groups[""].append(prop)

        # Remove empty groups
        return {k: v for k, v in groups.items() if v}

    def _toggle_expand(self) -> None:
        """Toggle expanded/collapsed state."""
        self._is_expanded = not self._is_expanded
        self._properties_container.setVisible(self._is_expanded)
        self._expand_btn.setArrowType(
            Qt.ArrowType.DownArrow if self._is_expanded else Qt.ArrowType.RightArrow
        )


class GameObjectHeaderWidget(QWidget):
    """Header showing GameObject info similar to Unity's Inspector top section."""

    def __init__(
        self,
        game_object: UnityGameObject,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._game_object = game_object
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Name and active state row
        name_row = QHBoxLayout()
        name_row.setSpacing(8)

        # Active toggle indicator
        active_indicator = QLabel("✓" if self._game_object.is_active else "○")
        active_indicator.setStyleSheet(
            f"color: {'#4CAF50' if self._game_object.is_active else '#888'};"
            "font-size: 16px;"
        )
        name_row.addWidget(active_indicator)

        # GameObject name
        name_label = QLabel(self._game_object.name)
        name_label.setStyleSheet("font-size: 16px; font-weight: bold;")

        # Apply diff status
        status = self._game_object.diff_status
        if status == DiffStatus.ADDED:
            name_label.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {DiffColors.ADDED_FG.name()};"
            )
        elif status == DiffStatus.REMOVED:
            name_label.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {DiffColors.REMOVED_FG.name()};"
            )
        elif status == DiffStatus.MODIFIED:
            name_label.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {DiffColors.MODIFIED_FG.name()};"
            )

        name_row.addWidget(name_label)
        name_row.addStretch()

        layout.addLayout(name_row)

        # Tag and Layer row
        meta_row = QHBoxLayout()
        meta_row.setSpacing(16)

        tag_label = QLabel(f"Tag: {self._game_object.tag}")
        tag_label.setStyleSheet("color: #888; font-size: 11px;")
        meta_row.addWidget(tag_label)

        layer_label = QLabel(f"Layer: {self._game_object.layer}")
        layer_label.setStyleSheet("color: #888; font-size: 11px;")
        meta_row.addWidget(layer_label)

        meta_row.addStretch()
        layout.addLayout(meta_row)

        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #555;")
        separator.setFixedHeight(1)
        layout.addWidget(separator)


class InspectorWidget(QScrollArea):
    """
    Unity-style Inspector widget.

    Displays a selected GameObject's components and properties in a
    scrollable, collapsible view similar to Unity's Inspector.
    """

    property_selected = Signal(str)  # Emitted when a property is clicked

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._game_object: Optional[UnityGameObject] = None
        self._other_object: Optional[UnityGameObject] = None  # For comparison
        self._component_widgets: list[ComponentWidget] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            """
            QScrollArea {
                background-color: #2d2d2d;
                border: none;
            }
        """
        )

        # Content widget
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setSpacing(4)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Placeholder message
        self._placeholder = QLabel("Select an object to inspect")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #666; font-size: 14px; padding: 40px;")
        self._content_layout.addWidget(self._placeholder)

        self.setWidget(self._content)

    def set_game_object(
        self,
        game_object: Optional[UnityGameObject],
        other_object: Optional[UnityGameObject] = None,
    ) -> None:
        """
        Set the GameObject to display.

        Args:
            game_object: The GameObject to inspect
            other_object: Optional other version for comparison (for diff view)
        """
        self._game_object = game_object
        self._other_object = other_object
        self._refresh()

    def set_component(
        self,
        component: UnityComponent,
        other_component: Optional[UnityComponent] = None,
    ) -> None:
        """
        Display a single component.

        Args:
            component: The component to display
            other_component: Optional other version for comparison
        """
        self._clear()

        if component:
            widget = ComponentWidget(component, other_component)
            self._content_layout.addWidget(widget)
            self._component_widgets.append(widget)

        self._content_layout.addStretch()

    def clear(self) -> None:
        """Clear the inspector."""
        self._game_object = None
        self._other_object = None
        self._refresh()

    def _refresh(self) -> None:
        """Refresh the display."""
        self._clear()

        if not self._game_object:
            self._placeholder.show()
            return

        self._placeholder.hide()

        # Add GameObject header
        header = GameObjectHeaderWidget(self._game_object)
        self._content_layout.addWidget(header)

        # Build component lookup for other object
        other_components = {}
        if self._other_object:
            other_components = {c.file_id: c for c in self._other_object.components}

        # Add component widgets
        for component in self._game_object.components:
            other_comp = other_components.get(component.file_id)
            widget = ComponentWidget(component, other_comp)
            self._content_layout.addWidget(widget)
            self._component_widgets.append(widget)

        # Add stretch at the end
        self._content_layout.addStretch()

    def _clear(self) -> None:
        """Clear all widgets."""
        self._component_widgets.clear()

        # Remove all widgets except the placeholder
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(self._content_layout.count() - 1)
            if item.widget() and item.widget() != self._placeholder:
                item.widget().deleteLater()

        # Also remove stretch
        while self._content_layout.count() > 0:
            item = self._content_layout.itemAt(0)
            if item.widget() == self._placeholder:
                break
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._placeholder.show()

    def expand_all(self) -> None:
        """Expand all component sections."""
        for widget in self._component_widgets:
            if not widget._is_expanded:
                widget._toggle_expand()

    def collapse_all(self) -> None:
        """Collapse all component sections."""
        for widget in self._component_widgets:
            if widget._is_expanded:
                widget._toggle_expand()
