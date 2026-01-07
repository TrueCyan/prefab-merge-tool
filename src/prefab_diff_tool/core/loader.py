"""
Unity file loader using unityflow.

Converts Unity YAML files to our internal UnityDocument model.
Uses unityflow's build_hierarchy() for hierarchy parsing, including
nested prefab loading and script name resolution.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from unityflow import (
    UnityYAMLDocument,
    build_hierarchy,
    HierarchyNode,
    ComponentInfo,
    get_lazy_guid_index,
    find_unity_project_root,
    GUIDIndex,
    LazyGUIDIndex,
    get_prefab_instance_for_stripped,
)


class PathOnlyGUIDIndex:
    """Wrapper that only allows path resolution, skipping script name resolution.

    This tricks unityflow's build_hierarchy into skipping script resolution
    (which does N individual SQLite queries) while still allowing nested prefab
    path resolution (which only needs a few queries).
    """

    def __init__(self, guid_index: LazyGUIDIndex):
        self._guid_index = guid_index
        self.project_root = guid_index.project_root

    def get_path(self, guid: str):
        """Allow path resolution for nested prefab loading."""
        return self._guid_index.get_path(guid)

    def resolve_name(self, guid: str):
        """Skip script name resolution - return None to force unityflow to skip."""
        return None

    def resolve_path(self, guid: str):
        """Allow path resolution."""
        return self._guid_index.resolve_path(guid)

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
        self._guid_index: Optional[LazyGUIDIndex] = None
        self._project_root: Optional[Path] = None

    def load(
        self,
        file_path: Path,
        unity_root: Optional[Path] = None,
        load_nested: bool = True,
        resolve_guids: bool = True,
    ) -> UnityDocument:
        """
        Load a Unity YAML file and convert to UnityDocument.

        Args:
            file_path: Path to the Unity file (.prefab, .unity, .asset, etc.)
            unity_root: Optional Unity project root for GUID resolution
            load_nested: If True, load contents of nested prefabs (default True)
            resolve_guids: If True, build GUID index for script name resolution (slower)

        Returns:
            UnityDocument with parsed hierarchy
        """
        t0 = time.perf_counter()

        self._raw_doc = UnityYAMLDocument.load(str(file_path))
        t1 = time.perf_counter()
        logger.info(f"[TIMING] YAML load: {(t1-t0)*1000:.1f}ms")

        # Find Unity project root
        file_path_obj = Path(file_path) if isinstance(file_path, str) else file_path
        project_root = unity_root or find_unity_project_root(file_path_obj)

        if project_root:
            logger.info(f"Using project root: {project_root}")
            self._project_root = project_root
            # Use lazy GUID index for fast startup (O(1) init, queries SQLite on-demand)
            if resolve_guids:
                self._guid_index = get_lazy_guid_index(project_root)
            else:
                self._guid_index = None
        else:
            logger.warning(f"Could not find project root for: {file_path_obj}")
            self._project_root = None
            self._guid_index = None

        t2 = time.perf_counter()
        logger.info(f"[TIMING] Project root + GUID index: {(t2-t1)*1000:.1f}ms")

        # Create document
        doc = UnityDocument(file_path=str(file_path))
        doc.project_root = str(project_root) if project_root else None

        # Build hierarchy WITHOUT script resolution for fast loading
        # Use PathOnlyGUIDIndex wrapper to allow path resolution but skip script resolution
        path_only_index = PathOnlyGUIDIndex(self._guid_index) if self._guid_index else None
        hierarchy = build_hierarchy(
            self._raw_doc,
            guid_index=path_only_index,  # Path resolution only, no script resolution
            project_root=self._project_root,
            load_nested_prefabs=False,
        )
        t3 = time.perf_counter()
        logger.info(f"[TIMING] build_hierarchy (no scripts): {(t3-t2)*1000:.1f}ms")

        # Load nested prefabs (also without script resolution)
        if load_nested:
            nested_count = hierarchy.load_all_nested_prefabs()
            t3b = time.perf_counter()
            logger.info(f"[TIMING] load_nested_prefabs ({nested_count} prefabs): {(t3b-t3)*1000:.1f}ms")
            t3 = t3b

        # Batch resolve all script GUIDs first (much faster than individual queries)
        script_guid_map = {}
        if self._guid_index:
            all_guids = set()
            for node in hierarchy.iter_all():
                for comp in node.components:
                    if comp.script_guid:
                        all_guids.add(comp.script_guid)
            if all_guids:
                script_guid_map = self._batch_resolve_guids(all_guids)
                logger.info(f"[TIMING] Batch resolved {len(script_guid_map)}/{len(all_guids)} script GUIDs")

        t3c = time.perf_counter()
        logger.info(f"[TIMING] Batch GUID resolution: {(t3c-t3)*1000:.1f}ms")

        # Convert unityflow hierarchy to our internal model
        for root_node in hierarchy.root_objects:
            root_go = self._convert_hierarchy_node(root_node, None, script_guid_map)
            if root_go:
                doc.root_objects.append(root_go)
                self._collect_all_objects(root_go, doc)

        t4 = time.perf_counter()
        logger.info(f"[TIMING] Convert hierarchy: {(t4-t3c)*1000:.1f}ms")

        # Build stripped object -> PrefabInstance mapping for reference resolution
        self._build_stripped_mapping(doc)

        t5 = time.perf_counter()
        logger.info(f"[TIMING] Build stripped mapping: {(t5-t4)*1000:.1f}ms")

        # Sort root objects by name for consistent ordering
        doc.root_objects.sort(key=lambda x: x.name)

        logger.info(f"[TIMING] TOTAL: {(t5-t0)*1000:.1f}ms")

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
                # Resolve class name (handle Unknown(ID) format)
                class_name = resolve_class_name(entry.class_name)
                doc.stripped_to_prefab[file_id] = (str(prefab_id), class_name)
                logger.debug(f"Mapped stripped {class_name} {file_id} -> PrefabInstance {prefab_id}")

    def _batch_resolve_guids(self, guids: set[str]) -> dict[str, str]:
        """Batch resolve GUIDs to script names using a single SQL query.

        Args:
            guids: Set of GUIDs to resolve

        Returns:
            Dict mapping GUID -> script name
        """
        if not self._guid_index or not guids:
            return {}

        import sqlite3
        from unityflow.asset_tracker import CACHE_DIR_NAME, CACHE_DB_NAME

        db_path = self._project_root / CACHE_DIR_NAME / CACHE_DB_NAME
        if not db_path.exists():
            return {}

        result = {}
        try:
            conn = sqlite3.connect(str(db_path), timeout=30.0)
            # Use WHERE IN for batch query
            placeholders = ",".join("?" * len(guids))
            cursor = conn.execute(
                f"SELECT guid, path FROM guid_cache WHERE guid IN ({placeholders})",
                list(guids),
            )
            for row in cursor:
                guid, path = row
                # Extract script name from path (stem)
                from pathlib import Path
                result[guid] = Path(path).stem
            conn.close()
        except sqlite3.Error as e:
            logger.warning(f"Batch GUID resolution failed: {e}")

        return result

    def _convert_hierarchy_node(
        self,
        node: HierarchyNode,
        parent: Optional[UnityGameObject],
        script_guid_map: Optional[dict[str, str]] = None,
    ) -> Optional[UnityGameObject]:
        """Convert a unityflow HierarchyNode to our UnityGameObject.

        Args:
            node: The unityflow HierarchyNode to convert
            parent: The parent UnityGameObject (or None for root)
            script_guid_map: Pre-resolved GUID -> script name mapping

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
            comp = self._convert_component_info(comp_info, script_guid_map)
            go.components.append(comp)

        # Convert children recursively (nested prefab contents already loaded by unityflow)
        for child_node in node.children:
            child_go = self._convert_hierarchy_node(child_node, go, script_guid_map)
            if child_go:
                go.children.append(child_go)

        return go

    def _convert_component_info(
        self,
        comp_info: ComponentInfo,
        script_guid_map: Optional[dict[str, str]] = None,
    ) -> UnityComponent:
        """Convert a unityflow ComponentInfo to our UnityComponent.

        Args:
            comp_info: The unityflow ComponentInfo to convert
            script_guid_map: Pre-resolved GUID -> script name mapping

        Returns:
            Converted UnityComponent
        """
        class_name = resolve_class_name(comp_info.class_name)
        comp = UnityComponent(
            file_id=str(comp_info.file_id),
            type_name=class_name,
        )

        # Script resolution: use pre-resolved map, unityflow's result, or fallback
        comp.script_guid = comp_info.script_guid
        if comp_info.script_name:
            comp.script_name = comp_info.script_name
        elif comp_info.script_guid and script_guid_map:
            comp.script_name = script_guid_map.get(comp_info.script_guid)

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
    resolve_guids: bool = True,
) -> UnityDocument:
    """
    Convenience function to load a Unity file.

    Args:
        file_path: Path to the Unity file
        unity_root: Optional Unity project root for GUID resolution
        load_nested: If True, load contents of nested prefabs (default True)
        resolve_guids: If True, build GUID index for script name resolution (slower)

    Returns:
        UnityDocument with parsed hierarchy
    """
    loader = UnityFileLoader()
    return loader.load(
        file_path,
        unity_root=unity_root,
        load_nested=load_nested,
        resolve_guids=resolve_guids,
    )
