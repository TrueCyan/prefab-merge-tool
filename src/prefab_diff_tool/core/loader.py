"""
Unity file loader using unityflow.

Converts Unity YAML files to our internal UnityDocument model.
"""

import logging
import re
from pathlib import Path
from typing import Any, Optional

from unityflow import UnityYAMLDocument

from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
    UnityProperty,
)
from prefab_diff_tool.utils.guid_resolver import GuidResolver

# Set up logging
logger = logging.getLogger(__name__)


# Additional Unity class IDs not in unityflow's mapping
# Reference: https://docs.unity3d.com/Manual/ClassIDReference.html
ADDITIONAL_CLASS_IDS = {
    50: "Rigidbody2D",
    55: "PhysicsManager",
    57: "Joint2D",
    58: "HingeJoint2D",
    59: "SpringJoint2D",
    60: "DistanceJoint2D",
    61: "SliderJoint2D",
    62: "RelativeJoint2D",
    64: "FixedJoint2D",
    65: "FrictionJoint2D",
    66: "TargetJoint2D",
    68: "WheelJoint2D",
    70: "CompositeCollider2D",
    71: "EdgeCollider2D",
    72: "CapsuleCollider2D",
    119: "LightProbes",
    127: "LevelGameManager",
    129: "LandscapeProxy",
    131: "UnityAnalyticsManager",
    150: "PreloadData",
    156: "TerrainData",
    157: "LightmapSettings",
    171: "SampleClip",
    194: "TerrainData",
    218: "Terrain",
    226: "BillboardAsset",
    238: "NavMeshData",
    290: "StreamingController",
    319: "AvatarMask",
    320: "PlayableDirector",
    328: "VideoPlayer",
    329: "VideoClip",
    331: "SpriteMask",
    362: "SpriteShapeRenderer",
    363: "OcclusionCullingData",
    387: "TilemapRenderer",
    483: "Tilemap",
    1101: "PrefabInstance",
    1102: "PrefabModification",
}

# Pattern to match "Unknown(ID)" format
UNKNOWN_PATTERN = re.compile(r"Unknown\((\d+)\)")


def resolve_class_name(class_name: str) -> str:
    """Resolve class name, handling Unknown(ID) format."""
    match = UNKNOWN_PATTERN.match(class_name)
    if match:
        class_id = int(match.group(1))
        return ADDITIONAL_CLASS_IDS.get(class_id, class_name)
    return class_name


class UnityFileLoader:
    """Loads Unity YAML files and converts to UnityDocument model."""

    # Component type names that are skipped for hierarchy building
    # Note: PrefabInstance is now handled specially for nested prefab support
    SKIP_TYPES = frozenset({"Prefab"})

    def __init__(self):
        self._raw_doc: Optional[UnityYAMLDocument] = None
        self._entries_by_id: dict[str, Any] = {}
        self._guid_resolver = GuidResolver()
        # Maps for PrefabInstance handling
        self._prefab_instances: dict[str, Any] = {}  # fileID -> PrefabInstance entry
        self._stripped_transforms: dict[str, str] = {}  # Transform fileID -> PrefabInstance fileID
        # Track loading prefabs to prevent circular references
        self._loading_prefabs: set[str] = set()
        # Project root for nested prefab loading
        self._project_root: Optional[Path] = None

    def _get_entry_data(self, entry: Any) -> dict:
        """Get the data dictionary from a UnityYAMLObject."""
        if hasattr(entry, "get_content"):
            return entry.get_content() or {}
        if hasattr(entry, "data"):
            # data is like {"GameObject": {...}} - get the inner dict
            data = entry.data or {}
            if data and len(data) == 1:
                return next(iter(data.values()), {})
            return data
        return {}

    def load(
        self,
        file_path: Path,
        unity_root: Optional[Path] = None,
        load_nested: bool = True,
    ) -> UnityDocument:
        """
        Load a Unity YAML file and convert to UnityDocument.

        Args:
            file_path: Path to the Unity file (.prefab, .unity, .asset, etc.)
            unity_root: Optional Unity project root for GUID resolution
            load_nested: If True, load contents of nested prefabs (default True)

        Returns:
            UnityDocument with parsed hierarchy
        """
        file_path_str = str(file_path)

        # Prevent circular reference
        if file_path_str in self._loading_prefabs:
            logger.warning(f"Circular reference detected, skipping: {file_path_str}")
            return UnityDocument(file_path=file_path_str)

        self._loading_prefabs.add(file_path_str)

        try:
            return self._load_internal(file_path, unity_root, load_nested)
        finally:
            self._loading_prefabs.discard(file_path_str)

    def _load_internal(
        self,
        file_path: Path,
        unity_root: Optional[Path],
        load_nested: bool,
    ) -> UnityDocument:
        """Internal load implementation."""
        self._raw_doc = UnityYAMLDocument.load(str(file_path))
        self._entries_by_id = {}

        # Find Unity project root and setup GUID resolver
        # Priority: provided unity_root > auto-detect (non-temp only)
        file_path_obj = Path(file_path) if isinstance(file_path, str) else file_path
        project_root = None

        # Use provided unity_root first (reliable)
        if unity_root:
            project_root = unity_root
            logger.info(f"Using provided unity_root: {project_root}")
        else:
            # Try auto-detection (may find temp directory - will be validated later)
            project_root = GuidResolver.find_project_root(file_path_obj)
            if project_root:
                logger.debug(f"Auto-detected project root: {project_root}")

        if project_root:
            logger.info(f"Setting up GUID resolver for project: {project_root}")
            self._guid_resolver.set_project_root(project_root)
            self._project_root = project_root
        else:
            logger.warning(f"Could not find project root for: {file_path_obj}")
            self._project_root = None

        # Index all entries by their file_id
        for entry in self._raw_doc.objects:
            file_id = getattr(entry, "file_id", None)
            if file_id:
                self._entries_by_id[str(file_id)] = entry

        # Create document
        doc = UnityDocument(file_path=str(file_path))
        doc.project_root = str(project_root) if project_root else None

        # Reset PrefabInstance tracking
        self._prefab_instances.clear()
        self._stripped_transforms.clear()

        # Extract all GameObjects and Components
        game_objects: dict[str, UnityGameObject] = {}
        components: dict[str, UnityComponent] = {}

        # First pass: collect PrefabInstances and stripped objects
        for entry in self._raw_doc.objects:
            file_id = str(getattr(entry, "file_id", ""))
            raw_class_name = getattr(entry, "class_name", "Unknown")
            class_name = resolve_class_name(raw_class_name)
            is_stripped = getattr(entry, "stripped", False)

            # Collect PrefabInstance entries
            if class_name == "PrefabInstance":
                self._prefab_instances[file_id] = entry

            # Collect stripped Transform references
            if is_stripped and class_name in ("Transform", "RectTransform"):
                data = self._get_entry_data(entry)
                prefab_ref = data.get("m_PrefabInstance")
                if prefab_ref and isinstance(prefab_ref, dict):
                    prefab_id = str(prefab_ref.get("fileID", ""))
                    if prefab_id:
                        self._stripped_transforms[file_id] = prefab_id

        # Second pass: parse GameObjects and Components
        for entry in self._raw_doc.objects:
            file_id = str(getattr(entry, "file_id", ""))
            raw_class_name = getattr(entry, "class_name", "Unknown")
            # Resolve Unknown(ID) patterns to actual class names
            class_name = resolve_class_name(raw_class_name)

            if class_name == "GameObject":
                go = self._parse_game_object(entry, file_id)
                game_objects[file_id] = go
                doc.all_objects[file_id] = go

            elif class_name == "PrefabInstance":
                # Create virtual GameObject for nested prefab
                virtual_go = self._parse_prefab_instance(entry, file_id, load_nested)
                if virtual_go:
                    game_objects[file_id] = virtual_go
                    doc.all_objects[file_id] = virtual_go

            elif class_name not in self.SKIP_TYPES:
                comp = self._parse_component(entry, file_id, class_name)
                components[file_id] = comp
                doc.all_components[file_id] = comp

        # Build hierarchy relationships
        self._build_hierarchy(game_objects, components)

        # Find root objects (those without parents)
        for go in game_objects.values():
            if go.parent is None:
                doc.root_objects.append(go)

        # Sort root objects by name for consistent ordering
        doc.root_objects.sort(key=lambda x: x.name)

        return doc

    def _parse_game_object(self, entry: Any, file_id: str) -> UnityGameObject:
        """Parse a GameObject entry."""
        data = self._get_entry_data(entry)
        name = data.get("m_Name", "Unnamed")
        layer = data.get("m_Layer", 0)
        tag = data.get("m_TagString", "Untagged")
        is_active = bool(data.get("m_IsActive", 1))

        return UnityGameObject(
            file_id=file_id,
            name=name,
            layer=layer,
            tag=tag,
            is_active=is_active,
        )

    def _parse_prefab_instance(
        self, entry: Any, file_id: str, load_nested: bool = True
    ) -> Optional[UnityGameObject]:
        """Parse a PrefabInstance entry and create a virtual GameObject.

        Args:
            entry: The raw PrefabInstance entry
            file_id: The fileID of this PrefabInstance
            load_nested: If True, load the source prefab's contents as children
        """
        data = self._get_entry_data(entry)

        # Get source prefab reference
        source_ref = data.get("m_SourcePrefab")
        source_guid = None
        if source_ref and isinstance(source_ref, dict):
            source_guid = source_ref.get("guid")

        # Try to resolve prefab name from GUID
        prefab_name = None
        if source_guid:
            prefab_name = self._guid_resolver.resolve(source_guid)

        # Fallback name if resolution fails
        if not prefab_name:
            prefab_name = f"PrefabInstance ({file_id[:8]}...)"

        # Create virtual GameObject representing the nested prefab
        virtual_go = UnityGameObject(
            file_id=file_id,
            name=prefab_name,
            is_prefab_instance=True,
            source_prefab_guid=source_guid,
            prefab_instance_id=file_id,
        )

        logger.debug(f"Created virtual GO for PrefabInstance: {prefab_name} (fileID={file_id})")

        # Load source prefab contents if requested
        if load_nested and source_guid and self._project_root:
            self._load_nested_prefab_contents(virtual_go, source_guid)

        return virtual_go

    def _load_nested_prefab_contents(
        self, virtual_go: UnityGameObject, source_guid: str
    ) -> None:
        """Load the contents of a nested prefab and add as children.

        Args:
            virtual_go: The virtual GameObject representing the PrefabInstance
            source_guid: GUID of the source prefab to load
        """
        # Resolve GUID to file path
        source_path = self._guid_resolver.resolve_path(source_guid)
        if not source_path:
            logger.debug(f"Could not resolve path for prefab GUID: {source_guid[:8]}...")
            return

        # Make path absolute if needed
        if not source_path.is_absolute() and self._project_root:
            source_path = self._project_root / source_path

        if not source_path.exists():
            logger.debug(f"Source prefab not found: {source_path}")
            return

        logger.debug(f"Loading nested prefab contents: {source_path}")

        try:
            # Load the source prefab (with nested loading to get full hierarchy)
            nested_doc = self.load(source_path, self._project_root, load_nested=True)

            # Add the source prefab's root objects as children of this PrefabInstance
            for root_obj in nested_doc.root_objects:
                # Clone the hierarchy to avoid shared references
                cloned = self._clone_game_object(root_obj, virtual_go)
                virtual_go.children.append(cloned)

            logger.debug(
                f"Loaded {len(nested_doc.root_objects)} root objects from {virtual_go.name}"
            )
        except Exception as e:
            logger.warning(f"Failed to load nested prefab {source_path}: {e}")

    def _clone_game_object(
        self, source: UnityGameObject, new_parent: Optional[UnityGameObject]
    ) -> UnityGameObject:
        """Create a shallow clone of a GameObject with updated parent reference.

        Args:
            source: The GameObject to clone
            new_parent: The new parent for the cloned object

        Returns:
            Cloned GameObject with updated parent and cloned children
        """
        cloned = UnityGameObject(
            file_id=f"{new_parent.file_id}_{source.file_id}" if new_parent else source.file_id,
            name=source.name,
            components=source.components,  # Share components (read-only display)
            children=[],  # Will be populated below
            parent=new_parent,
            diff_status=source.diff_status,
            layer=source.layer,
            tag=source.tag,
            is_active=source.is_active,
            is_prefab_instance=source.is_prefab_instance,
            source_prefab_guid=source.source_prefab_guid,
            prefab_instance_id=source.prefab_instance_id,
        )

        # Recursively clone children
        for child in source.children:
            cloned_child = self._clone_game_object(child, cloned)
            cloned.children.append(cloned_child)

        return cloned

    def _parse_component(
        self, entry: Any, file_id: str, class_name: str
    ) -> UnityComponent:
        """Parse a component entry."""
        comp = UnityComponent(
            file_id=file_id,
            type_name=class_name,
        )

        data = self._get_entry_data(entry)

        # Handle MonoBehaviour special case
        if class_name == "MonoBehaviour":
            script_ref = data.get("m_Script")
            if script_ref:
                comp.script_guid = self._extract_guid(script_ref)
                logger.debug(f"MonoBehaviour script_ref: {script_ref}, extracted GUID: {comp.script_guid}")
                # Try to get script name from data first, then resolve from GUID
                comp.script_name = self._guess_script_name(data)
                if not comp.script_name and comp.script_guid:
                    comp.script_name = self._guid_resolver.resolve(comp.script_guid)
                    if comp.script_name:
                        logger.debug(f"Resolved script GUID {comp.script_guid[:8]}... -> {comp.script_name}")
                    else:
                        logger.warning(f"Failed to resolve script GUID: {comp.script_guid}")

        # Extract all properties
        comp.properties = self._extract_properties(data)

        return comp

    def _extract_properties(
        self, data: dict, prefix: str = ""
    ) -> list[UnityProperty]:
        """Recursively extract all properties from a data dictionary."""
        properties = []

        if not isinstance(data, dict):
            return properties

        for key, value in data.items():
            path = f"{prefix}{key}" if prefix else key
            prop = self._create_property(key, value, path)
            if prop:
                properties.append(prop)

        return properties

    def _create_property(
        self, name: str, value: Any, path: str
    ) -> Optional[UnityProperty]:
        """Create a UnityProperty from a value."""
        # Handle different value types
        if isinstance(value, (str, int, float, bool, type(None))):
            return UnityProperty(name=name, value=value, path=path)

        elif isinstance(value, dict):
            # Keep dict as-is (including references with fileID)
            # inspector_widget.py will handle formatting for display
            return UnityProperty(name=name, value=value, path=path)

        elif isinstance(value, list):
            return UnityProperty(name=name, value=value, path=path)

        else:
            # Complex object - try to get a reasonable representation
            return UnityProperty(name=name, value=str(value), path=path)

    def _extract_guid(self, script_ref: Any) -> Optional[str]:
        """Extract GUID from a script reference."""
        if isinstance(script_ref, dict):
            return script_ref.get("guid")
        return None

    def _guess_script_name(self, data: dict) -> Optional[str]:
        """Try to guess the script name from entry data."""
        # Some common patterns for script identification
        for attr in ["m_Name", "m_ClassName", "m_ScriptName"]:
            name = data.get(attr)
            if name and isinstance(name, str):
                return name
        return None

    def _build_hierarchy(
        self,
        game_objects: dict[str, UnityGameObject],
        components: dict[str, UnityComponent],
    ) -> None:
        """Build parent-child relationships and attach components."""
        # First pass: attach components to GameObjects
        for comp_id, comp in components.items():
            entry = self._entries_by_id.get(comp_id)
            if not entry:
                continue

            # Find the GameObject this component belongs to
            data = self._get_entry_data(entry)
            go_ref = data.get("m_GameObject")
            if go_ref and isinstance(go_ref, dict):
                go_id = str(go_ref.get("fileID", ""))
                if go_id in game_objects:
                    game_objects[go_id].components.append(comp)

        # Build Transform ID -> GameObject index for O(1) lookup
        # This avoids O(n²) complexity when building hierarchy
        transform_to_go: dict[str, UnityGameObject] = {}
        for go in game_objects.values():
            transform = go.get_transform()
            if transform:
                transform_to_go[transform.file_id] = go

        # Add stripped Transform -> PrefabInstance (virtual GO) mappings
        # This allows objects added to nested prefabs to find their parent
        for stripped_transform_id, prefab_instance_id in self._stripped_transforms.items():
            if prefab_instance_id in game_objects:
                virtual_go = game_objects[prefab_instance_id]
                transform_to_go[stripped_transform_id] = virtual_go
                logger.debug(
                    f"Mapped stripped Transform {stripped_transform_id} -> "
                    f"PrefabInstance {virtual_go.name}"
                )

        # Second pass: build hierarchy for PrefabInstances using m_TransformParent
        for prefab_id, prefab_entry in self._prefab_instances.items():
            if prefab_id not in game_objects:
                continue

            virtual_go = game_objects[prefab_id]
            data = self._get_entry_data(prefab_entry)

            # Get modification data which contains m_TransformParent
            modification = data.get("m_Modification", {})
            parent_ref = modification.get("m_TransformParent")
            if parent_ref and isinstance(parent_ref, dict):
                parent_transform_id = str(parent_ref.get("fileID", ""))
                if parent_transform_id and parent_transform_id != "0":
                    parent_go = transform_to_go.get(parent_transform_id)
                    if parent_go and virtual_go not in parent_go.children:
                        virtual_go.parent = parent_go
                        parent_go.children.append(virtual_go)
                        logger.debug(
                            f"PrefabInstance {virtual_go.name} -> parent {parent_go.name}"
                        )

        # Third pass: build Transform hierarchy using m_Father for regular GameObjects
        # (Using m_Father is sufficient and avoids duplicate children)
        for go_id, go in game_objects.items():
            # Skip PrefabInstances - they use m_TransformParent instead
            if go.is_prefab_instance:
                continue

            transform = go.get_transform()
            if not transform:
                continue

            # Find transform entry in raw data
            transform_entry = self._entries_by_id.get(transform.file_id)
            if not transform_entry:
                continue

            transform_data = self._get_entry_data(transform_entry)

            # Get parent transform via m_Father
            father_ref = transform_data.get("m_Father")
            if father_ref and isinstance(father_ref, dict):
                father_id = str(father_ref.get("fileID", ""))
                if father_id and father_id != "0":
                    # O(1) lookup using index instead of O(n) search
                    parent_go = transform_to_go.get(father_id)
                    if parent_go and go not in parent_go.children:
                        go.parent = parent_go
                        parent_go.children.append(go)

        # Sort children by m_Children order (Unity's actual hierarchy order)
        self._sort_children_by_transform_order(game_objects, transform_to_go)

    def _sort_children_by_transform_order(
        self,
        game_objects: dict[str, UnityGameObject],
        transform_to_go: dict[str, UnityGameObject],
    ) -> None:
        """Sort children according to Transform's m_Children order."""
        for go in game_objects.values():
            if not go.children:
                continue

            # Get Transform's m_Children order
            transform = go.get_transform()
            if not transform:
                # For PrefabInstances without transform, keep current order
                continue

            transform_entry = self._entries_by_id.get(transform.file_id)
            if not transform_entry:
                continue

            transform_data = self._get_entry_data(transform_entry)
            m_children = transform_data.get("m_Children", [])

            if not m_children:
                # No m_Children info, fall back to name sorting
                go.children.sort(key=lambda x: x.name)
                continue

            # Build order map: transform_id -> index
            child_order: dict[str, int] = {}
            for idx, child_ref in enumerate(m_children):
                if isinstance(child_ref, dict):
                    child_transform_id = str(child_ref.get("fileID", ""))
                    if child_transform_id:
                        child_order[child_transform_id] = idx

            # Sort children by their transform's position in m_Children
            def get_sort_key(child_go: UnityGameObject) -> tuple[int, str]:
                # For regular GameObjects, use their transform's fileID
                child_transform = child_go.get_transform()
                if child_transform and child_transform.file_id in child_order:
                    return (child_order[child_transform.file_id], child_go.name)

                # For PrefabInstances, check stripped transforms
                if child_go.is_prefab_instance:
                    # Find stripped transform that maps to this PrefabInstance
                    for stripped_id, prefab_id in self._stripped_transforms.items():
                        if prefab_id == child_go.file_id and stripped_id in child_order:
                            return (child_order[stripped_id], child_go.name)

                # Fallback: put at end, sorted by name
                return (len(m_children), child_go.name)

            go.children.sort(key=get_sort_key)


def load_unity_file(
    file_path: Path,
    unity_root: Optional[Path] = None,
    load_nested: bool = True,
) -> UnityDocument:
    """
    Convenience function to load a Unity file.

    Args:
        file_path: Path to the Unity file
        unity_root: Optional Unity project root for GUID resolution
        load_nested: If True, load contents of nested prefabs (default True)

    Returns:
        UnityDocument with parsed hierarchy
    """
    loader = UnityFileLoader()
    return loader.load(file_path, unity_root=unity_root, load_nested=load_nested)
