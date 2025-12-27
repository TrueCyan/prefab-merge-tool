"""
Unity data models for representing prefab/scene structure.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DiffStatus(Enum):
    """Status of an item in diff comparison."""
    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


@dataclass
class UnityProperty:
    """A single property within a component."""
    name: str
    value: Any
    path: str  # Full path like "m_LocalPosition.x"
    diff_status: DiffStatus = DiffStatus.UNCHANGED
    old_value: Optional[Any] = None  # Previous value if modified
    
    def __repr__(self) -> str:
        return f"UnityProperty({self.name}={self.value!r})"


@dataclass
class UnityComponent:
    """A Unity component (Transform, Rigidbody, MonoBehaviour, etc.)."""
    file_id: str
    type_name: str  # "Transform", "MonoBehaviour", etc.
    properties: list[UnityProperty] = field(default_factory=list)
    diff_status: DiffStatus = DiffStatus.UNCHANGED
    script_name: Optional[str] = None  # For MonoBehaviour, the script name
    script_guid: Optional[str] = None  # Script GUID reference
    
    def get_property(self, path: str) -> Optional[UnityProperty]:
        """Get property by path."""
        for prop in self.properties:
            if prop.path == path:
                return prop
        return None
    
    def __repr__(self) -> str:
        name = self.script_name or self.type_name
        return f"UnityComponent({name}, fileID={self.file_id})"


@dataclass
class UnityGameObject:
    """A Unity GameObject with its components and children."""
    file_id: str
    name: str
    components: list[UnityComponent] = field(default_factory=list)
    children: list["UnityGameObject"] = field(default_factory=list)
    parent: Optional["UnityGameObject"] = field(default=None, repr=False)
    diff_status: DiffStatus = DiffStatus.UNCHANGED
    
    # Additional metadata
    layer: int = 0
    tag: str = "Untagged"
    is_active: bool = True
    
    def get_component(self, type_name: str) -> Optional[UnityComponent]:
        """Get first component of given type."""
        for comp in self.components:
            if comp.type_name == type_name:
                return comp
        return None
    
    def get_transform(self) -> Optional[UnityComponent]:
        """Get Transform or RectTransform component."""
        return self.get_component("Transform") or self.get_component("RectTransform")
    
    def get_path(self) -> str:
        """Get full hierarchy path like 'Parent/Child/GrandChild'."""
        parts = [self.name]
        obj = self.parent
        while obj:
            parts.insert(0, obj.name)
            obj = obj.parent
        return "/".join(parts)
    
    def iter_descendants(self):
        """Iterate over all descendants (depth-first)."""
        for child in self.children:
            yield child
            yield from child.iter_descendants()
    
    def __repr__(self) -> str:
        return f"UnityGameObject({self.name!r}, fileID={self.file_id})"


@dataclass
class UnityDocument:
    """Represents an entire Unity file (prefab, scene, asset)."""
    file_path: str
    root_objects: list[UnityGameObject] = field(default_factory=list)
    all_objects: dict[str, UnityGameObject] = field(default_factory=dict)
    all_components: dict[str, UnityComponent] = field(default_factory=dict)

    # Metadata
    unity_version: Optional[str] = None
    project_root: Optional[str] = None  # Unity project root path
    
    def get_object(self, file_id: str) -> Optional[UnityGameObject]:
        """Get GameObject by fileID."""
        return self.all_objects.get(file_id)
    
    def get_component(self, file_id: str) -> Optional[UnityComponent]:
        """Get component by fileID."""
        return self.all_components.get(file_id)
    
    def iter_all_objects(self):
        """Iterate over all GameObjects in the document."""
        for root in self.root_objects:
            yield root
            yield from root.iter_descendants()
    
    @property
    def object_count(self) -> int:
        return len(self.all_objects)
    
    @property
    def component_count(self) -> int:
        return len(self.all_components)
    
    def __repr__(self) -> str:
        return f"UnityDocument({self.file_path!r}, objects={self.object_count})"


# === Diff/Merge related models ===

@dataclass
class Change:
    """Represents a single change between two versions."""
    path: str  # Full path like "Player/Body.Transform.m_LocalPosition.y"
    status: DiffStatus
    left_value: Optional[Any] = None
    right_value: Optional[Any] = None
    object_id: Optional[str] = None
    component_type: Optional[str] = None


@dataclass
class DiffSummary:
    """Summary statistics for a diff."""
    added_objects: int = 0
    removed_objects: int = 0
    modified_objects: int = 0
    added_components: int = 0
    removed_components: int = 0
    modified_properties: int = 0
    
    @property
    def added(self) -> int:
        return self.added_objects + self.added_components
    
    @property
    def removed(self) -> int:
        return self.removed_objects + self.removed_components
    
    @property
    def modified(self) -> int:
        return self.modified_objects + self.modified_properties
    
    @property
    def total(self) -> int:
        return self.added + self.removed + self.modified


@dataclass
class DiffResult:
    """Result of comparing two Unity documents."""
    left: UnityDocument
    right: UnityDocument
    changes: list[Change] = field(default_factory=list)
    summary: DiffSummary = field(default_factory=DiffSummary)


class ConflictResolution(Enum):
    """How a merge conflict was resolved."""
    UNRESOLVED = "unresolved"
    USE_OURS = "ours"
    USE_THEIRS = "theirs"
    USE_MANUAL = "manual"


@dataclass
class MergeConflict:
    """A single merge conflict."""
    path: str
    base_value: Optional[Any] = None
    ours_value: Optional[Any] = None
    theirs_value: Optional[Any] = None
    resolution: ConflictResolution = ConflictResolution.UNRESOLVED
    resolved_value: Optional[Any] = None
    
    @property
    def is_resolved(self) -> bool:
        return self.resolution != ConflictResolution.UNRESOLVED


@dataclass
class MergeResult:
    """Result of a 3-way merge."""
    base: UnityDocument
    ours: UnityDocument
    theirs: UnityDocument
    conflicts: list[MergeConflict] = field(default_factory=list)
    auto_merged: list[Change] = field(default_factory=list)
    
    @property
    def has_conflicts(self) -> bool:
        return any(not c.is_resolved for c in self.conflicts)
    
    @property
    def unresolved_count(self) -> int:
        return sum(1 for c in self.conflicts if not c.is_resolved)
    
    @property
    def resolved_count(self) -> int:
        return sum(1 for c in self.conflicts if c.is_resolved)
