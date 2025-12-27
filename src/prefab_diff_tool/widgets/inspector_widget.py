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
    QLineEdit,
)

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


# Properties to skip (internal Unity properties)
SKIP_PROPERTIES = {
    "m_ObjectHideFlags",
    "m_CorrespondingSourceObject",
    "m_PrefabInstance",
    "m_PrefabAsset",
    "serializedVersion",
    "m_EditorHideFlags",
    "m_EditorClassIdentifier",
}


def _is_vector_like(value: Any) -> bool:
    """Check if value looks like a Unity Vector (has x, y, z or x, y components)."""
    if not isinstance(value, dict):
        return False
    keys = set(value.keys())
    return keys == {"x", "y"} or keys == {"x", "y", "z"} or keys == {"x", "y", "z", "w"}


def _is_color_like(value: Any) -> bool:
    """Check if value looks like a Unity Color (has r, g, b, a components)."""
    if not isinstance(value, dict):
        return False
    keys = set(value.keys())
    return keys == {"r", "g", "b", "a"}


def _is_reference(value: Any) -> bool:
    """Check if value is a Unity object reference."""
    if not isinstance(value, dict):
        return False
    return "fileID" in value


def _format_float(value: float) -> str:
    """Format a float value for display."""
    if value == int(value):
        return str(int(value))
    return f"{value:.4g}"


class FieldWidget(QWidget):
    """A Unity-style field widget with label and value display."""

    def __init__(
        self,
        label: str,
        value: str,
        is_modified: bool = False,
        old_value: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._setup_ui(label, value, is_modified, old_value)

    def _setup_ui(
        self,
        label: str,
        value: str,
        is_modified: bool,
        old_value: Optional[str],
    ) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)

        # Label
        label_widget = QLabel(label)
        label_widget.setFixedWidth(60)
        label_widget.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        layout.addWidget(label_widget)

        # Value field (read-only)
        value_field = QLineEdit(value)
        value_field.setReadOnly(True)
        value_field.setFrame(False)

        if is_modified:
            value_field.setStyleSheet(
                f"background-color: {DiffColors.MODIFIED_BG_DARK.name()}; "
                f"color: {DiffColors.MODIFIED_FG.name()}; "
                "padding: 2px 4px; border-radius: 2px; font-size: 11px;"
            )
        else:
            value_field.setStyleSheet(
                "background-color: #3c3c3c; color: #e0e0e0; "
                "padding: 2px 4px; border-radius: 2px; font-size: 11px;"
            )

        layout.addWidget(value_field, 1)

        # Show old value if modified
        if is_modified and old_value is not None:
            arrow = QLabel("←")
            arrow.setStyleSheet("color: #666; font-size: 11px;")
            layout.addWidget(arrow)

            old_field = QLineEdit(old_value)
            old_field.setReadOnly(True)
            old_field.setFrame(False)
            old_field.setStyleSheet(
                "background-color: #2a2a2a; color: #888; "
                "padding: 2px 4px; border-radius: 2px; font-size: 11px; "
                "text-decoration: line-through;"
            )
            layout.addWidget(old_field, 1)


class VectorFieldWidget(QWidget):
    """Unity-style Vector field with X, Y, Z (and optionally W) components."""

    def __init__(
        self,
        value: dict,
        is_modified: bool = False,
        old_value: Optional[dict] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._setup_ui(value, is_modified, old_value)

    def _setup_ui(
        self,
        value: dict,
        is_modified: bool,
        old_value: Optional[dict],
    ) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(8)

        components = ["x", "y", "z", "w"]
        labels = ["X", "Y", "Z", "W"]
        colors = ["#ff6b6b", "#6bff6b", "#6b6bff", "#ffff6b"]

        for comp, label, color in zip(components, labels, colors):
            if comp not in value:
                continue

            # Component label
            comp_label = QLabel(label)
            comp_label.setFixedWidth(12)
            comp_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
            layout.addWidget(comp_label)

            # Value
            val_str = _format_float(value[comp]) if isinstance(value[comp], (int, float)) else str(value[comp])
            val_field = QLineEdit(val_str)
            val_field.setReadOnly(True)
            val_field.setFrame(False)

            # Check if this specific component changed
            comp_modified = is_modified and old_value and old_value.get(comp) != value.get(comp)

            if comp_modified:
                val_field.setStyleSheet(
                    f"background-color: {DiffColors.MODIFIED_BG_DARK.name()}; "
                    f"color: {DiffColors.MODIFIED_FG.name()}; "
                    "padding: 2px 4px; border-radius: 2px; font-size: 11px;"
                )
            else:
                val_field.setStyleSheet(
                    "background-color: #3c3c3c; color: #e0e0e0; "
                    "padding: 2px 4px; border-radius: 2px; font-size: 11px;"
                )

            layout.addWidget(val_field, 1)

        layout.addStretch()


class ColorFieldWidget(QWidget):
    """Unity-style Color field with R, G, B, A components and color preview."""

    def __init__(
        self,
        value: dict,
        is_modified: bool = False,
        old_value: Optional[dict] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._setup_ui(value, is_modified, old_value)

    def _setup_ui(
        self,
        value: dict,
        is_modified: bool,
        old_value: Optional[dict],
    ) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)

        # Color preview
        r = int(float(value.get("r", 0)) * 255)
        g = int(float(value.get("g", 0)) * 255)
        b = int(float(value.get("b", 0)) * 255)
        a = float(value.get("a", 1))

        color_preview = QFrame()
        color_preview.setFixedSize(40, 18)
        color_preview.setStyleSheet(
            f"background-color: rgba({r}, {g}, {b}, {a}); "
            "border: 1px solid #555; border-radius: 2px;"
        )
        layout.addWidget(color_preview)

        # RGBA values
        components = ["r", "g", "b", "a"]
        labels = ["R", "G", "B", "A"]

        for comp, label in zip(components, labels):
            comp_label = QLabel(label)
            comp_label.setFixedWidth(12)
            comp_label.setStyleSheet("color: #888; font-size: 10px;")
            layout.addWidget(comp_label)

            val = value.get(comp, 0)
            val_str = _format_float(val) if isinstance(val, (int, float)) else str(val)

            val_field = QLineEdit(val_str)
            val_field.setReadOnly(True)
            val_field.setFrame(False)
            val_field.setFixedWidth(40)

            comp_modified = is_modified and old_value and old_value.get(comp) != value.get(comp)

            if comp_modified:
                val_field.setStyleSheet(
                    f"background-color: {DiffColors.MODIFIED_BG_DARK.name()}; "
                    f"color: {DiffColors.MODIFIED_FG.name()}; "
                    "padding: 1px 2px; border-radius: 2px; font-size: 10px;"
                )
            else:
                val_field.setStyleSheet(
                    "background-color: #3c3c3c; color: #e0e0e0; "
                    "padding: 1px 2px; border-radius: 2px; font-size: 10px;"
                )

            layout.addWidget(val_field)

        layout.addStretch()


class ReferenceFieldWidget(QWidget):
    """Unity-style object reference field."""

    def __init__(
        self,
        value: dict,
        is_modified: bool = False,
        old_value: Optional[dict] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._setup_ui(value, is_modified, old_value)

    def _setup_ui(
        self,
        value: dict,
        is_modified: bool,
        old_value: Optional[dict],
    ) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)

        # Format reference
        file_id = value.get("fileID", 0)
        guid = value.get("guid", "")

        if file_id == 0:
            display = "None"
        elif guid:
            display = f"({guid[:8]}...)"
        else:
            display = f"(ID: {file_id})"

        # Reference field
        ref_field = QLineEdit(display)
        ref_field.setReadOnly(True)
        ref_field.setFrame(False)

        if is_modified:
            ref_field.setStyleSheet(
                f"background-color: {DiffColors.MODIFIED_BG_DARK.name()}; "
                f"color: {DiffColors.MODIFIED_FG.name()}; "
                "padding: 2px 4px; border-radius: 2px; font-size: 11px;"
            )
        else:
            ref_field.setStyleSheet(
                "background-color: #3c3c3c; color: #a0a0a0; "
                "padding: 2px 4px; border-radius: 2px; font-size: 11px; "
                "font-style: italic;"
            )

        layout.addWidget(ref_field, 1)

        # Old value if modified
        if is_modified and old_value is not None:
            arrow = QLabel("←")
            arrow.setStyleSheet("color: #666; font-size: 11px;")
            layout.addWidget(arrow)

            old_file_id = old_value.get("fileID", 0)
            old_guid = old_value.get("guid", "")

            if old_file_id == 0:
                old_display = "None"
            elif old_guid:
                old_display = f"({old_guid[:8]}...)"
            else:
                old_display = f"(ID: {old_file_id})"

            old_field = QLineEdit(old_display)
            old_field.setReadOnly(True)
            old_field.setFrame(False)
            old_field.setStyleSheet(
                "background-color: #2a2a2a; color: #666; "
                "padding: 2px 4px; border-radius: 2px; font-size: 11px; "
                "text-decoration: line-through; font-style: italic;"
            )
            layout.addWidget(old_field, 1)


class PropertyRowWidget(QWidget):
    """A single property row with Unity-style field display."""

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
        layout.setContentsMargins(16, 2, 8, 2)
        layout.setSpacing(8)

        # Property name (nicified)
        name_label = QLabel(nicify_variable_name(self._prop.name))
        name_label.setFixedWidth(130)
        name_label.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        layout.addWidget(name_label)

        # Get diff info
        is_modified = self._prop.diff_status == DiffStatus.MODIFIED and self._show_diff
        old_value = self._prop.old_value if is_modified else None

        # Create appropriate field widget based on value type
        value = self._prop.value

        if _is_vector_like(value):
            field = VectorFieldWidget(value, is_modified, old_value)
        elif _is_color_like(value):
            field = ColorFieldWidget(value, is_modified, old_value)
        elif _is_reference(value):
            field = ReferenceFieldWidget(value, is_modified, old_value)
        else:
            # Simple value field
            value_str = self._format_simple_value(value)
            old_str = self._format_simple_value(old_value) if old_value is not None else None
            field = FieldWidget("", value_str, is_modified, old_str)

        layout.addWidget(field, 1)

    def _format_simple_value(self, value: Any) -> str:
        """Format a simple value for display."""
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "✓" if value else "✗"
        if isinstance(value, float):
            return _format_float(value)
        if isinstance(value, int):
            return str(value)
        if isinstance(value, list):
            if len(value) == 0:
                return "[ ]"
            return f"Array [{len(value)}]"
        if isinstance(value, dict):
            # Generic dict (not vector/color/reference)
            return "{...}"
        return str(value)[:60]


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

        # Component icon
        icon_label = QLabel(self._get_component_icon())
        icon_label.setStyleSheet("font-size: 14px;")
        header_layout.addWidget(icon_label)

        # Component name
        display_name = get_component_display_name(
            self._component.type_name, self._component.script_name
        )
        name_label = QLabel(display_name)
        name_label.setStyleSheet("font-weight: bold; font-size: 12px;")

        # Apply diff status color
        status = self._component.diff_status
        if status == DiffStatus.ADDED:
            name_label.setStyleSheet(
                f"font-weight: bold; font-size: 12px; color: {DiffColors.ADDED_FG.name()};"
            )
        elif status == DiffStatus.REMOVED:
            name_label.setStyleSheet(
                f"font-weight: bold; font-size: 12px; color: {DiffColors.REMOVED_FG.name()};"
            )
        elif status == DiffStatus.MODIFIED:
            name_label.setStyleSheet(
                f"font-weight: bold; font-size: 12px; color: {DiffColors.MODIFIED_FG.name()};"
            )

        header_layout.addWidget(name_label)
        header_layout.addStretch()

        # Diff status badge
        if status != DiffStatus.UNCHANGED:
            badge = QLabel(self._get_status_badge(status))
            badge.setStyleSheet("font-size: 10px; color: #888;")
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
            DiffStatus.ADDED: "[+]",
            DiffStatus.REMOVED: "[-]",
            DiffStatus.MODIFIED: "[~]",
        }
        return badges.get(status, "")

    def _populate_properties(self) -> None:
        """Populate the properties list."""
        other_props = {}
        if self._other_component:
            other_props = {p.path: p for p in self._other_component.properties}

        # Filter out internal Unity properties
        visible_props = [
            p for p in self._component.properties
            if p.name not in SKIP_PROPERTIES
        ]

        # Group properties by category (based on path structure)
        grouped = self._group_properties(visible_props)

        for group_name, props in grouped.items():
            if group_name:
                # Add group header
                group_label = QLabel(group_name)
                group_label.setStyleSheet(
                    "color: #909090; font-size: 10px; padding: 4px 8px; "
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
        name_label.setStyleSheet("font-size: 14px; font-weight: bold;")

        # Apply diff status
        status = self._game_object.diff_status
        if status == DiffStatus.ADDED:
            name_label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {DiffColors.ADDED_FG.name()};"
            )
        elif status == DiffStatus.REMOVED:
            name_label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {DiffColors.REMOVED_FG.name()};"
            )
        elif status == DiffStatus.MODIFIED:
            name_label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {DiffColors.MODIFIED_FG.name()};"
            )

        name_row.addWidget(name_label)
        name_row.addStretch()

        layout.addLayout(name_row)

        # Tag and Layer row
        meta_row = QHBoxLayout()
        meta_row.setSpacing(16)

        tag_label = QLabel(f"Tag: {self._game_object.tag}")
        tag_label.setStyleSheet("color: #888; font-size: 10px;")
        meta_row.addWidget(tag_label)

        layer_label = QLabel(f"Layer: {self._game_object.layer}")
        layer_label.setStyleSheet("color: #888; font-size: 10px;")
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
        self._placeholder.setStyleSheet("color: #666; font-size: 12px; padding: 40px;")
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
