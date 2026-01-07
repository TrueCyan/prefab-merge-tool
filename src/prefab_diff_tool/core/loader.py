"""
Unity file loader using unityflow.

Converts Unity YAML files to our internal UnityDocument model.
Uses unityflow's build_hierarchy() for hierarchy parsing, including
nested prefab loading and script name resolution.
"""

import copy
import logging
import re
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
from unityflow.parser import CLASS_IDS

from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
    UnityProperty,
)

# Set up logging
logger = logging.getLogger(__name__)

# Pattern to match "Unknown(ID)" format
_UNKNOWN_PATTERN = re.compile(r"Unknown\((\d+)\)")


def resolve_class_name(class_name: str) -> str:
    """Resolve class name, handling Unknown(ID) format.

    Uses unityflow's CLASS_IDS for resolution.
    """
    match = _UNKNOWN_PATTERN.match(class_name)
    if match:
        class_id = int(match.group(1))
        return CLASS_IDS.get(class_id, class_name)
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
        self._raw_doc = UnityYAMLDocument.load(str(file_path))

        # Find Unity project root
        file_path_obj = Path(file_path) if isinstance(file_path, str) else file_path
        project_root = unity_root or find_unity_project_root(file_path_obj)

        if project_root:
            logger.debug(f"Using project root: {project_root}")
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

        # Create document
        doc = UnityDocument(file_path=str(file_path))
        doc.project_root = str(project_root) if project_root else None

        # Build hierarchy with script name resolution
        # unityflow 0.3.0+ uses internal batch resolution for O(1) performance
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
                # Resolve class name (handle Unknown(ID) format)
                class_name = resolve_class_name(entry.class_name)
                doc.stripped_to_prefab[file_id] = (str(prefab_id), class_name)
                logger.debug(f"Mapped stripped {class_name} {file_id} -> PrefabInstance {prefab_id}")

    def _convert_hierarchy_node(
        self,
        node: HierarchyNode,
        parent: Optional[UnityGameObject],
    ) -> Optional[UnityGameObject]:
        """Convert a unityflow HierarchyNode to our UnityGameObject.

        For PrefabInstance nodes with loaded nested content, merges the
        PrefabInstance with its nested root to avoid duplicate display.
        Applies m_Modifications from the PrefabInstance to override field values.

        Args:
            node: The unityflow HierarchyNode to convert
            parent: The parent UnityGameObject (or None for root)

        Returns:
            Converted UnityGameObject
        """
        # Check if this is a PrefabInstance with loaded nested content
        # In this case, merge with the nested root to avoid duplicate display
        nested_root = None
        modifications_by_target: dict[int, list[dict]] = {}

        if node.is_prefab_instance and node.nested_prefab_loaded and node.children:
            # Find the nested prefab's root (first child that is_from_nested_prefab)
            for child in node.children:
                if child.is_from_nested_prefab:
                    nested_root = child
                    break

            # Group modifications by target fileID for efficient lookup
            for mod in node.modifications:
                target = mod.get("target", {})
                target_file_id = target.get("fileID", 0)
                if target_file_id:
                    if target_file_id not in modifications_by_target:
                        modifications_by_target[target_file_id] = []
                    modifications_by_target[target_file_id].append(mod)

        # Create UnityGameObject from HierarchyNode
        go = UnityGameObject(
            file_id=str(node.file_id),
            name=node.name,
            parent=parent,
            is_prefab_instance=node.is_prefab_instance,
            source_prefab_guid=node.source_guid if node.is_prefab_instance else None,
            prefab_instance_id=str(node.prefab_instance_id) if node.prefab_instance_id else None,
        )

        # Collect components - merge if nested root exists
        components_by_type: dict[str, ComponentInfo] = {}

        # First add nested root's components (original/base)
        if nested_root:
            for comp_info in nested_root.components:
                key = comp_info.script_name or comp_info.class_name
                components_by_type[key] = comp_info

        # Then add/override with PrefabInstance's components (modifications)
        for comp_info in node.components:
            key = comp_info.script_name or comp_info.class_name
            components_by_type[key] = comp_info

        # Convert components maintaining order (nested root order, then any new from PrefabInstance)
        seen_keys = set()
        if nested_root:
            for comp_info in nested_root.components:
                key = comp_info.script_name or comp_info.class_name
                final_comp_info = components_by_type[key]
                # Apply modifications targeting this component
                mods = modifications_by_target.get(final_comp_info.file_id, [])
                comp = self._convert_component_info(final_comp_info, mods)
                go.components.append(comp)
                seen_keys.add(key)

        for comp_info in node.components:
            key = comp_info.script_name or comp_info.class_name
            if key not in seen_keys:
                # Apply modifications for PrefabInstance's own components
                mods = modifications_by_target.get(comp_info.file_id, [])
                comp = self._convert_component_info(comp_info, mods)
                go.components.append(comp)
                seen_keys.add(key)

        # Convert children
        if nested_root:
            # Use nested root's children (they contain the actual hierarchy)
            for child_node in nested_root.children:
                child_go = self._convert_hierarchy_node(child_node, go)
                if child_go:
                    go.children.append(child_go)
        else:
            # Normal case - use node's children directly
            for child_node in node.children:
                child_go = self._convert_hierarchy_node(child_node, go)
                if child_go:
                    go.children.append(child_go)

        return go

    def _convert_component_info(
        self,
        comp_info: ComponentInfo,
        modifications: Optional[list[dict]] = None,
    ) -> UnityComponent:
        """Convert a unityflow ComponentInfo to our UnityComponent.

        Args:
            comp_info: The unityflow ComponentInfo to convert
            modifications: Optional list of m_Modifications targeting this component

        Returns:
            Converted UnityComponent
        """
        class_name = resolve_class_name(comp_info.class_name)
        comp = UnityComponent(
            file_id=str(comp_info.file_id),
            type_name=class_name,
        )

        # Script name is resolved by unityflow 0.3.0+ via batch resolution
        comp.script_guid = comp_info.script_guid
        comp.script_name = comp_info.script_name

        # Apply modifications to component data before extracting properties
        data = comp_info.data
        if modifications:
            # Deep copy to avoid modifying the original data
            data = self._apply_modifications(copy.deepcopy(data), modifications)

        # Extract all properties
        comp.properties = self._extract_properties(data)

        return comp

    def _apply_modifications(
        self,
        data: dict,
        modifications: list[dict],
    ) -> dict:
        """Apply PrefabInstance modifications to component data.

        Each modification has:
        - propertyPath: path like "m_LocalPosition.x" or "m_Materials.Array.data[0]"
        - value: the new value (for simple types)
        - objectReference: reference value (for object references)

        Args:
            data: Component data dictionary (will be modified in place)
            modifications: List of modifications targeting this component

        Returns:
            Modified data dictionary
        """
        for mod in modifications:
            property_path = mod.get("propertyPath", "")
            value = mod.get("value")
            obj_ref = mod.get("objectReference", {})

            if not property_path:
                continue

            # Parse property path and apply value
            self._set_nested_value(data, property_path, value, obj_ref)

        return data

    def _set_nested_value(
        self,
        data: dict,
        property_path: str,
        value: Any,
        obj_ref: dict,
    ) -> None:
        """Set a nested value in a dictionary using Unity property path.

        Handles paths like:
        - "m_LocalPosition.x"
        - "m_Materials.Array.data[0]"
        - "m_Name"

        Args:
            data: Dictionary to modify
            property_path: Unity property path
            value: Value to set (for simple types)
            obj_ref: Object reference (for reference types)
        """
        # Unity property paths use "." for nesting and ".Array.data[N]" for arrays
        parts = property_path.split(".")
        current = data

        for i, part in enumerate(parts[:-1]):
            # Handle array access like "Array" followed by "data[0]"
            if part == "Array":
                continue  # Skip "Array", next part will be "data[N]"

            # Handle "data[N]" pattern
            if part.startswith("data["):
                idx_str = part[5:-1]  # Extract N from "data[N]"
                try:
                    idx = int(idx_str)
                    if isinstance(current, list) and 0 <= idx < len(current):
                        current = current[idx]
                    else:
                        return  # Index out of range
                except (ValueError, TypeError):
                    return
                continue

            # Regular nested key
            if isinstance(current, dict):
                if part not in current:
                    current[part] = {}
                current = current[part]
            else:
                return  # Cannot traverse further

        # Set the final value
        final_key = parts[-1]

        # Handle final array index
        if final_key.startswith("data["):
            idx_str = final_key[5:-1]
            try:
                idx = int(idx_str)
                if isinstance(current, list) and 0 <= idx < len(current):
                    # Use object reference if fileID is non-zero, otherwise use value
                    if obj_ref and obj_ref.get("fileID", 0) != 0:
                        current[idx] = obj_ref
                    else:
                        current[idx] = value
            except (ValueError, TypeError):
                pass
            return

        # Regular final key
        if isinstance(current, dict):
            # Use object reference if fileID is non-zero, otherwise use value
            if obj_ref and obj_ref.get("fileID", 0) != 0:
                current[final_key] = obj_ref
            else:
                current[final_key] = value

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
