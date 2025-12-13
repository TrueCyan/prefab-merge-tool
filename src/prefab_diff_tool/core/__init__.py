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
from prefab_diff_tool.core.loader import (
    UnityFileLoader,
    load_unity_file,
)
from prefab_diff_tool.core.writer import (
    MergeResultWriter,
    write_merge_result,
    perform_text_merge,
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
    "UnityFileLoader",
    "load_unity_file",
    "MergeResultWriter",
    "write_merge_result",
    "perform_text_merge",
]
