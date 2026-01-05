"""
Application initialization and main loop.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPalette, QColor
from PySide6.QtWidgets import QApplication

from prefab_diff_tool.widgets.main_window import MainWindow
from prefab_diff_tool.utils.log_handler import setup_logging


def setup_dark_palette(app: QApplication) -> None:
    """Apply dark theme palette."""
    palette = QPalette()
    
    # Base colors
    palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(212, 212, 212))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(212, 212, 212))
    palette.setColor(QPalette.ColorRole.Text, QColor(212, 212, 212))
    palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(212, 212, 212))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    
    # Disabled colors
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(127, 127, 127))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(127, 127, 127))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(127, 127, 127))
    
    app.setPalette(palette)


def run_app(
    mode: str = "empty",
    files: Optional[list[Path]] = None,
    output: Optional[Path] = None,
    unity_root: Optional[Path] = None,
    workspace_root: Optional[Path] = None,
    depot_path: Optional[str] = None,
) -> int:
    """
    Initialize and run the application.

    Args:
        mode: "empty", "view", "diff", or "merge"
        files: List of files to open
        output: Output file for merge mode
        unity_root: Optional Unity project root path (for GUID resolution)
        workspace_root: VCS workspace root (for debugging)
        depot_path: Perforce depot path (for debugging)

    Returns:
        Exit code (0 for success)
    """
    # Setup logging (captures logs for the log viewer)
    setup_logging(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.info("Starting prefab-diff-tool")

    # High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("prefab-diff-tool")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("TrueCyan")
    
    # Apply dark theme
    setup_dark_palette(app)
    app.setStyle("Fusion")
    
    # Create main window
    window = MainWindow(
        unity_root=unity_root,
        workspace_root=workspace_root,
        depot_path=depot_path,
    )

    # Handle mode
    if mode == "diff" and files and len(files) >= 2:
        window.open_diff(files[0], files[1])
    elif mode == "merge" and files and len(files) >= 3 and output:
        window.open_merge(files[0], files[1], files[2], output)
    elif mode == "view" and files:
        window.open_file(files[0])
    
    window.show()
    
    return app.exec()
