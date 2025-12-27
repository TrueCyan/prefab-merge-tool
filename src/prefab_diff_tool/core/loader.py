"""
Unity file loader using unityflow.

Converts Unity YAML files to our internal UnityDocument model.
"""

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


# Additional Unity class IDs not in unityflow's mapping
# Reference: https://docs.unity3d.com/Manual/ClassIDReference.html
ADDITIONAL_CLASS_IDS = {
    50: "Rigidbody2D",
    55: "PhysicsManager",
    57: "Joint2D",
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
    319: "AvatarMask",
    328: "VideoPlayer",
    329: "VideoClip",
    363: "OcclusionCullingData",
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
    SKIP_TYPES = frozenset({"Prefab", "PrefabInstance"})

    def __init__(self):
        self._raw_doc: Optional[UnityYAMLDocument] = None
        self._entries_by_id: dict[str, Any] = {}
        self._guid_resolver = GuidResolver()

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

    def load(self, file_path: Path) -> UnityDocument:
        """
        Load a Unity YAML file and convert to UnityDocument.

        Args:
            file_path: Path to the Unity file (.prefab, .unity, .asset, etc.)

        Returns:
            UnityDocument with parsed hierarchy
        """
        self._raw_doc = UnityYAMLDocument.load(str(file_path))
        self._entries_by_id = {}

        # Find Unity project root and setup GUID resolver
        file_path_obj = Path(file_path) if isinstance(file_path, str) else file_path
        project_root = GuidResolver.find_project_root(file_path_obj)
        if project_root:
            self._guid_resolver.set_project_root(project_root)

        # Index all entries by their file_id
        for entry in self._raw_doc.objects:
            file_id = getattr(entry, "file_id", None)
            if file_id:
                self._entries_by_id[str(file_id)] = entry

        # Create document
        doc = UnityDocument(file_path=str(file_path))
        doc.project_root = str(project_root) if project_root else None

        # Extract all GameObjects and Components
        game_objects: dict[str, UnityGameObject] = {}
        components: dict[str, UnityComponent] = {}

        for entry in self._raw_doc.objects:
            file_id = str(getattr(entry, "file_id", ""))
            raw_class_name = getattr(entry, "class_name", "Unknown")
            # Resolve Unknown(ID) patterns to actual class names
            class_name = resolve_class_name(raw_class_name)

            if class_name == "GameObject":
                go = self._parse_game_object(entry, file_id)
                game_objects[file_id] = go
                doc.all_objects[file_id] = go

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
                # Try to get script name from data first, then resolve from GUID
                comp.script_name = self._guess_script_name(data)
                if not comp.script_name and comp.script_guid:
                    comp.script_name = self._guid_resolver.resolve(comp.script_guid)

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

        # Second pass: build Transform hierarchy using m_Father only
        # (Using m_Father is sufficient and avoids duplicate children)
        for go_id, go in game_objects.items():
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

        # Sort children by name for consistent ordering
        for go in game_objects.values():
            go.children.sort(key=lambda x: x.name)


def load_unity_file(file_path: Path) -> UnityDocument:
    """
    Convenience function to load a Unity file.

    Args:
        file_path: Path to the Unity file

    Returns:
        UnityDocument with parsed hierarchy
    """
    loader = UnityFileLoader()
    return loader.load(file_path)
