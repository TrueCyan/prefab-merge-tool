"""
Unity file loader using unityparser.

Converts Unity YAML files to our internal UnityDocument model.
"""

from pathlib import Path
from typing import Any, Optional

from unityparser import UnityDocument as UnityParserDoc

from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
    UnityProperty,
)


class UnityFileLoader:
    """Loads Unity YAML files and converts to UnityDocument model."""

    # Component type names that are skipped for hierarchy building
    SKIP_TYPES = frozenset({"Prefab", "PrefabInstance"})

    def __init__(self):
        self._raw_doc: Optional[UnityParserDoc] = None
        self._entries_by_id: dict[str, Any] = {}

    def load(self, file_path: Path) -> UnityDocument:
        """
        Load a Unity YAML file and convert to UnityDocument.

        Args:
            file_path: Path to the Unity file (.prefab, .unity, .asset, etc.)

        Returns:
            UnityDocument with parsed hierarchy
        """
        self._raw_doc = UnityParserDoc.load_yaml(str(file_path))
        self._entries_by_id = {}

        # Index all entries by their anchor (fileID)
        for entry in self._raw_doc.entries:
            anchor = getattr(entry, "anchor", None)
            if anchor:
                self._entries_by_id[str(anchor)] = entry

        # Create document
        doc = UnityDocument(file_path=str(file_path))

        # Extract all GameObjects and Components
        game_objects: dict[str, UnityGameObject] = {}
        components: dict[str, UnityComponent] = {}

        for entry in self._raw_doc.entries:
            anchor = str(getattr(entry, "anchor", ""))
            class_name = entry.__class__.__name__

            if class_name == "GameObject":
                go = self._parse_game_object(entry, anchor)
                game_objects[anchor] = go
                doc.all_objects[anchor] = go

            elif class_name not in self.SKIP_TYPES:
                comp = self._parse_component(entry, anchor, class_name)
                components[anchor] = comp
                doc.all_components[anchor] = comp

        # Build hierarchy relationships
        self._build_hierarchy(game_objects, components)

        # Find root objects (those without parents)
        for go in game_objects.values():
            if go.parent is None:
                doc.root_objects.append(go)

        # Sort root objects by name for consistent ordering
        doc.root_objects.sort(key=lambda x: x.name)

        return doc

    def _parse_game_object(self, entry: Any, anchor: str) -> UnityGameObject:
        """Parse a GameObject entry."""
        name = getattr(entry, "m_Name", "Unnamed")
        layer = getattr(entry, "m_Layer", 0)
        tag = getattr(entry, "m_TagString", "Untagged")
        is_active = bool(getattr(entry, "m_IsActive", 1))

        return UnityGameObject(
            file_id=anchor,
            name=name,
            layer=layer,
            tag=tag,
            is_active=is_active,
        )

    def _parse_component(
        self, entry: Any, anchor: str, class_name: str
    ) -> UnityComponent:
        """Parse a component entry."""
        comp = UnityComponent(
            file_id=anchor,
            type_name=class_name,
        )

        # Handle MonoBehaviour special case
        if class_name == "MonoBehaviour":
            script_ref = getattr(entry, "m_Script", None)
            if script_ref:
                comp.script_guid = self._extract_guid(script_ref)
                # Try to get script name from metadata if available
                comp.script_name = self._guess_script_name(entry)

        # Extract all properties
        comp.properties = self._extract_properties(entry)

        return comp

    def _extract_properties(
        self, entry: Any, prefix: str = ""
    ) -> list[UnityProperty]:
        """Recursively extract all properties from an entry."""
        properties = []

        # Get all attributes that don't start with underscore
        for attr_name in dir(entry):
            if attr_name.startswith("_") or attr_name == "anchor":
                continue

            try:
                value = getattr(entry, attr_name)
            except (AttributeError, Exception):
                continue

            # Skip methods
            if callable(value):
                continue

            path = f"{prefix}{attr_name}" if prefix else attr_name
            prop = self._create_property(attr_name, value, path)
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
            # Check if it's a reference (has fileID)
            if "fileID" in value:
                return UnityProperty(
                    name=name,
                    value=self._format_reference(value),
                    path=path,
                )
            else:
                # Nested dict - flatten to string representation
                return UnityProperty(name=name, value=value, path=path)

        elif isinstance(value, list):
            return UnityProperty(name=name, value=value, path=path)

        else:
            # Complex object - try to get a reasonable representation
            return UnityProperty(name=name, value=str(value), path=path)

    def _format_reference(self, ref: dict) -> str:
        """Format a Unity reference dict as string."""
        file_id = ref.get("fileID", 0)
        guid = ref.get("guid", "")
        if guid:
            return f"{{fileID: {file_id}, guid: {guid}}}"
        return f"{{fileID: {file_id}}}"

    def _extract_guid(self, script_ref: Any) -> Optional[str]:
        """Extract GUID from a script reference."""
        if isinstance(script_ref, dict):
            return script_ref.get("guid")
        return None

    def _guess_script_name(self, entry: Any) -> Optional[str]:
        """Try to guess the script name from entry attributes."""
        # Some common patterns for script identification
        for attr in ["m_Name", "m_ClassName", "m_ScriptName"]:
            name = getattr(entry, attr, None)
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
            go_ref = getattr(entry, "m_GameObject", None)
            if go_ref and isinstance(go_ref, dict):
                go_id = str(go_ref.get("fileID", ""))
                if go_id in game_objects:
                    game_objects[go_id].components.append(comp)

        # Second pass: build Transform hierarchy
        for go_id, go in game_objects.items():
            transform = go.get_transform()
            if not transform:
                continue

            # Find transform entry in raw data
            transform_entry = self._entries_by_id.get(transform.file_id)
            if not transform_entry:
                continue

            # Get parent transform
            father_ref = getattr(transform_entry, "m_Father", None)
            if father_ref and isinstance(father_ref, dict):
                father_id = str(father_ref.get("fileID", ""))
                if father_id and father_id != "0":
                    # Find parent GameObject through its transform
                    parent_go = self._find_go_by_transform(
                        game_objects, father_id
                    )
                    if parent_go:
                        go.parent = parent_go
                        parent_go.children.append(go)

            # Get children from m_Children list
            children_refs = getattr(transform_entry, "m_Children", [])
            if isinstance(children_refs, list):
                for child_ref in children_refs:
                    if isinstance(child_ref, dict):
                        child_transform_id = str(child_ref.get("fileID", ""))
                        child_go = self._find_go_by_transform(
                            game_objects, child_transform_id
                        )
                        if child_go and child_go not in go.children:
                            child_go.parent = go
                            go.children.append(child_go)

        # Sort children by name for consistent ordering
        for go in game_objects.values():
            go.children.sort(key=lambda x: x.name)

    def _find_go_by_transform(
        self,
        game_objects: dict[str, UnityGameObject],
        transform_id: str,
    ) -> Optional[UnityGameObject]:
        """Find GameObject that owns the given transform."""
        for go in game_objects.values():
            transform = go.get_transform()
            if transform and transform.file_id == transform_id:
                return go
        return None


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
