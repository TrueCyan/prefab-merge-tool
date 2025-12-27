"""
prefab-diff-tool: Visual diff and merge tool for Unity prefab files.
"""

__version__ = "0.1.4"
__author__ = "TrueCyan"

from prefab_diff_tool.core.unity_model import (
    DiffStatus,
    UnityComponent,
    UnityDocument,
    UnityGameObject,
    UnityProperty,
)

__all__ = [
    "DiffStatus",
    "UnityProperty",
    "UnityComponent",
    "UnityGameObject",
    "UnityDocument",
]
