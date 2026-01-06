"""
Unity-style Inspector widget for displaying component properties.

Displays components and their properties in a collapsible, hierarchical view
similar to Unity's Inspector window.
"""

from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QFrame,
    QLabel,
    QHBoxLayout,
    QToolButton,
    QLineEdit,
    QPushButton,
    QMenu,
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
from prefab_diff_tool.utils.guid_resolver import GuidResolver


# Properties to skip in Normal mode (internal Unity properties)
SKIP_PROPERTIES_NORMAL = {
    "m_ObjectHideFlags",
    "m_CorrespondingSourceObject",
    "m_PrefabInstance",
    "m_PrefabAsset",
    "serializedVersion",
    "m_EditorHideFlags",
    "m_EditorClassIdentifier",
    "m_GameObject",  # Reference to parent GameObject - not shown in Unity Inspector
}

# Additional properties to skip for Transform components in Normal mode
TRANSFORM_SKIP_PROPERTIES = {
    "m_Father",  # Hierarchy info - shown in Hierarchy panel
    "m_Children",  # Hierarchy info - shown in Hierarchy panel
    "m_RootOrder",  # Internal ordering
    "m_ConstrainProportionsScale",  # Shown as chain button instead
    "m_LocalRotation",  # Quaternion - use EulerAnglesHint instead for display
}

# Properties to display for Transform in Normal mode (Unity Inspector style)
TRANSFORM_DISPLAY_PROPERTIES = {
    "m_LocalPosition",
    "m_LocalEulerAnglesHint",  # Euler angles (shown as "Rotation" in Unity)
    "m_LocalScale",
}

# RectTransform additional properties
RECT_TRANSFORM_DISPLAY_PROPERTIES = {
    "m_AnchoredPosition",
    "m_SizeDelta",
    "m_Pivot",
    "m_AnchorMin",
    "m_AnchorMax",
    "m_AnchoredPosition3D",
}

# Properties to skip in Debug mode (minimal filtering)
SKIP_PROPERTIES_DEBUG = {
    "serializedVersion",
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

        # Label (only if not empty)
        if label:
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
        layout.setSpacing(4)

        components = ["x", "y", "z", "w"]
        labels = ["X", "Y", "Z", "W"]
        colors = ["#ff6b6b", "#6bff6b", "#6b6bff", "#ffff6b"]

        for comp, label, color in zip(components, labels, colors):
            if comp not in value:
                continue

            # Component label
            comp_label = QLabel(label)
            comp_label.setFixedWidth(14)
            comp_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
            layout.addWidget(comp_label)

            # Value - use stretch factor for equal distribution
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

            layout.addWidget(val_field, 1)  # Equal stretch factor


class ScaleFieldWidget(QWidget):
    """Unity-style Scale field with X, Y, Z components and chain link button."""

    def __init__(
        self,
        value: dict,
        constrain_proportions: bool = False,
        is_modified: bool = False,
        old_value: Optional[dict] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._constrain_proportions = constrain_proportions
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

        components = ["x", "y", "z"]
        labels = ["X", "Y", "Z"]
        colors = ["#ff6b6b", "#6bff6b", "#6b6bff"]

        for comp, label, color in zip(components, labels, colors):
            if comp not in value:
                continue

            # Component label
            comp_label = QLabel(label)
            comp_label.setFixedWidth(14)
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

        # Chain link button for constrain proportions
        chain_btn = QToolButton()
        chain_btn.setFixedSize(20, 20)
        chain_btn.setAutoRaise(True)
        if self._constrain_proportions:
            chain_btn.setText("🔗")
            chain_btn.setToolTip("Constrain Proportions: On")
            chain_btn.setStyleSheet("font-size: 12px; color: #4CAF50;")
        else:
            chain_btn.setText("⛓")
            chain_btn.setToolTip("Constrain Proportions: Off")
            chain_btn.setStyleSheet("font-size: 12px; color: #666;")
        layout.addWidget(chain_btn)


class ArrayFieldWidget(QFrame):
    """Expandable array field widget showing all array elements."""

    # Signals for reference navigation
    reference_clicked = Signal(str, str)  # file_id, guid
    external_reference_clicked = Signal(str)  # guid

    def __init__(
        self,
        value: list,
        prop_name: str = "",
        is_modified: bool = False,
        old_value: Optional[list] = None,
        document: Optional[Any] = None,
        guid_resolver: Optional["GuidResolver"] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._value = value
        self._prop_name = prop_name
        self._is_modified = is_modified
        self._old_value = old_value
        self._document = document
        self._guid_resolver = guid_resolver
        self._is_expanded = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self.setStyleSheet(
            "ArrayFieldWidget { background-color: #353535; border: 1px solid #444; border-radius: 3px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        # Header row with expand button
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        # Expand button
        self._expand_btn = QToolButton()
        self._expand_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._expand_btn.setAutoRaise(True)
        self._expand_btn.setFixedSize(16, 16)
        self._expand_btn.clicked.connect(self._toggle_expand)
        header_layout.addWidget(self._expand_btn)

        # Array info label
        count = len(self._value)
        label_text = f"Array [{count}]"
        if self._is_modified and self._old_value is not None:
            old_count = len(self._old_value)
            if old_count != count:
                label_text = f"Array [{count}] ← [{old_count}]"
        self._header_label = QLabel(label_text)
        if self._is_modified:
            self._header_label.setStyleSheet(
                f"color: {DiffColors.MODIFIED_FG.name()}; font-size: 11px;"
            )
        else:
            self._header_label.setStyleSheet("color: #aaa; font-size: 11px;")
        header_layout.addWidget(self._header_label)
        header_layout.addStretch()

        layout.addWidget(header)

        # Content container (hidden by default)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(16, 4, 0, 4)
        self._content_layout.setSpacing(2)
        self._content.setVisible(False)
        layout.addWidget(self._content)

    def _toggle_expand(self) -> None:
        """Toggle expanded/collapsed state."""
        self._is_expanded = not self._is_expanded
        self._expand_btn.setArrowType(
            Qt.ArrowType.DownArrow if self._is_expanded else Qt.ArrowType.RightArrow
        )

        if self._is_expanded and self._content_layout.count() == 0:
            self._populate_content()

        self._content.setVisible(self._is_expanded)

    def _populate_content(self) -> None:
        """Populate the array content when first expanded."""
        for i, item in enumerate(self._value):
            old_item = None
            is_item_modified = False

            if self._is_modified and self._old_value is not None:
                if i < len(self._old_value):
                    old_item = self._old_value[i]
                    is_item_modified = item != old_item
                else:
                    is_item_modified = True  # New item

            row = self._create_element_row(i, item, is_item_modified, old_item)
            self._content_layout.addWidget(row)

        # Show removed items from old value
        if self._is_modified and self._old_value is not None:
            for i in range(len(self._value), len(self._old_value)):
                row = self._create_removed_row(i, self._old_value[i])
                self._content_layout.addWidget(row)

    def _create_element_row(
        self, index: int, value: Any, is_modified: bool, old_value: Any
    ) -> QWidget:
        """Create a widget row for an array element."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 1, 0, 1)
        row_layout.setSpacing(4)

        # Index label
        idx_label = QLabel(f"[{index}]")
        idx_label.setFixedWidth(40)
        idx_label.setStyleSheet("color: #888; font-size: 10px;")
        row_layout.addWidget(idx_label)

        # Value widget based on type
        if _is_vector_like(value):
            field = VectorFieldWidget(value, is_modified, old_value if is_modified else None)
            row_layout.addWidget(field, 1)
        elif _is_color_like(value):
            field = ColorFieldWidget(value, is_modified, old_value if is_modified else None)
            row_layout.addWidget(field, 1)
        elif _is_reference(value):
            field = ReferenceFieldWidget(
                value, is_modified, old_value if is_modified else None,
                self._document, self._guid_resolver
            )
            field.reference_clicked.connect(self.reference_clicked)
            field.external_reference_clicked.connect(self.external_reference_clicked)
            row_layout.addWidget(field, 1)
        elif isinstance(value, list):
            # Nested array
            nested = ArrayFieldWidget(
                value, f"[{index}]", is_modified, old_value if is_modified else None,
                self._document, self._guid_resolver
            )
            nested.reference_clicked.connect(self.reference_clicked)
            nested.external_reference_clicked.connect(self.external_reference_clicked)
            row_layout.addWidget(nested, 1)
        elif isinstance(value, dict):
            # Nested dict - show as expandable
            nested = DictFieldWidget(
                value, f"[{index}]", is_modified, old_value if is_modified else None,
                self._document, self._guid_resolver
            )
            nested.reference_clicked.connect(self.reference_clicked)
            nested.external_reference_clicked.connect(self.external_reference_clicked)
            row_layout.addWidget(nested, 1)
        else:
            # Simple value
            val_str = self._format_simple_value(value)
            old_str = self._format_simple_value(old_value) if is_modified and old_value is not None else None
            field = FieldWidget("", val_str, is_modified, old_str)
            row_layout.addWidget(field, 1)

        return row

    def _create_removed_row(self, index: int, value: Any) -> QWidget:
        """Create a widget row for a removed array element."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 1, 0, 1)
        row_layout.setSpacing(4)

        idx_label = QLabel(f"[{index}]")
        idx_label.setFixedWidth(40)
        idx_label.setStyleSheet(f"color: {DiffColors.REMOVED_FG.name()}; font-size: 10px; text-decoration: line-through;")
        row_layout.addWidget(idx_label)

        val_str = self._format_simple_value(value)
        removed_label = QLabel(val_str)
        removed_label.setStyleSheet(
            f"color: {DiffColors.REMOVED_FG.name()}; font-size: 11px; text-decoration: line-through;"
        )
        row_layout.addWidget(removed_label, 1)

        return row

    def _format_simple_value(self, value: Any) -> str:
        """Format a simple value for display."""
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "✓" if value else "✗"
        if isinstance(value, float):
            return _format_float(value)
        if isinstance(value, (int, str)):
            return str(value)
        if isinstance(value, list):
            return f"Array [{len(value)}]"
        if isinstance(value, dict):
            if _is_reference(value):
                return f"(ref: {value.get('fileID', 0)})"
            return "{...}"
        return str(value)[:60]


class DictFieldWidget(QFrame):
    """Expandable dictionary/object field widget showing all properties."""

    # Signals for reference navigation
    reference_clicked = Signal(str, str)  # file_id, guid
    external_reference_clicked = Signal(str)  # guid

    def __init__(
        self,
        value: dict,
        prop_name: str = "",
        is_modified: bool = False,
        old_value: Optional[dict] = None,
        document: Optional[Any] = None,
        guid_resolver: Optional["GuidResolver"] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._value = value
        self._prop_name = prop_name
        self._is_modified = is_modified
        self._old_value = old_value
        self._document = document
        self._guid_resolver = guid_resolver
        self._is_expanded = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self.setStyleSheet(
            "DictFieldWidget { background-color: #353535; border: 1px solid #444; border-radius: 3px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        # Header row with expand button
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        # Expand button
        self._expand_btn = QToolButton()
        self._expand_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._expand_btn.setAutoRaise(True)
        self._expand_btn.setFixedSize(16, 16)
        self._expand_btn.clicked.connect(self._toggle_expand)
        header_layout.addWidget(self._expand_btn)

        # Object info label
        count = len(self._value)
        label_text = f"Object {{{count} properties}}"
        self._header_label = QLabel(label_text)
        if self._is_modified:
            self._header_label.setStyleSheet(
                f"color: {DiffColors.MODIFIED_FG.name()}; font-size: 11px;"
            )
        else:
            self._header_label.setStyleSheet("color: #aaa; font-size: 11px;")
        header_layout.addWidget(self._header_label)
        header_layout.addStretch()

        layout.addWidget(header)

        # Content container (hidden by default)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(16, 4, 0, 4)
        self._content_layout.setSpacing(2)
        self._content.setVisible(False)
        layout.addWidget(self._content)

    def _toggle_expand(self) -> None:
        """Toggle expanded/collapsed state."""
        self._is_expanded = not self._is_expanded
        self._expand_btn.setArrowType(
            Qt.ArrowType.DownArrow if self._is_expanded else Qt.ArrowType.RightArrow
        )

        if self._is_expanded and self._content_layout.count() == 0:
            self._populate_content()

        self._content.setVisible(self._is_expanded)

    def _populate_content(self) -> None:
        """Populate the dict content when first expanded."""
        old_dict = self._old_value if isinstance(self._old_value, dict) else {}

        for key, item in self._value.items():
            old_item = old_dict.get(key)
            is_item_modified = self._is_modified and (key not in old_dict or item != old_item)

            row = self._create_property_row(key, item, is_item_modified, old_item)
            self._content_layout.addWidget(row)

        # Show removed keys
        if self._is_modified and old_dict:
            for key in old_dict:
                if key not in self._value:
                    row = self._create_removed_row(key, old_dict[key])
                    self._content_layout.addWidget(row)

    def _create_property_row(
        self, key: str, value: Any, is_modified: bool, old_value: Any
    ) -> QWidget:
        """Create a widget row for a dict property."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 1, 0, 1)
        row_layout.setSpacing(4)

        # Key label
        key_label = QLabel(nicify_variable_name(key))
        key_label.setFixedWidth(100)
        key_label.setStyleSheet("color: #b0b0b0; font-size: 10px;")
        row_layout.addWidget(key_label)

        # Value widget based on type
        if _is_vector_like(value):
            field = VectorFieldWidget(value, is_modified, old_value if is_modified else None)
            row_layout.addWidget(field, 1)
        elif _is_color_like(value):
            field = ColorFieldWidget(value, is_modified, old_value if is_modified else None)
            row_layout.addWidget(field, 1)
        elif _is_reference(value):
            field = ReferenceFieldWidget(
                value, is_modified, old_value if is_modified else None,
                self._document, self._guid_resolver
            )
            field.reference_clicked.connect(self.reference_clicked)
            field.external_reference_clicked.connect(self.external_reference_clicked)
            row_layout.addWidget(field, 1)
        elif isinstance(value, list):
            nested = ArrayFieldWidget(
                value, key, is_modified, old_value if is_modified else None,
                self._document, self._guid_resolver
            )
            nested.reference_clicked.connect(self.reference_clicked)
            nested.external_reference_clicked.connect(self.external_reference_clicked)
            row_layout.addWidget(nested, 1)
        elif isinstance(value, dict):
            nested = DictFieldWidget(
                value, key, is_modified, old_value if is_modified else None,
                self._document, self._guid_resolver
            )
            nested.reference_clicked.connect(self.reference_clicked)
            nested.external_reference_clicked.connect(self.external_reference_clicked)
            row_layout.addWidget(nested, 1)
        else:
            val_str = self._format_simple_value(value)
            old_str = self._format_simple_value(old_value) if is_modified and old_value is not None else None
            field = FieldWidget("", val_str, is_modified, old_str)
            row_layout.addWidget(field, 1)

        return row

    def _create_removed_row(self, key: str, value: Any) -> QWidget:
        """Create a widget row for a removed property."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 1, 0, 1)
        row_layout.setSpacing(4)

        key_label = QLabel(nicify_variable_name(key))
        key_label.setFixedWidth(100)
        key_label.setStyleSheet(f"color: {DiffColors.REMOVED_FG.name()}; font-size: 10px; text-decoration: line-through;")
        row_layout.addWidget(key_label)

        val_str = self._format_simple_value(value)
        removed_label = QLabel(val_str)
        removed_label.setStyleSheet(
            f"color: {DiffColors.REMOVED_FG.name()}; font-size: 11px; text-decoration: line-through;"
        )
        row_layout.addWidget(removed_label, 1)

        return row

    def _format_simple_value(self, value: Any) -> str:
        """Format a simple value for display."""
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "✓" if value else "✗"
        if isinstance(value, float):
            return _format_float(value)
        if isinstance(value, (int, str)):
            return str(value)
        if isinstance(value, list):
            return f"Array [{len(value)}]"
        if isinstance(value, dict):
            if _is_reference(value):
                return f"(ref: {value.get('fileID', 0)})"
            return "{...}"
        return str(value)[:60]


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
    """Unity-style object reference field with click-to-navigate support."""

    # Signals for navigation
    reference_clicked = Signal(str, str)  # file_id, guid
    external_reference_clicked = Signal(str)  # guid (for external assets)

    def __init__(
        self,
        value: dict,
        is_modified: bool = False,
        old_value: Optional[dict] = None,
        document: Optional[Any] = None,  # UnityDocument for resolving internal refs
        guid_resolver: Optional[GuidResolver] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._value = value
        self._document = document
        self._guid_resolver = guid_resolver
        self._setup_ui(value, is_modified, old_value)

    def _resolve_reference(self, value: dict) -> str:
        """Resolve a reference to a display name like 'ObjectName (ComponentType)'."""
        file_id = value.get("fileID", 0)
        guid = value.get("guid", "")

        if file_id == 0:
            return "None"

        # External reference (has GUID)
        if guid:
            # Try to resolve using GUID resolver
            if self._guid_resolver:
                name, asset_type = self._guid_resolver.resolve_with_type(guid)
                if name:
                    return f"{name} ({asset_type})"
            # Fallback to showing partial GUID
            return f"External Asset ({guid[:8]}...)"

        # Internal reference - try to resolve from document
        if self._document:
            file_id_str = str(file_id)
            # Check if it's a GameObject
            go = self._document.all_objects.get(file_id_str)
            if go:
                return f"{go.name} (GameObject)"

            # Check if it's a Component - use O(1) reverse lookup
            comp = self._document.all_components.get(file_id_str)
            if comp:
                owner = self._document.get_component_owner(file_id_str)
                comp_name = comp.script_name or comp.type_name
                if owner:
                    return f"{owner.name} ({comp_name})"
                return f"({comp_name})"

        # Fallback
        return f"(ID: {file_id})"

    def _setup_ui(
        self,
        value: dict,
        is_modified: bool,
        old_value: Optional[dict],
    ) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)

        file_id = value.get("fileID", 0)
        guid = value.get("guid", "")
        display = self._resolve_reference(value)

        # Create clickable button for non-None references
        if file_id != 0:
            ref_btn = QPushButton(display)
            ref_btn.setFlat(True)
            ref_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            if is_modified:
                ref_btn.setStyleSheet(
                    f"QPushButton {{ background-color: {DiffColors.MODIFIED_BG_DARK.name()}; "
                    f"color: {DiffColors.MODIFIED_FG.name()}; "
                    "padding: 2px 4px; border-radius: 2px; font-size: 11px; "
                    "text-align: left; border: none; }} "
                    "QPushButton:hover { background-color: #4a4a4a; }"
                )
            else:
                ref_btn.setStyleSheet(
                    "QPushButton { background-color: #3c3c3c; color: #7eb8ff; "
                    "padding: 2px 4px; border-radius: 2px; font-size: 11px; "
                    "text-align: left; border: none; } "
                    "QPushButton:hover { background-color: #4a4a4a; text-decoration: underline; }"
                )

            ref_btn.clicked.connect(lambda: self._on_click(value))
            layout.addWidget(ref_btn, 1)
        else:
            # None reference - just show label
            ref_label = QLabel(display)
            ref_label.setStyleSheet(
                "background-color: #3c3c3c; color: #888; "
                "padding: 2px 4px; border-radius: 2px; font-size: 11px; "
                "font-style: italic;"
            )
            layout.addWidget(ref_label, 1)

        # Old value if modified
        if is_modified and old_value is not None:
            arrow = QLabel("←")
            arrow.setStyleSheet("color: #666; font-size: 11px;")
            layout.addWidget(arrow)

            old_display = self._resolve_reference(old_value)
            old_field = QLabel(old_display)
            old_field.setStyleSheet(
                "background-color: #2a2a2a; color: #666; "
                "padding: 2px 4px; border-radius: 2px; font-size: 11px; "
                "text-decoration: line-through; font-style: italic;"
            )
            layout.addWidget(old_field, 1)

    def _on_click(self, value: dict) -> None:
        """Handle click on reference."""
        file_id = str(value.get("fileID", 0))
        guid = value.get("guid", "")

        if guid:
            # External reference
            self.external_reference_clicked.emit(guid)
        else:
            # Internal reference
            self.reference_clicked.emit(file_id, guid)


class PropertyRowWidget(QWidget):
    """A single property row with Unity-style field display."""

    # Signals for reference navigation
    reference_clicked = Signal(str, str)  # file_id, guid
    external_reference_clicked = Signal(str)  # guid

    def __init__(
        self,
        prop: UnityProperty,
        other_value: Any = None,
        show_diff: bool = True,
        document: Optional[Any] = None,
        guid_resolver: Optional[GuidResolver] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._prop = prop
        self._other_value = other_value
        self._show_diff = show_diff
        self._document = document
        self._guid_resolver = guid_resolver
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
            field = ReferenceFieldWidget(
                value, is_modified, old_value, self._document, self._guid_resolver
            )
            # Forward signals
            field.reference_clicked.connect(self.reference_clicked)
            field.external_reference_clicked.connect(self.external_reference_clicked)
        elif isinstance(value, list):
            # Expandable array field
            field = ArrayFieldWidget(
                value, self._prop.name, is_modified, old_value,
                self._document, self._guid_resolver
            )
            field.reference_clicked.connect(self.reference_clicked)
            field.external_reference_clicked.connect(self.external_reference_clicked)
        elif isinstance(value, dict):
            # Expandable dict field (non-vector/color/reference dicts)
            field = DictFieldWidget(
                value, self._prop.name, is_modified, old_value,
                self._document, self._guid_resolver
            )
            field.reference_clicked.connect(self.reference_clicked)
            field.external_reference_clicked.connect(self.external_reference_clicked)
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
        return str(value)[:60]


class ComponentWidget(QFrame):
    """
    A collapsible component section similar to Unity's Inspector.

    Shows component header with expand/collapse button and property list.
    Supports Normal mode (Unity Inspector style) and Debug mode (all properties).

    Uses lazy loading: property widgets are only created when the component
    is expanded for the first time, improving initial display performance.
    """

    # Signals for reference navigation
    reference_clicked = Signal(str, str)  # file_id, guid
    external_reference_clicked = Signal(str)  # guid

    def __init__(
        self,
        component: UnityComponent,
        other_component: Optional[UnityComponent] = None,
        debug_mode: bool = False,
        document: Optional[Any] = None,  # UnityDocument for resolving refs
        guid_resolver: Optional[GuidResolver] = None,
        parent: Optional[QWidget] = None,
        start_expanded: bool = True,
    ):
        super().__init__(parent)
        self._component = component
        self._other_component = other_component
        self._debug_mode = debug_mode
        self._document = document
        self._guid_resolver = guid_resolver
        self._is_expanded = start_expanded
        self._properties_populated = False  # Lazy loading flag
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

        # Lazy loading: only populate if starting expanded
        if self._is_expanded:
            self._populate_properties()
            self._properties_container.setVisible(True)
        else:
            self._properties_container.setVisible(False)

        layout.addWidget(self._properties_container)

    def _create_header(self) -> QWidget:
        """Create the component header with icon, name, and expand button."""
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(8)

        # Expand/collapse button - reflect actual state
        self._expand_btn = QToolButton()
        self._expand_btn.setArrowType(
            Qt.ArrowType.DownArrow if self._is_expanded else Qt.ArrowType.RightArrow
        )
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
            self._component.type_name,
            self._component.script_name,
            self._component.script_guid,
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
        """Populate the properties list based on Normal/Debug mode (lazy loaded)."""
        self._properties_populated = True

        other_props = {}
        if self._other_component:
            other_props = {p.path: p for p in self._other_component.properties}

        # Get constrain proportions value for Scale field (Transform only)
        constrain_proportions = False
        if self._component.type_name in ("Transform", "RectTransform"):
            for p in self._component.properties:
                if p.name == "m_ConstrainProportionsScale":
                    constrain_proportions = bool(p.value)
                    break

        # Filter properties based on mode and component type
        visible_props = self._get_visible_properties()

        # For Transform, use special layout (no grouping, Unity Inspector style)
        if self._component.type_name in ("Transform", "RectTransform") and not self._debug_mode:
            self._populate_transform_properties(visible_props, other_props, constrain_proportions)
        else:
            # Standard property layout with grouping
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

                    row = PropertyRowWidget(
                        prop, other_value,
                        document=self._document,
                        guid_resolver=self._guid_resolver,
                    )
                    # Forward reference signals to ComponentWidget
                    row.reference_clicked.connect(self.reference_clicked)
                    row.external_reference_clicked.connect(self.external_reference_clicked)
                    self._properties_layout.addWidget(row)
                    self._property_widgets.append(row)

    def _get_visible_properties(self) -> list[UnityProperty]:
        """Get list of visible properties based on mode and component type."""
        if self._debug_mode:
            # Debug mode: show almost everything
            return [
                p for p in self._component.properties
                if p.name not in SKIP_PROPERTIES_DEBUG
            ]

        # Normal mode
        is_transform = self._component.type_name in ("Transform", "RectTransform")

        if is_transform:
            # Transform: only show Position, Rotation, Scale
            allowed = TRANSFORM_DISPLAY_PROPERTIES.copy()
            if self._component.type_name == "RectTransform":
                allowed.update(RECT_TRANSFORM_DISPLAY_PROPERTIES)

            return [
                p for p in self._component.properties
                if p.name in allowed
            ]
        else:
            # Other components: filter out internal properties
            return [
                p for p in self._component.properties
                if p.name not in SKIP_PROPERTIES_NORMAL
            ]

    def _populate_transform_properties(
        self,
        props: list[UnityProperty],
        other_props: dict,
        constrain_proportions: bool,
    ) -> None:
        """Populate Transform properties in Unity Inspector style."""
        # Define property order (use EulerAnglesHint for Rotation like Unity Inspector)
        order = ["m_LocalPosition", "m_LocalEulerAnglesHint", "m_LocalScale"]
        display_names = {
            "m_LocalPosition": "Position",
            "m_LocalEulerAnglesHint": "Rotation",
            "m_LocalScale": "Scale",
            "m_AnchoredPosition": "Anchored Position",
            "m_SizeDelta": "Size Delta",
            "m_Pivot": "Pivot",
            "m_AnchorMin": "Anchor Min",
            "m_AnchorMax": "Anchor Max",
        }

        # Add RectTransform properties
        if self._component.type_name == "RectTransform":
            order = ["m_AnchoredPosition", "m_SizeDelta", "m_AnchorMin", "m_AnchorMax", "m_Pivot",
                     "m_LocalPosition", "m_LocalEulerAnglesHint", "m_LocalScale"]

        props_by_name = {p.name: p for p in props}

        for prop_name in order:
            prop = props_by_name.get(prop_name)
            if not prop:
                continue

            # Create row
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(16, 2, 8, 2)
            row_layout.setSpacing(8)

            # Property label
            label_text = display_names.get(prop_name, nicify_variable_name(prop_name))
            name_label = QLabel(label_text)
            name_label.setFixedWidth(130)
            name_label.setStyleSheet("color: #b0b0b0; font-size: 11px;")
            row_layout.addWidget(name_label)

            # Get diff info
            is_modified = prop.diff_status == DiffStatus.MODIFIED
            old_value = prop.old_value if is_modified else None
            value = prop.value

            # Create appropriate field widget
            if prop_name == "m_LocalScale" and _is_vector_like(value):
                # Use ScaleFieldWidget with chain button
                field = ScaleFieldWidget(value, constrain_proportions, is_modified, old_value)
            elif _is_vector_like(value):
                field = VectorFieldWidget(value, is_modified, old_value)
            else:
                value_str = str(value)
                old_str = str(old_value) if old_value else None
                field = FieldWidget("", value_str, is_modified, old_str)

            row_layout.addWidget(field, 1)

            self._properties_layout.addWidget(row_widget)
            self._property_widgets.append(row_widget)

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
        """Toggle expanded/collapsed state with lazy property loading."""
        self._is_expanded = not self._is_expanded

        # Lazy loading: populate properties on first expand
        if self._is_expanded and not self._properties_populated:
            self._populate_properties()

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
    Supports Normal and Debug modes like Unity's Inspector.
    """

    property_selected = Signal(str)  # Emitted when a property is clicked
    reference_clicked = Signal(str, str)  # file_id, guid - for internal navigation
    external_reference_clicked = Signal(str)  # guid - for external asset navigation

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._game_object: Optional[UnityGameObject] = None
        self._other_object: Optional[UnityGameObject] = None  # For comparison
        self._document: Optional[Any] = None  # UnityDocument for resolving references
        self._guid_resolver: Optional[GuidResolver] = None
        self._component_widgets: list[ComponentWidget] = []
        self._component_widget_index: dict[str, ComponentWidget] = {}  # O(1) lookup cache
        self._debug_mode = False  # Normal mode by default
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

        # Main container
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Mode selector header
        self._mode_header = self._create_mode_header()
        main_layout.addWidget(self._mode_header)

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

        main_layout.addWidget(self._content, 1)
        self.setWidget(main_widget)

    def _create_mode_header(self) -> QWidget:
        """Create the mode selector header (Normal/Debug toggle)."""
        header = QWidget()
        header.setStyleSheet("background-color: #353535; border-bottom: 1px solid #444;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(4)

        header_layout.addStretch()

        # Mode button with dropdown menu
        self._mode_btn = QToolButton()
        self._mode_btn.setText("Normal")
        self._mode_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._mode_btn.setStyleSheet(
            "QToolButton { color: #aaa; font-size: 11px; padding: 2px 8px; border: none; } "
            "QToolButton:hover { background-color: #444; } "
            "QToolButton::menu-indicator { image: none; }"
        )

        # Create mode menu
        mode_menu = QMenu(self._mode_btn)
        mode_menu.setStyleSheet(
            "QMenu { background-color: #3c3c3c; color: #ddd; border: 1px solid #555; } "
            "QMenu::item:selected { background-color: #505050; }"
        )

        normal_action = mode_menu.addAction("Normal")
        normal_action.setCheckable(True)
        normal_action.setChecked(True)
        normal_action.triggered.connect(lambda: self._set_mode(False))

        debug_action = mode_menu.addAction("Debug")
        debug_action.setCheckable(True)
        debug_action.triggered.connect(lambda: self._set_mode(True))

        self._normal_action = normal_action
        self._debug_action = debug_action
        self._mode_btn.setMenu(mode_menu)

        header_layout.addWidget(self._mode_btn)

        return header

    def _set_mode(self, debug: bool) -> None:
        """Set inspector mode (Normal or Debug)."""
        if self._debug_mode == debug:
            return

        self._debug_mode = debug
        self._mode_btn.setText("Debug" if debug else "Normal")
        self._normal_action.setChecked(not debug)
        self._debug_action.setChecked(debug)
        self._refresh()

    def set_document(self, document: Optional[Any]) -> None:
        """Set the Unity document for resolving references."""
        self._document = document
        # Setup GUID resolver if project root is available
        if document and hasattr(document, "project_root") and document.project_root:
            from pathlib import Path

            self._guid_resolver = GuidResolver()
            self._guid_resolver.set_project_root(Path(document.project_root))

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
            widget = ComponentWidget(
                component,
                other_component,
                debug_mode=self._debug_mode,
                document=self._document,
                guid_resolver=self._guid_resolver,
            )
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

        # Add component widgets - all start expanded by default
        for component in self._game_object.components:
            other_comp = other_components.get(component.file_id)

            widget = ComponentWidget(
                component,
                other_comp,
                debug_mode=self._debug_mode,
                document=self._document,
                guid_resolver=self._guid_resolver,
                start_expanded=True,  # Always start expanded
            )
            # Forward reference signals to InspectorWidget
            widget.reference_clicked.connect(self.reference_clicked)
            widget.external_reference_clicked.connect(self.external_reference_clicked)
            self._content_layout.addWidget(widget)
            self._component_widgets.append(widget)
            # Cache for O(1) lookup
            self._component_widget_index[component.file_id] = widget

        # Add stretch at the end
        self._content_layout.addStretch()

    def _clear(self) -> None:
        """Clear all widgets."""
        self._component_widgets.clear()
        self._component_widget_index.clear()

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

    def scroll_to_component(self, component_file_id: str) -> bool:
        """
        Scroll to a specific component by its file_id. O(1) lookup using cache.

        Args:
            component_file_id: The file_id of the component to scroll to

        Returns:
            True if the component was found and scrolled to
        """
        # O(1) lookup using cache
        widget = self._component_widget_index.get(component_file_id)
        if widget:
            # Expand the component if collapsed
            if not widget._is_expanded:
                widget._toggle_expand()
            # Process pending events to ensure layout is updated
            # This is necessary because ensureWidgetVisible needs
            # accurate widget geometry which isn't available until
            # the layout system has processed all pending updates
            QApplication.processEvents()
            # Scroll to make the component visible
            self.ensureWidgetVisible(widget)
            return True
        return False
