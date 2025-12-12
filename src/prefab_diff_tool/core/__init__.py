"""Core logic for diff and merge operations."""

from prefab_diff_tool.core.unity_model import (
    Change,
    ConflictResolution,
    DiffResult,
    DiffStatus,
    DiffSummary,
    MergeConflict,
    MergeResult,
    UnityComponent,
    UnityDocument,
    UnityGameObject,
    UnityProperty,
)

__all__ = [
    "Change",
    "ConflictResolution",
    "DiffResult",
    "DiffStatus",
    "DiffSummary",
    "MergeConflict",
    "MergeResult",
    "UnityComponent",
    "UnityDocument",
    "UnityGameObject",
    "UnityProperty",
]
