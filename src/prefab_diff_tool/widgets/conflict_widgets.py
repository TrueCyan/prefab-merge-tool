"""
Conflict resolution widgets for merge view.

Provides UI components for displaying and resolving merge conflicts
at both property and structural (hierarchy) levels.
"""

import logging
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from prefab_diff_tool.core.unity_model import (
    ConflictResolution,
    ConflictType,
    MergeConflict,
)
from prefab_diff_tool.utils.colors import DiffColors

logger = logging.getLogger(__name__)


def _format_value(value: Any, max_length: int = 30) -> str:
    """Format a value for display in conflict UI."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value == int(value):
            return str(int(value))
        return f"{value:.4g}" if isinstance(value, float) else str(value)
    if isinstance(value, dict):
        if "fileID" in value:
            file_id = value.get("fileID", 0)
            if file_id == 0:
                return "None"
            return f"(ID: {file_id})"
        return "{...}"
    if isinstance(value, list):
        return f"[{len(value)} items]"
    s = str(value)
    if len(s) > max_length:
        return s[: max_length - 3] + "..."
    return s


class ConflictResolutionButtonsWidget(QWidget):
    """
    Horizontal button row for selecting conflict resolution.

    Shows [Base] [Ours] [Theirs] buttons with the selected one highlighted.
    """

    resolution_selected = Signal(ConflictResolution)

    def __init__(
        self,
        show_base: bool = True,
        current_resolution: ConflictResolution = ConflictResolution.UNRESOLVED,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._show_base = show_base
        self._current = current_resolution
        self._buttons: dict[ConflictResolution, QPushButton] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if self._show_base:
            self._add_button(layout, "Base", ConflictResolution.USE_BASE, "#666")

        self._add_button(layout, "Ours", ConflictResolution.USE_OURS, "#2d5a2d")
        self._add_button(layout, "Theirs", ConflictResolution.USE_THEIRS, "#5a2d2d")

        layout.addStretch()

    def _add_button(
        self,
        layout: QHBoxLayout,
        text: str,
        resolution: ConflictResolution,
        color: str,
    ) -> None:
        btn = QPushButton(text)
        btn.setFixedHeight(22)
        btn.setMinimumWidth(50)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self._on_click(resolution))
        self._buttons[resolution] = btn
        self._update_button_style(btn, resolution, color)
        layout.addWidget(btn)

    def _update_button_style(
        self, btn: QPushButton, resolution: ConflictResolution, color: str
    ) -> None:
        is_selected = self._current == resolution
        if is_selected:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color}; color: white; "
                f"border: 2px solid #fff; border-radius: 3px; font-size: 11px; "
                f"font-weight: bold; padding: 2px 8px; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: #3c3c3c; color: #aaa; "
                f"border: 1px solid #555; border-radius: 3px; font-size: 11px; "
                f"padding: 2px 8px; }} "
                f"QPushButton:hover {{ background-color: {color}; color: white; }}"
            )

    def _on_click(self, resolution: ConflictResolution) -> None:
        self._current = resolution
        # Update all button styles
        colors = {
            ConflictResolution.USE_BASE: "#666",
            ConflictResolution.USE_OURS: "#2d5a2d",
            ConflictResolution.USE_THEIRS: "#5a2d2d",
        }
        for res, btn in self._buttons.items():
            self._update_button_style(btn, res, colors.get(res, "#666"))
        self.resolution_selected.emit(resolution)

    def set_resolution(self, resolution: ConflictResolution) -> None:
        """Set the current resolution without emitting signal."""
        self._current = resolution
        colors = {
            ConflictResolution.USE_BASE: "#666",
            ConflictResolution.USE_OURS: "#2d5a2d",
            ConflictResolution.USE_THEIRS: "#5a2d2d",
        }
        for res, btn in self._buttons.items():
            self._update_button_style(btn, res, colors.get(res, "#666"))


class PropertyConflictWidget(QFrame):
    """
    Widget for displaying and resolving a property-level conflict.

    Shows the property name, BASE/OURS/THEIRS values, and resolution buttons.
    """

    resolution_changed = Signal(MergeConflict, ConflictResolution)

    def __init__(
        self,
        conflict: MergeConflict,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._conflict = conflict
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self.setStyleSheet(
            "PropertyConflictWidget { "
            "background-color: #4a3030; "
            "border: 1px solid #8b4444; "
            "border-radius: 4px; "
            "margin: 2px 0; "
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Header with conflict icon and property path
        header = QHBoxLayout()
        header.setSpacing(8)

        icon = QLabel("⚠️")
        icon.setStyleSheet("font-size: 14px;")
        header.addWidget(icon)

        prop_label = QLabel(self._conflict.display_name)
        prop_label.setStyleSheet(
            "font-weight: bold; font-size: 11px; color: #ffaa88;"
        )
        header.addWidget(prop_label)
        header.addStretch()

        # Resolution status
        if self._conflict.is_resolved:
            status = QLabel("✓ 해결됨")
            status.setStyleSheet("color: #88ff88; font-size: 10px;")
            header.addWidget(status)

        layout.addLayout(header)

        # Values section
        values_widget = QWidget()
        values_layout = QHBoxLayout(values_widget)
        values_layout.setContentsMargins(0, 4, 0, 4)
        values_layout.setSpacing(8)

        # BASE value
        base_frame = self._create_value_frame(
            "BASE", self._conflict.base_value, "#555"
        )
        values_layout.addWidget(base_frame, 1)

        # OURS value
        ours_frame = self._create_value_frame(
            "OURS", self._conflict.ours_value, "#2d5a2d"
        )
        values_layout.addWidget(ours_frame, 1)

        # THEIRS value
        theirs_frame = self._create_value_frame(
            "THEIRS", self._conflict.theirs_value, "#5a2d2d"
        )
        values_layout.addWidget(theirs_frame, 1)

        layout.addWidget(values_widget)

        # Resolution buttons
        buttons = ConflictResolutionButtonsWidget(
            show_base=True,
            current_resolution=self._conflict.resolution,
        )
        buttons.resolution_selected.connect(self._on_resolution_selected)
        layout.addWidget(buttons)

    def _create_value_frame(
        self, label: str, value: Any, border_color: str
    ) -> QFrame:
        """Create a frame showing a single value (BASE/OURS/THEIRS)."""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background-color: #2a2a2a; "
            f"border: 1px solid {border_color}; border-radius: 3px; }}"
        )

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        # Label
        label_widget = QLabel(label)
        label_widget.setStyleSheet(
            f"color: #888; font-size: 9px; font-weight: bold; border: none;"
        )
        layout.addWidget(label_widget)

        # Value
        value_str = _format_value(value)
        value_widget = QLabel(value_str)
        value_widget.setStyleSheet(
            "color: #ddd; font-size: 11px; border: none;"
        )
        value_widget.setWordWrap(True)
        layout.addWidget(value_widget)

        return frame

    def _on_resolution_selected(self, resolution: ConflictResolution) -> None:
        self._conflict.resolution = resolution
        if resolution == ConflictResolution.USE_BASE:
            self._conflict.resolved_value = self._conflict.base_value
        elif resolution == ConflictResolution.USE_OURS:
            self._conflict.resolved_value = self._conflict.ours_value
        elif resolution == ConflictResolution.USE_THEIRS:
            self._conflict.resolved_value = self._conflict.theirs_value
        self.resolution_changed.emit(self._conflict, resolution)


class StructuralConflictWidget(QFrame):
    """
    Widget for displaying and resolving structural (hierarchy-level) conflicts.

    Used for conflicts like:
    - Object deleted in one branch, modified in another
    - Object deleted in one branch, children added in another
    - Same object added in both branches
    """

    resolution_changed = Signal(MergeConflict, ConflictResolution)

    def __init__(
        self,
        conflict: MergeConflict,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._conflict = conflict
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self.setStyleSheet(
            "StructuralConflictWidget { "
            "background-color: #4a3a30; "
            "border: 2px solid #aa6644; "
            "border-radius: 6px; "
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        header.setSpacing(8)

        icon = QLabel("🔀")
        icon.setStyleSheet("font-size: 18px;")
        header.addWidget(icon)

        title = QLabel("구조 충돌")
        title.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: #ffcc88;"
        )
        header.addWidget(title)
        header.addStretch()

        if self._conflict.is_resolved:
            status = QLabel("✓ 해결됨")
            status.setStyleSheet("color: #88ff88; font-size: 11px;")
            header.addWidget(status)

        layout.addLayout(header)

        # Description based on conflict type
        desc = self._get_conflict_description()
        desc_label = QLabel(desc)
        desc_label.setStyleSheet("color: #ddd; font-size: 11px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Options section
        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(0, 8, 0, 0)
        options_layout.setSpacing(6)

        ours_desc, theirs_desc = self._get_option_descriptions()

        # OURS option
        ours_btn = self._create_option_button(
            "OURS 선택",
            ours_desc,
            ConflictResolution.USE_OURS,
            "#2d5a2d",
        )
        options_layout.addWidget(ours_btn)

        # THEIRS option
        theirs_btn = self._create_option_button(
            "THEIRS 선택",
            theirs_desc,
            ConflictResolution.USE_THEIRS,
            "#5a2d2d",
        )
        options_layout.addWidget(theirs_btn)

        layout.addWidget(options)

    def _get_conflict_description(self) -> str:
        """Get human-readable description of the conflict."""
        ct = self._conflict.conflict_type
        if ct == ConflictType.OBJECT_DELETED_MODIFIED:
            return "이 오브젝트가 한쪽에서는 삭제되고, 다른 쪽에서는 수정되었습니다."
        elif ct == ConflictType.OBJECT_DELETED_CHILDREN:
            return "이 오브젝트가 한쪽에서는 삭제되고, 다른 쪽에서는 자식이 추가되었습니다."
        elif ct == ConflictType.OBJECT_BOTH_ADDED:
            return "같은 오브젝트가 양쪽 브랜치에서 추가되었습니다."
        elif ct == ConflictType.COMPONENT_DELETED_MODIFIED:
            return "이 컴포넌트가 한쪽에서는 삭제되고, 다른 쪽에서는 수정되었습니다."
        return self._conflict.path

    def _get_option_descriptions(self) -> tuple[str, str]:
        """Get descriptions for OURS and THEIRS options."""
        ct = self._conflict.conflict_type
        if ct == ConflictType.OBJECT_DELETED_MODIFIED:
            return ("오브젝트 삭제", "오브젝트 유지 (수정사항 적용)")
        elif ct == ConflictType.OBJECT_DELETED_CHILDREN:
            return ("오브젝트 삭제 (자식도 삭제)", "오브젝트 유지 (자식 포함)")
        elif ct == ConflictType.OBJECT_BOTH_ADDED:
            return ("OURS 버전 사용", "THEIRS 버전 사용")
        elif ct == ConflictType.COMPONENT_DELETED_MODIFIED:
            return ("컴포넌트 삭제", "컴포넌트 유지 (수정사항 적용)")
        return ("OURS 값 사용", "THEIRS 값 사용")

    def _create_option_button(
        self,
        title: str,
        description: str,
        resolution: ConflictResolution,
        color: str,
    ) -> QPushButton:
        """Create an option button with title and description."""
        btn = QPushButton()
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        is_selected = self._conflict.resolution == resolution
        if is_selected:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color}; color: white; "
                f"border: 2px solid #fff; border-radius: 4px; "
                f"text-align: left; padding: 8px 12px; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: #3c3c3c; color: #ccc; "
                f"border: 1px solid #555; border-radius: 4px; "
                f"text-align: left; padding: 8px 12px; }} "
                f"QPushButton:hover {{ background-color: {color}; color: white; "
                f"border: 1px solid {color}; }}"
            )

        # Custom layout for button content
        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            "font-weight: bold; font-size: 11px; background: transparent;"
        )
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        desc_label = QLabel(description)
        desc_label.setStyleSheet(
            "font-size: 10px; color: #aaa; background: transparent;"
        )
        desc_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Set button text to include both (workaround for layout in button)
        btn.setText(f"{title}\n{description}")

        btn.clicked.connect(lambda: self._on_option_selected(resolution))
        return btn

    def _on_option_selected(self, resolution: ConflictResolution) -> None:
        self._conflict.resolution = resolution
        if resolution == ConflictResolution.USE_OURS:
            self._conflict.resolved_value = self._conflict.ours_value
        elif resolution == ConflictResolution.USE_THEIRS:
            self._conflict.resolved_value = self._conflict.theirs_value
        self.resolution_changed.emit(self._conflict, resolution)
        # Refresh UI (recreate widget)
        self._refresh()

    def _refresh(self) -> None:
        """Refresh the widget to reflect resolution state."""
        # Clear and rebuild
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._setup_ui()


class ConflictSummaryWidget(QFrame):
    """
    Summary widget showing conflict count and quick navigation.
    """

    next_conflict_clicked = Signal()
    prev_conflict_clicked = Signal()

    def __init__(
        self,
        total: int = 0,
        resolved: int = 0,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._total = total
        self._resolved = resolved
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            "ConflictSummaryWidget { "
            "background-color: #3a3a3a; "
            "border: 1px solid #555; "
            "border-radius: 4px; "
            "}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # Conflict icon
        icon = QLabel("⚠️")
        icon.setStyleSheet("font-size: 16px;")
        layout.addWidget(icon)

        # Status text
        if self._total == 0:
            text = "충돌 없음"
            color = "#88ff88"
        elif self._resolved == self._total:
            text = f"모든 충돌 해결됨 ({self._total}개)"
            color = "#88ff88"
        else:
            remaining = self._total - self._resolved
            text = f"충돌 {remaining}개 남음 (총 {self._total}개)"
            color = "#ffaa88"

        status = QLabel(text)
        status.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")
        layout.addWidget(status)

        layout.addStretch()

        # Navigation buttons
        if self._total > 0:
            prev_btn = QPushButton("< 이전")
            prev_btn.setStyleSheet(
                "QPushButton { background-color: #444; color: #ccc; "
                "border: 1px solid #555; border-radius: 3px; "
                "padding: 4px 12px; font-size: 11px; } "
                "QPushButton:hover { background-color: #555; }"
            )
            prev_btn.clicked.connect(self.prev_conflict_clicked)
            layout.addWidget(prev_btn)

            next_btn = QPushButton("다음 >")
            next_btn.setStyleSheet(
                "QPushButton { background-color: #444; color: #ccc; "
                "border: 1px solid #555; border-radius: 3px; "
                "padding: 4px 12px; font-size: 11px; } "
                "QPushButton:hover { background-color: #555; }"
            )
            next_btn.clicked.connect(self.next_conflict_clicked)
            layout.addWidget(next_btn)

    def update_counts(self, total: int, resolved: int) -> None:
        """Update the conflict counts."""
        self._total = total
        self._resolved = resolved
        # Rebuild UI
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._setup_ui()
