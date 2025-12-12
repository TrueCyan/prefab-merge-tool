"""
Color definitions for diff highlighting.
"""

from PySide6.QtGui import QColor


class DiffColors:
    """Colors for diff status highlighting."""
    
    # Background colors (light, for tree items)
    ADDED_BG = QColor(212, 237, 218)       # Light green (#d4edda)
    REMOVED_BG = QColor(248, 215, 218)     # Light red (#f8d7da)
    MODIFIED_BG = QColor(255, 243, 205)    # Light yellow (#fff3cd)
    UNCHANGED_BG = QColor(0, 0, 0, 0)      # Transparent
    
    # Dark theme background colors
    ADDED_BG_DARK = QColor(40, 80, 40)     # Dark green
    REMOVED_BG_DARK = QColor(80, 40, 40)   # Dark red
    MODIFIED_BG_DARK = QColor(80, 70, 30)  # Dark yellow
    UNCHANGED_BG_DARK = QColor(0, 0, 0, 0) # Transparent
    
    # Text/foreground colors (light theme)
    ADDED_FG_LIGHT = QColor(21, 87, 36)    # Dark green (#155724)
    REMOVED_FG_LIGHT = QColor(114, 28, 36) # Dark red (#721c24)
    MODIFIED_FG_LIGHT = QColor(133, 100, 4) # Dark yellow (#856404)

    # Text/foreground colors (dark theme) - brighter for visibility
    ADDED_FG = QColor(100, 220, 120)        # Bright green
    REMOVED_FG = QColor(255, 120, 120)      # Bright red
    MODIFIED_FG = QColor(255, 210, 80)      # Bright yellow
    
    # Accent colors (for icons/badges)
    ADDED_ACCENT = QColor(40, 167, 69)     # Green (#28a745)
    REMOVED_ACCENT = QColor(220, 53, 69)   # Red (#dc3545)
    MODIFIED_ACCENT = QColor(255, 193, 7)  # Yellow (#ffc107)
    
    # Conflict colors
    CONFLICT_BG = QColor(255, 200, 200)    # Light pink
    CONFLICT_BG_DARK = QColor(100, 40, 40) # Dark pink
    CONFLICT_ACCENT = QColor(255, 0, 0)    # Red
    
    @classmethod
    def get_background(cls, status: str, dark_mode: bool = True) -> QColor:
        """Get background color for a diff status."""
        if dark_mode:
            return {
                "added": cls.ADDED_BG_DARK,
                "removed": cls.REMOVED_BG_DARK,
                "modified": cls.MODIFIED_BG_DARK,
                "unchanged": cls.UNCHANGED_BG_DARK,
            }.get(status, cls.UNCHANGED_BG_DARK)
        else:
            return {
                "added": cls.ADDED_BG,
                "removed": cls.REMOVED_BG,
                "modified": cls.MODIFIED_BG,
                "unchanged": cls.UNCHANGED_BG,
            }.get(status, cls.UNCHANGED_BG)
    
    @classmethod
    def get_accent(cls, status: str) -> QColor:
        """Get accent color for a diff status."""
        return {
            "added": cls.ADDED_ACCENT,
            "removed": cls.REMOVED_ACCENT,
            "modified": cls.MODIFIED_ACCENT,
        }.get(status, QColor(128, 128, 128))


# Status symbols/icons
DIFF_SYMBOLS = {
    "added": "+",
    "removed": "−",
    "modified": "●",
    "unchanged": "",
}
