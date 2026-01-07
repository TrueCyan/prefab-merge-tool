"""
Unity file loader using unityflow.

Converts Unity YAML files to our internal UnityDocument model.
Uses unityflow's build_hierarchy() for hierarchy parsing, including
nested prefab loading and script name resolution.
"""

import logging
import re
from pathlib import Path
from typing import Any, Optional

from unityflow import (
    UnityYAMLDocument,
    build_hierarchy,
    HierarchyNode,
    ComponentInfo,
    get_cached_guid_index,
    find_unity_project_root,
    GUIDIndex,
    get_prefab_instance_for_stripped,
)

from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
    UnityProperty,
)

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
    """Loads Unity YAML files and converts to UnityDocument model.

    Uses unityflow's build_hierarchy() for parsing hierarchy structure,
    including nested prefab loading and script name resolution.
    """

    def __init__(self):
        self._raw_doc: Optional[UnityYAMLDocument] = None
        self._guid_index: Optional[GUIDIndex] = None
        self._project_root: Optional[Path] = None

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
        self._raw_doc = UnityYAMLDocument.load(str(file_path))

        # Find Unity project root
        file_path_obj = Path(file_path) if isinstance(file_path, str) else file_path
        project_root = unity_root or find_unity_project_root(file_path_obj)

        if project_root:
            logger.info(f"Using project root: {project_root}")
            self._project_root = project_root
            # Get cached GUID index for script name resolution
            self._guid_index = get_cached_guid_index(project_root)
        else:
            logger.warning(f"Could not find project root for: {file_path_obj}")
            self._project_root = None
            self._guid_index = None

        # Create document
        doc = UnityDocument(file_path=str(file_path))
        doc.project_root = str(project_root) if project_root else None

        # Use unityflow's build_hierarchy() with nested prefab loading and GUID resolution
        hierarchy = build_hierarchy(
            self._raw_doc,
            guid_index=self._guid_index,
            project_root=self._project_root,
            load_nested_prefabs=load_nested,
        )

        # Convert unityflow hierarchy to our internal model
        for root_node in hierarchy.root_objects:
            root_go = self._convert_hierarchy_node(root_node, None)
            if root_go:
                doc.root_objects.append(root_go)
                self._collect_all_objects(root_go, doc)

        # Build stripped object -> PrefabInstance mapping for reference resolution
        self._build_stripped_mapping(doc)

        # Sort root objects by name for consistent ordering
        doc.root_objects.sort(key=lambda x: x.name)

        return doc

    def _build_stripped_mapping(self, doc: UnityDocument) -> None:
        """Build mapping from stripped objects to their parent PrefabInstances.

        This is needed to resolve references that point to stripped components
        (placeholders for components inside nested prefabs).
        """
        if not self._raw_doc:
            return

        for entry in self._raw_doc.objects:
            if not entry.stripped:
                continue

            file_id = str(entry.file_id)
            # Skip if already in our objects (shouldn't happen for stripped)
            if file_id in doc.all_objects or file_id in doc.all_components:
                continue

            # Get the parent PrefabInstance for this stripped object
            prefab_id = get_prefab_instance_for_stripped(self._raw_doc, entry.file_id)
            if prefab_id:
                doc.stripped_to_prefab[file_id] = str(prefab_id)
                logger.debug(f"Mapped stripped {entry.class_name} {file_id} -> PrefabInstance {prefab_id}")

    def _convert_hierarchy_node(
        self,
        node: HierarchyNode,
        parent: Optional[UnityGameObject],
    ) -> Optional[UnityGameObject]:
        """Convert a unityflow HierarchyNode to our UnityGameObject.

        Args:
            node: The unityflow HierarchyNode to convert
            parent: The parent UnityGameObject (or None for root)

        Returns:
            Converted UnityGameObject
        """
        # Create UnityGameObject from HierarchyNode
        go = UnityGameObject(
            file_id=str(node.file_id),
            name=node.name,
            parent=parent,
            is_prefab_instance=node.is_prefab_instance,
            source_prefab_guid=node.source_guid if node.is_prefab_instance else None,
            prefab_instance_id=str(node.prefab_instance_id) if node.prefab_instance_id else None,
        )

        # Convert components
        for comp_info in node.components:
            comp = self._convert_component_info(comp_info)
            go.components.append(comp)

        # Convert children recursively (nested prefab contents already loaded by unityflow)
        for child_node in node.children:
            child_go = self._convert_hierarchy_node(child_node, go)
            if child_go:
                go.children.append(child_go)

        return go

    def _convert_component_info(self, comp_info: ComponentInfo) -> UnityComponent:
        """Convert a unityflow ComponentInfo to our UnityComponent.

        Args:
            comp_info: The unityflow ComponentInfo to convert

        Returns:
            Converted UnityComponent
        """
        class_name = resolve_class_name(comp_info.class_name)
        comp = UnityComponent(
            file_id=str(comp_info.file_id),
            type_name=class_name,
        )

        # Use script info directly from unityflow (already resolved)
        comp.script_guid = comp_info.script_guid
        comp.script_name = comp_info.script_name

        # Extract all properties
        comp.properties = self._extract_properties(comp_info.data)

        return comp

    def _collect_all_objects(self, go: UnityGameObject, doc: UnityDocument) -> None:
        """Recursively collect all GameObjects and Components into doc's lookup dicts."""
        doc.all_objects[go.file_id] = go
        for comp in go.components:
            doc.all_components[comp.file_id] = comp
        for child in go.children:
            self._collect_all_objects(child, doc)

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
