"""
Unity YAML file writer for merge results.

Applies conflict resolutions and saves the merged document.
"""

from pathlib import Path
from typing import Any, Optional
import re

from prefab_tool import UnityYAMLDocument
from prefab_tool.merge import three_way_merge
from prefab_tool.normalizer import UnityPrefabNormalizer

from prefab_diff_tool.core.unity_model import (
    MergeConflict,
    MergeResult,
    ConflictResolution,
)


class MergeResultWriter:
    """
    Writes merge results to Unity YAML files.

    Strategies:
    1. Text-based merge: Use prefab_tool's three_way_merge for line-level merging
    2. Object-based merge: Apply resolved values to individual properties
    """

    def __init__(self, normalize: bool = True):
        """
        Initialize the writer.

        Args:
            normalize: Whether to normalize output (sort by fileID, etc.)
        """
        self._normalize = normalize
        if normalize:
            self._normalizer = UnityPrefabNormalizer(
                sort_documents=True,
                sort_modifications=True,
                normalize_floats=True,
                float_precision=6,
            )
        else:
            self._normalizer = None

    def write_text_merge(
        self,
        base_path: Path,
        ours_path: Path,
        theirs_path: Path,
        output_path: Path,
        conflicts: Optional[list[MergeConflict]] = None,
    ) -> tuple[bool, int]:
        """
        Perform text-based 3-way merge and write result.

        This uses prefab_tool's three_way_merge function which performs
        line-by-line merging with conflict markers.

        Args:
            base_path: Path to BASE file
            ours_path: Path to OURS file
            theirs_path: Path to THEIRS file
            output_path: Path to write merged result
            conflicts: Optional list of resolved conflicts to apply

        Returns:
            Tuple of (success, conflict_count)
        """
        # Read file contents
        base_content = base_path.read_text(encoding='utf-8')
        ours_content = ours_path.read_text(encoding='utf-8')
        theirs_content = theirs_path.read_text(encoding='utf-8')

        # Perform 3-way merge
        # three_way_merge returns (merged_content, has_conflicts)
        merged_content, has_conflicts = three_way_merge(
            base_content, ours_content, theirs_content
        )

        # Count conflicts by counting conflict markers
        conflict_count = merged_content.count('<<<<<<< ours')

        # Apply conflict resolutions if provided
        if conflicts and has_conflicts:
            merged_content = self._apply_text_resolutions(
                merged_content, conflicts
            )

        # Normalize if enabled
        if self._normalize and self._normalizer:
            # Write to temp location and normalize
            output_path.write_text(merged_content, encoding='utf-8')
            self._normalizer.normalize_file(str(output_path), str(output_path))
        else:
            output_path.write_text(merged_content, encoding='utf-8')

        return not has_conflicts, conflict_count

    def _apply_text_resolutions(
        self,
        content: str,
        conflicts: list[MergeConflict],
    ) -> str:
        """
        Apply resolved conflict values to text content with conflict markers.

        Replaces conflict marker blocks with resolved values.
        """
        # Pattern to match conflict markers
        # <<<<<<< ours
        # ... ours content ...
        # =======
        # ... theirs content ...
        # >>>>>>> theirs
        conflict_pattern = re.compile(
            r'<<<<<<< ours\n(.*?)\n=======\n(.*?)\n>>>>>>> theirs',
            re.DOTALL
        )

        # Build resolution map from conflicts
        # Note: This is a simplified approach - in practice, matching
        # conflict markers to our MergeConflict objects requires
        # more sophisticated heuristics

        def replace_conflict(match):
            ours_text = match.group(1)
            theirs_text = match.group(2)

            # Find matching conflict by comparing values
            for conflict in conflicts:
                if conflict.is_resolved:
                    # Check if this conflict matches
                    if conflict.resolution == ConflictResolution.USE_OURS:
                        return ours_text
                    elif conflict.resolution == ConflictResolution.USE_THEIRS:
                        return theirs_text
                    elif conflict.resolution == ConflictResolution.USE_MANUAL:
                        if conflict.resolved_value is not None:
                            return str(conflict.resolved_value)
                        return ours_text

            # If no matching resolution, keep ours by default
            return ours_text

        return conflict_pattern.sub(replace_conflict, content)

    def write_object_merge(
        self,
        merge_result: MergeResult,
        output_path: Path,
    ) -> bool:
        """
        Write merge result using object-level merging.

        This approach applies resolved values directly to the OURS document's
        objects and then saves the modified document.

        Args:
            merge_result: The MergeResult containing resolved conflicts
            output_path: Path to write merged result

        Returns:
            True if successful
        """
        if not merge_result.ours:
            return False

        # Load the OURS document as the base for our merged result
        ours_doc = UnityYAMLDocument.load(merge_result.ours.file_path)

        # Apply resolved conflict values
        for conflict in merge_result.conflicts:
            if not conflict.is_resolved:
                continue

            # Get the resolved value
            if conflict.resolution == ConflictResolution.USE_OURS:
                resolved_value = conflict.ours_value
            elif conflict.resolution == ConflictResolution.USE_THEIRS:
                resolved_value = conflict.theirs_value
            elif conflict.resolution == ConflictResolution.USE_MANUAL:
                resolved_value = conflict.resolved_value
            else:
                continue

            # Apply to document
            self._apply_property_value(ours_doc, conflict.path, resolved_value)

        # Save the document
        ours_doc.save(str(output_path))

        # Normalize if enabled
        if self._normalize and self._normalizer:
            self._normalizer.normalize_file(str(output_path), str(output_path))

        return True

    def _apply_property_value(
        self,
        doc: UnityYAMLDocument,
        path: str,
        value: Any,
    ) -> bool:
        """
        Apply a resolved value to a property in the document.

        Path format: "GameObjectPath.ComponentType.PropertyPath"
        Example: "Player/Body.Transform.m_LocalPosition.x"

        Args:
            doc: The Unity document to modify
            path: Full property path
            value: The resolved value to set

        Returns:
            True if successfully applied
        """
        # Parse the path
        # Format: "GOPath.ComponentType.PropertyPath"
        parts = path.split('.')
        if len(parts) < 3:
            return False

        go_path = parts[0]
        comp_type = parts[1]
        prop_path = '.'.join(parts[2:])

        # Find the object by path (this is simplified - real impl needs
        # to traverse hierarchy)
        for obj in doc.entries:
            if not hasattr(obj, 'm_Name'):
                continue

            # Check if this is the right object or component
            obj_name = getattr(obj, 'm_Name', '')
            class_name = obj.__class__.__name__

            if class_name == comp_type:
                # Try to set the property
                try:
                    self._set_nested_property(obj, prop_path, value)
                    return True
                except (AttributeError, KeyError):
                    pass

        return False

    def _set_nested_property(self, obj: Any, path: str, value: Any) -> None:
        """
        Set a nested property value on an object.

        Args:
            obj: The object to modify
            path: Dot-separated property path
            value: Value to set
        """
        parts = path.split('.')
        current = obj

        # Navigate to parent of target property
        for part in parts[:-1]:
            if isinstance(current, dict):
                current = current[part]
            else:
                current = getattr(current, part)

        # Set the final property
        final_prop = parts[-1]
        if isinstance(current, dict):
            current[final_prop] = value
        else:
            setattr(current, final_prop, value)


def write_merge_result(
    merge_result: MergeResult,
    output_path: Path,
    normalize: bool = True,
) -> bool:
    """
    Convenience function to write a merge result.

    Args:
        merge_result: The MergeResult to write
        output_path: Path to write the result
        normalize: Whether to normalize the output

    Returns:
        True if successful
    """
    writer = MergeResultWriter(normalize=normalize)
    return writer.write_object_merge(merge_result, output_path)


def perform_text_merge(
    base_path: Path,
    ours_path: Path,
    theirs_path: Path,
    output_path: Path,
    conflicts: Optional[list[MergeConflict]] = None,
    normalize: bool = True,
) -> tuple[bool, int]:
    """
    Convenience function to perform text-based merge.

    Args:
        base_path: Path to BASE file
        ours_path: Path to OURS file
        theirs_path: Path to THEIRS file
        output_path: Path to write merged result
        conflicts: Optional resolved conflicts to apply
        normalize: Whether to normalize output

    Returns:
        Tuple of (no_conflicts, conflict_count)
    """
    writer = MergeResultWriter(normalize=normalize)
    return writer.write_text_merge(
        base_path, ours_path, theirs_path, output_path, conflicts
    )
