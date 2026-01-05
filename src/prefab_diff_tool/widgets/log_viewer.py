"""
Log viewer dialog for displaying application logs.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont, QTextCharFormat, QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QComboBox,
    QLineEdit,
    QPushButton,
    QLabel,
    QWidget,
    QCheckBox,
)

from prefab_diff_tool.utils.log_handler import MemoryLogHandler, LogRecord


# Log level colors
LEVEL_COLORS = {
    "DEBUG": QColor("#808080"),    # Gray
    "INFO": QColor("#d4d4d4"),     # Light gray (default text)
    "WARNING": QColor("#e0a030"),  # Orange
    "ERROR": QColor("#e04040"),    # Red
    "CRITICAL": QColor("#ff4040"), # Bright red
}


class LogViewerDialog(QDialog):
    """Dialog for viewing application logs."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("로그 뷰어")
        self.setMinimumSize(800, 500)
        self.resize(900, 600)

        # Get the log handler
        self._handler = MemoryLogHandler.get_instance()

        # Setup UI
        self._setup_ui()

        # Load initial records
        self._refresh_logs()

        # Register callback for live updates
        self._handler.add_callback(self._on_new_log)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Filter bar
        filter_bar = self._create_filter_bar()
        layout.addWidget(filter_bar)

        # Log display
        self._log_display = QTextEdit()
        self._log_display.setReadOnly(True)
        self._log_display.setFont(QFont("Consolas", 10))
        self._log_display.setStyleSheet(
            """
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #444;
                border-radius: 4px;
            }
            """
        )
        layout.addWidget(self._log_display, 1)

        # Button bar
        button_bar = self._create_button_bar()
        layout.addWidget(button_bar)

    def _create_filter_bar(self) -> QWidget:
        """Create the filter controls bar."""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Log level filter
        level_label = QLabel("레벨:")
        layout.addWidget(level_label)

        self._level_combo = QComboBox()
        self._level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._level_combo.setCurrentText("DEBUG")
        self._level_combo.currentTextChanged.connect(self._refresh_logs)
        layout.addWidget(self._level_combo)

        # Logger filter
        logger_label = QLabel("로거:")
        layout.addWidget(logger_label)

        self._logger_filter = QLineEdit()
        self._logger_filter.setPlaceholderText("로거 이름 필터 (예: prefab_diff)")
        self._logger_filter.setMinimumWidth(200)
        self._logger_filter.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._logger_filter)

        # Auto-scroll checkbox
        self._auto_scroll = QCheckBox("자동 스크롤")
        self._auto_scroll.setChecked(True)
        layout.addWidget(self._auto_scroll)

        layout.addStretch()

        # Record count
        self._count_label = QLabel("0개 레코드")
        self._count_label.setStyleSheet("color: #888;")
        layout.addWidget(self._count_label)

        return bar

    def _create_button_bar(self) -> QWidget:
        """Create the action buttons bar."""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Clear button
        clear_btn = QPushButton("로그 지우기")
        clear_btn.clicked.connect(self._on_clear)
        layout.addWidget(clear_btn)

        # Refresh button
        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self._refresh_logs)
        layout.addWidget(refresh_btn)

        layout.addStretch()

        # Close button
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        return bar

    def _get_level_number(self, level_name: str) -> int:
        """Convert level name to logging level number."""
        return getattr(logging, level_name, logging.DEBUG)

    @Slot()
    def _refresh_logs(self) -> None:
        """Refresh the log display with current filters."""
        min_level = self._get_level_number(self._level_combo.currentText())
        logger_filter = self._logger_filter.text().strip() or None

        records = self._handler.get_records(
            min_level=min_level,
            logger_filter=logger_filter,
        )

        # Clear and repopulate
        self._log_display.clear()
        cursor = self._log_display.textCursor()

        for record in records:
            self._append_record(record, cursor)

        # Update count
        self._count_label.setText(f"{len(records):,}개 레코드")

        # Scroll to end if auto-scroll is enabled
        if self._auto_scroll.isChecked():
            self._log_display.verticalScrollBar().setValue(
                self._log_display.verticalScrollBar().maximum()
            )

    def _on_filter_changed(self) -> None:
        """Handle filter text change with debouncing."""
        # Use a timer to debounce rapid typing
        if hasattr(self, "_filter_timer"):
            self._filter_timer.stop()
        else:
            self._filter_timer = QTimer()
            self._filter_timer.setSingleShot(True)
            self._filter_timer.timeout.connect(self._refresh_logs)

        self._filter_timer.start(300)  # 300ms delay

    def _on_new_log(self, record: LogRecord) -> None:
        """Handle a new log record (called from logging thread)."""
        # Check if this record passes our filters
        min_level = self._get_level_number(self._level_combo.currentText())
        if record.level_no < min_level:
            return

        logger_filter = self._logger_filter.text().strip()
        if logger_filter and logger_filter not in record.logger_name:
            return

        # Append to display (must be done in GUI thread)
        QTimer.singleShot(0, lambda: self._append_single_record(record))

    def _append_single_record(self, record: LogRecord) -> None:
        """Append a single record to the display."""
        cursor = self._log_display.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._append_record(record, cursor)

        # Update count
        current_count = int(self._count_label.text().replace(",", "").replace("개 레코드", ""))
        self._count_label.setText(f"{current_count + 1:,}개 레코드")

        # Auto-scroll if enabled
        if self._auto_scroll.isChecked():
            self._log_display.verticalScrollBar().setValue(
                self._log_display.verticalScrollBar().maximum()
            )

    def _append_record(self, record: LogRecord, cursor) -> None:
        """Append a formatted record to the text display."""
        # Set color based on level
        fmt = QTextCharFormat()
        color = LEVEL_COLORS.get(record.level, LEVEL_COLORS["INFO"])
        fmt.setForeground(color)

        # Format and insert text
        text = record.format(show_timestamp=True, show_logger=True)
        cursor.insertText(text + "\n", fmt)

    @Slot()
    def _on_clear(self) -> None:
        """Clear all logs."""
        self._handler.clear()
        self._log_display.clear()
        self._count_label.setText("0개 레코드")

    def closeEvent(self, event) -> None:
        """Handle dialog close."""
        # Unregister callback
        self._handler.remove_callback(self._on_new_log)
        super().closeEvent(event)
