#!/usr/bin/env python3
"""
Test unityflow 0.3.5 semantic diff/merge functionality.
"""
import sys
from pathlib import Path

# Test files
TEST_DIR = Path(__file__).parent / "test_prefabs"
BASE_FILE = TEST_DIR / "conflict_base.prefab"
OURS_FILE = TEST_DIR / "conflict_ours.prefab"
THEIRS_FILE = TEST_DIR / "conflict_theirs.prefab"


def test_semantic_diff():
    """Test semantic_diff() function."""
    print("=" * 60)
    print("Testing semantic_diff()")
    print("=" * 60)

    from unityflow import UnityYAMLDocument
    from unityflow.semantic_diff import semantic_diff

    # Load documents
    base_doc = UnityYAMLDocument.load(str(BASE_FILE))
    ours_doc = UnityYAMLDocument.load(str(OURS_FILE))

    print(f"\nComparing: {BASE_FILE.name} vs {OURS_FILE.name}")

    # Perform diff
    result = semantic_diff(base_doc, ours_doc)

    print(f"\nResult:")
    print(f"  has_changes: {result.has_changes}")
    print(f"  added_count: {result.added_count}")
    print(f"  removed_count: {result.removed_count}")
    print(f"  modified_count: {result.modified_count}")

    print(f"\nProperty Changes ({len(result.property_changes)}):")
    for change in result.property_changes:
        print(f"  [{change.change_type.value}] {change.class_name}.{change.property_path}")
        if change.old_value is not None:
            print(f"    old: {change.old_value}")
        if change.new_value is not None:
            print(f"    new: {change.new_value}")

    print(f"\nObject Changes ({len(result.object_changes)}):")
    for change in result.object_changes:
        print(f"  [{change.change_type.value}] {change.class_name} (fileID: {change.file_id})")

    # Verify expected change
    position_changes = [c for c in result.property_changes if "LocalPosition" in c.property_path]
    if position_changes:
        print("\n[PASS] Position change detected!")
        return True
    else:
        print("\n[FAIL] Expected position change not detected")
        return False


def test_semantic_merge():
    """Test semantic_three_way_merge() function."""
    print("\n" + "=" * 60)
    print("Testing semantic_three_way_merge()")
    print("=" * 60)

    from unityflow import UnityYAMLDocument
    from unityflow.semantic_merge import semantic_three_way_merge

    # Load documents
    base_doc = UnityYAMLDocument.load(str(BASE_FILE))
    ours_doc = UnityYAMLDocument.load(str(OURS_FILE))
    theirs_doc = UnityYAMLDocument.load(str(THEIRS_FILE))

    print(f"\n3-way merge:")
    print(f"  BASE:   {BASE_FILE.name} (position.x = 0)")
    print(f"  OURS:   {OURS_FILE.name} (position.x = 10)")
    print(f"  THEIRS: {THEIRS_FILE.name} (position.x = 20)")

    # Perform merge
    result = semantic_three_way_merge(base_doc, ours_doc, theirs_doc)

    print(f"\nResult:")
    print(f"  has_conflicts: {result.has_conflicts}")
    print(f"  conflict_count: {result.conflict_count}")

    print(f"\nProperty Conflicts ({len(result.property_conflicts)}):")
    for conflict in result.property_conflicts:
        print(f"  [{conflict.conflict_type.value}] {conflict.class_name}.{conflict.property_path}")
        print(f"    base:   {conflict.base_value}")
        print(f"    ours:   {conflict.ours_value}")
        print(f"    theirs: {conflict.theirs_value}")

    print(f"\nObject Conflicts ({len(result.object_conflicts)}):")
    for conflict in result.object_conflicts:
        print(f"  [{conflict.conflict_type.value}] {conflict.class_name}")
        print(f"    {conflict.description}")

    print(f"\nAuto-merged Changes ({len(result.auto_merged)}):")
    for change in result.auto_merged:
        print(f"  {change.class_name}.{change.property_path} <- {change.source}")

    # Verify expected conflict
    position_conflicts = [c for c in result.property_conflicts if "LocalPosition" in c.property_path]
    if position_conflicts:
        print("\n[PASS] Position conflict detected!")
        return True
    else:
        print("\n[FAIL] Expected position conflict not detected")
        return False


def test_apply_resolution():
    """Test apply_resolution() function."""
    print("\n" + "=" * 60)
    print("Testing apply_resolution()")
    print("=" * 60)

    from unityflow import UnityYAMLDocument
    from unityflow.semantic_merge import semantic_three_way_merge, apply_resolution

    # Load and merge
    base_doc = UnityYAMLDocument.load(str(BASE_FILE))
    ours_doc = UnityYAMLDocument.load(str(OURS_FILE))
    theirs_doc = UnityYAMLDocument.load(str(THEIRS_FILE))

    result = semantic_three_way_merge(base_doc, ours_doc, theirs_doc)

    if not result.property_conflicts:
        print("[SKIP] No conflicts to resolve")
        return True

    conflict = result.property_conflicts[0]
    print(f"\nResolving conflict: {conflict.class_name}.{conflict.property_path}")
    print(f"  Choosing: ours ({conflict.ours_value})")

    # Apply resolution
    success = apply_resolution(result.merged_document, conflict, "ours")

    print(f"\nResolution applied: {success}")

    if success:
        print("[PASS] Resolution applied successfully!")
        return True
    else:
        print("[FAIL] Failed to apply resolution")
        return False


def main():
    print("=" * 60)
    print("Unityflow 0.3.5 Semantic Diff/Merge Test")
    print("=" * 60)

    # Check test files exist
    if not BASE_FILE.exists():
        print(f"[ERROR] Test file not found: {BASE_FILE}")
        return 1

    results = []

    try:
        results.append(("semantic_diff", test_semantic_diff()))
    except Exception as e:
        print(f"[ERROR] semantic_diff test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("semantic_diff", False))

    try:
        results.append(("semantic_merge", test_semantic_merge()))
    except Exception as e:
        print(f"[ERROR] semantic_merge test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("semantic_merge", False))

    try:
        results.append(("apply_resolution", test_apply_resolution()))
    except Exception as e:
        print(f"[ERROR] apply_resolution test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("apply_resolution", False))

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\nTotal: {passed}/{total} passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
