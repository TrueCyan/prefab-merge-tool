"""
In-memory logging handler for UI display.

Captures log messages in a circular buffer for display in the log viewer.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional


@dataclass
class LogRecord:
    """A captured log record."""

    timestamp: datetime
    level: str
    logger_name: str
    message: str
    level_no: int

    def format(self, show_timestamp: bool = True, show_logger: bool = True) -> str:
        """Format the record for display."""
        parts = []
        if show_timestamp:
            parts.append(self.timestamp.strftime("%H:%M:%S"))
        parts.append(f"[{self.level}]")
        if show_logger:
            # Shorten logger name (keep last 2 parts)
            name_parts = self.logger_name.split(".")
            short_name = ".".join(name_parts[-2:]) if len(name_parts) > 2 else self.logger_name
            parts.append(short_name)
        parts.append(self.message)
        return " ".join(parts)


class MemoryLogHandler(logging.Handler):
    """
    Logging handler that stores records in memory.

    Uses a circular buffer to limit memory usage.
    Supports callbacks for real-time UI updates.
    """

    _instance: Optional["MemoryLogHandler"] = None

    def __init__(self, max_records: int = 1000):
        super().__init__()
        self._records: deque[LogRecord] = deque(maxlen=max_records)
        self._callbacks: list[Callable[[LogRecord], None]] = []
        self.setLevel(logging.DEBUG)
        self.setFormatter(logging.Formatter("%(message)s"))

    @classmethod
    def get_instance(cls, max_records: int = 1000) -> "MemoryLogHandler":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls(max_records)
        return cls._instance

    def emit(self, record: logging.LogRecord) -> None:
        """Handle a log record."""
        try:
            log_record = LogRecord(
                timestamp=datetime.fromtimestamp(record.created),
                level=record.levelname,
                logger_name=record.name,
                message=self.format(record),
                level_no=record.levelno,
            )
            self._records.append(log_record)

            # Notify callbacks
            for callback in self._callbacks:
                try:
                    callback(log_record)
                except Exception:
                    pass  # Don't let callback errors affect logging

        except Exception:
            self.handleError(record)

    def get_records(
        self,
        min_level: int = logging.DEBUG,
        logger_filter: Optional[str] = None,
    ) -> list[LogRecord]:
        """
        Get stored records with optional filtering.

        Args:
            min_level: Minimum log level to include
            logger_filter: If set, only include loggers containing this string

        Returns:
            List of matching LogRecord objects
        """
        records = []
        for record in self._records:
            if record.level_no < min_level:
                continue
            if logger_filter and logger_filter not in record.logger_name:
                continue
            records.append(record)
        return records

    def add_callback(self, callback: Callable[[LogRecord], None]) -> None:
        """Add a callback to be notified of new log records."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[LogRecord], None]) -> None:
        """Remove a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def clear(self) -> None:
        """Clear all stored records."""
        self._records.clear()


def setup_logging(level: int = logging.INFO) -> MemoryLogHandler:
    """
    Setup logging with the memory handler.

    Args:
        level: Logging level for the root logger

    Returns:
        The MemoryLogHandler instance
    """
    handler = MemoryLogHandler.get_instance()

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing memory handlers to avoid duplicates
    for h in root_logger.handlers[:]:
        if isinstance(h, MemoryLogHandler):
            root_logger.removeHandler(h)

    root_logger.addHandler(handler)

    # Also add console handler for debugging
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    )

    # Check if console handler already exists
    has_console = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, MemoryLogHandler)
        for h in root_logger.handlers
    )
    if not has_console:
        root_logger.addHandler(console_handler)

    return handler
