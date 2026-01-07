"""
Unity file loader using unityflow.

Converts Unity YAML files to our internal UnityDocument model.
Uses unityflow's build_hierarchy() for hierarchy parsing.
"""

import logging
import re
from pathlib import Path
from typing import Any, Optional

from unityflow import UnityYAMLDocument, build_hierarchy, HierarchyNode, ComponentInfo

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
    """Loads Unity YAML files and converts to UnityDocument model.

    Uses unityflow's build_hierarchy() for parsing hierarchy structure,
    then converts to our internal model with additional features like
    nested prefab content loading.
    """

    def __init__(self):
        self._raw_doc: Optional[UnityYAMLDocument] = None
        self._guid_resolver = GuidResolver()
        # Track loading prefabs to prevent circular references
        self._loading_prefabs: set[str] = set()
        # Project root for nested prefab loading
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
        """Internal load implementation using unityflow's build_hierarchy()."""
        self._raw_doc = UnityYAMLDocument.load(str(file_path))

        # Find Unity project root and setup GUID resolver
        file_path_obj = Path(file_path) if isinstance(file_path, str) else file_path
        project_root = None

        if unity_root:
            project_root = unity_root
            logger.info(f"Using provided unity_root: {project_root}")
        else:
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

        # Create document
        doc = UnityDocument(file_path=str(file_path))
        doc.project_root = str(project_root) if project_root else None

        # Use unityflow's build_hierarchy() for hierarchy parsing
        hierarchy = build_hierarchy(self._raw_doc)

        # Convert unityflow hierarchy to our internal model
        for root_node in hierarchy.root_objects:
            root_go = self._convert_hierarchy_node(root_node, None, load_nested)
            if root_go:
                doc.root_objects.append(root_go)
                self._collect_all_objects(root_go, doc)

        # Sort root objects by name for consistent ordering
        doc.root_objects.sort(key=lambda x: x.name)

        return doc

    def _convert_hierarchy_node(
        self,
        node: HierarchyNode,
        parent: Optional[UnityGameObject],
        load_nested: bool,
    ) -> Optional[UnityGameObject]:
        """Convert a unityflow HierarchyNode to our UnityGameObject.

        Args:
            node: The unityflow HierarchyNode to convert
            parent: The parent UnityGameObject (or None for root)
            load_nested: If True, load nested prefab contents

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

        # For PrefabInstances, load nested prefab contents if requested
        if node.is_prefab_instance and load_nested and node.source_guid:
            self._load_nested_prefab_contents(go, node.source_guid)

        # Convert children recursively
        for child_node in node.children:
            child_go = self._convert_hierarchy_node(child_node, go, load_nested)
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

        data = comp_info.data

        # Handle MonoBehaviour script resolution
        if class_name == "MonoBehaviour":
            script_ref = data.get("m_Script")
            if script_ref:
                comp.script_guid = self._extract_guid(script_ref)
                comp.script_name = self._guess_script_name(data)
                if not comp.script_name and comp.script_guid:
                    comp.script_name = self._guid_resolver.resolve(comp.script_guid)
                    if comp.script_name:
                        logger.debug(
                            f"Resolved script GUID {comp.script_guid[:8]}... -> {comp.script_name}"
                        )

        # Extract all properties
        comp.properties = self._extract_properties(data)

        return comp

    def _collect_all_objects(self, go: UnityGameObject, doc: UnityDocument) -> None:
        """Recursively collect all GameObjects and Components into doc's lookup dicts."""
        doc.all_objects[go.file_id] = go
        for comp in go.components:
            doc.all_components[comp.file_id] = comp
        for child in go.children:
            self._collect_all_objects(child, doc)

    def _load_nested_prefab_contents(
        self, virtual_go: UnityGameObject, source_guid: str
    ) -> None:
        """Load the contents of a nested prefab and add as children.

        The nested prefab's root object's children and components are merged
        into virtual_go, showing the prefab contents under the PrefabInstance.

        Note: The name is already resolved by unityflow's build_hierarchy(),
        including m_Modifications name overrides.

        Args:
            virtual_go: The virtual GameObject representing the PrefabInstance
            source_guid: GUID of the source prefab to load
        """
        if not self._project_root:
            logger.debug(f"No project root, skipping nested prefab load for {virtual_go.name}")
            return

        # Resolve GUID to file path
        source_path = self._guid_resolver.resolve_path(source_guid)
        if not source_path:
            logger.warning(
                f"Could not resolve path for prefab GUID: {source_guid} "
                f"(name: {virtual_go.name})"
            )
            return

        # Make path absolute if needed
        if not source_path.is_absolute():
            source_path = self._project_root / source_path

        if not source_path.exists():
            logger.warning(f"Source prefab not found: {source_path}")
            return

        # Check for circular reference
        source_path_str = str(source_path)
        if source_path_str in self._loading_prefabs:
            logger.debug(f"Circular reference detected, skipping: {source_path_str}")
            return

        logger.debug(f"Loading nested prefab contents: {source_path}")

        try:
            # Use a NEW loader instance to avoid corrupting current loader's state
            nested_loader = UnityFileLoader()
            nested_loader._loading_prefabs = self._loading_prefabs  # Share circular ref tracking
            nested_doc = nested_loader.load(source_path, self._project_root, load_nested=True)

            # Get the first root object (main prefab root)
            if nested_doc.root_objects:
                root_obj = nested_doc.root_objects[0]

                # Copy root's children directly to virtual_go (skip the root level)
                for child in root_obj.children:
                    cloned = self._clone_game_object(child, virtual_go)
                    virtual_go.children.append(cloned)

                # Also copy components from root
                virtual_go.components.extend(root_obj.components)

                logger.debug(
                    f"Loaded nested prefab '{virtual_go.name}' with {len(virtual_go.children)} children"
                )
            else:
                logger.warning(f"No root objects found in prefab: {source_path}")
        except Exception as e:
            logger.warning(f"Failed to load nested prefab {source_path}: {e}", exc_info=True)

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
