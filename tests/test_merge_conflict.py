"""
Test script for verifying merge conflict detection logic.
"""
import sys
from pathlib import Path

# Add source to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from prefab_diff_tool.core.loader import load_unity_file
from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
    MergeConflict,
    DiffStatus,
)


def check_conflicts(
    base_doc: UnityDocument,
    ours_doc: UnityDocument,
    theirs_doc: UnityDocument,
) -> list[MergeConflict]:
    """
    Detect merge conflicts between three documents.
    This is a simplified version of MergeView._perform_merge()
    """
    conflicts = []

    # Build lookup maps
    base_objects = {go.file_id: go for go in base_doc.iter_all_objects()}
    ours_objects = {go.file_id: go for go in ours_doc.iter_all_objects()}
    theirs_objects = {go.file_id: go for go in theirs_doc.iter_all_objects()}

    print(f"\n=== Document Summary ===")
    print(f"BASE objects: {list(base_objects.keys())}")
    print(f"OURS objects: {list(ours_objects.keys())}")
    print(f"THEIRS objects: {list(theirs_objects.keys())}")

    # Find common objects
    all_object_ids = set(base_objects.keys()) | set(ours_objects.keys()) | set(theirs_objects.keys())

    for file_id in all_object_ids:
        in_base = file_id in base_objects
        in_ours = file_id in ours_objects
        in_theirs = file_id in theirs_objects

        if in_base and in_ours and in_theirs:
            base_go = base_objects[file_id]
            ours_go = ours_objects[file_id]
            theirs_go = theirs_objects[file_id]

            print(f"\n=== Checking GameObject: {base_go.name} (fileID: {file_id}) ===")

            # Compare components
            base_comps = {c.file_id: c for c in base_go.components}
            ours_comps = {c.file_id: c for c in ours_go.components}
            theirs_comps = {c.file_id: c for c in theirs_go.components}

            print(f"BASE components: {[(c.type_name, c.file_id) for c in base_go.components]}")
            print(f"OURS components: {[(c.type_name, c.file_id) for c in ours_go.components]}")
            print(f"THEIRS components: {[(c.type_name, c.file_id) for c in theirs_go.components]}")

            all_comp_ids = set(base_comps.keys()) | set(ours_comps.keys()) | set(theirs_comps.keys())

            for comp_id in all_comp_ids:
                base_comp = base_comps.get(comp_id)
                ours_comp = ours_comps.get(comp_id)
                theirs_comp = theirs_comps.get(comp_id)

                if base_comp and ours_comp and theirs_comp:
                    print(f"\n  Component: {base_comp.type_name} (fileID: {comp_id})")

                    # Compare properties
                    base_props = {p.path: p for p in base_comp.properties}
                    ours_props = {p.path: p for p in ours_comp.properties}
                    theirs_props = {p.path: p for p in theirs_comp.properties}

                    print(f"  BASE props: {list(base_props.keys())}")
                    print(f"  OURS props: {list(ours_props.keys())}")
                    print(f"  THEIRS props: {list(theirs_props.keys())}")

                    all_prop_paths = set(base_props.keys()) | set(ours_props.keys()) | set(theirs_props.keys())

                    for prop_path in sorted(all_prop_paths):
                        base_prop = base_props.get(prop_path)
                        ours_prop = ours_props.get(prop_path)
                        theirs_prop = theirs_props.get(prop_path)

                        base_val = base_prop.value if base_prop else None
                        ours_val = ours_prop.value if ours_prop else None
                        theirs_val = theirs_prop.value if theirs_prop else None

                        ours_changed = ours_val != base_val
                        theirs_changed = theirs_val != base_val

                        if ours_changed or theirs_changed:
                            print(f"\n    Property: {prop_path}")
                            print(f"      BASE:   {base_val}")
                            print(f"      OURS:   {ours_val} (changed={ours_changed})")
                            print(f"      THEIRS: {theirs_val} (changed={theirs_changed})")

                        if ours_changed and theirs_changed and ours_val != theirs_val:
                            # CONFLICT!
                            conflict = MergeConflict(
                                path=f"{base_go.get_path()}.{base_comp.type_name}.{prop_path}",
                                base_value=base_val,
                                ours_value=ours_val,
                                theirs_value=theirs_val,
                            )
                            conflicts.append(conflict)
                            print(f"      >>> CONFLICT DETECTED! <<<")

    return conflicts


def main():
    test_dir = Path(__file__).parent / "test_prefabs"

    base_path = test_dir / "conflict_base.prefab"
    ours_path = test_dir / "conflict_ours.prefab"
    theirs_path = test_dir / "conflict_theirs.prefab"

    print("=" * 60)
    print("Merge Conflict Detection Test")
    print("=" * 60)

    print(f"\nLoading BASE: {base_path}")
    base_doc = load_unity_file(base_path, resolve_guids=False)

    print(f"Loading OURS: {ours_path}")
    ours_doc = load_unity_file(ours_path, resolve_guids=False)

    print(f"Loading THEIRS: {theirs_path}")
    theirs_doc = load_unity_file(theirs_path, resolve_guids=False)

    print("\n" + "=" * 60)
    print("Checking for conflicts...")
    print("=" * 60)

    conflicts = check_conflicts(base_doc, ours_doc, theirs_doc)

    print("\n" + "=" * 60)
    print(f"RESULT: Found {len(conflicts)} conflict(s)")
    print("=" * 60)

    for i, conflict in enumerate(conflicts, 1):
        print(f"\nConflict {i}:")
        print(f"  Path: {conflict.path}")
        print(f"  BASE:   {conflict.base_value}")
        print(f"  OURS:   {conflict.ours_value}")
        print(f"  THEIRS: {conflict.theirs_value}")

    if len(conflicts) == 0:
        print("\n[FAIL] Expected at least 1 conflict but found none!")
        return 1
    else:
        print("\n[PASS] Conflict detection is working!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
