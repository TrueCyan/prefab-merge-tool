"""
Detailed test for merge conflict detection logic.
Simulates various merge scenarios.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DiffStatus(Enum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


@dataclass
class UnityProperty:
    name: str
    value: Any
    path: str
    diff_status: DiffStatus = DiffStatus.UNCHANGED


@dataclass
class UnityComponent:
    file_id: str
    type_name: str
    properties: list[UnityProperty] = field(default_factory=list)
    diff_status: DiffStatus = DiffStatus.UNCHANGED


@dataclass
class UnityGameObject:
    file_id: str
    name: str
    components: list[UnityComponent] = field(default_factory=list)
    diff_status: DiffStatus = DiffStatus.UNCHANGED

    def get_path(self) -> str:
        return self.name


@dataclass
class MergeConflict:
    path: str
    base_value: Optional[Any] = None
    ours_value: Optional[Any] = None
    theirs_value: Optional[Any] = None


def check_component_conflicts(
    go_path: str,
    base_comp: UnityComponent,
    ours_comp: UnityComponent,
    theirs_comp: UnityComponent,
) -> list[MergeConflict]:
    """Check for property-level conflicts in a component."""
    conflicts = []

    base_props = {p.path: p for p in base_comp.properties}
    ours_props = {p.path: p for p in ours_comp.properties}
    theirs_props = {p.path: p for p in theirs_comp.properties}

    all_prop_paths = set(base_props.keys()) | set(ours_props.keys()) | set(theirs_props.keys())

    for prop_path in all_prop_paths:
        base_prop = base_props.get(prop_path)
        ours_prop = ours_props.get(prop_path)
        theirs_prop = theirs_props.get(prop_path)

        base_val = base_prop.value if base_prop else None
        ours_val = ours_prop.value if ours_prop else None
        theirs_val = theirs_prop.value if theirs_prop else None

        # Check for conflict: both changed from base to different values
        ours_changed = ours_val != base_val
        theirs_changed = theirs_val != base_val

        if ours_changed and theirs_changed and ours_val != theirs_val:
            comp_name = ours_comp.type_name
            conflicts.append(MergeConflict(
                path=f"{go_path}.{comp_name}.{prop_path}",
                base_value=base_val,
                ours_value=ours_val,
                theirs_value=theirs_val,
            ))

    return conflicts


def create_transform_component(file_id: str, position: dict) -> UnityComponent:
    """Helper to create a Transform component."""
    return UnityComponent(
        file_id=file_id,
        type_name="Transform",
        properties=[
            UnityProperty(name="m_LocalPosition", value=position, path="m_LocalPosition"),
            UnityProperty(name="m_LocalRotation", value={"x": 0, "y": 0, "z": 0, "w": 1}, path="m_LocalRotation"),
            UnityProperty(name="m_LocalScale", value={"x": 1, "y": 1, "z": 1}, path="m_LocalScale"),
        ]
    )


def test_basic_conflict():
    """Test: BASE=0, OURS=10, THEIRS=20 → Conflict"""
    print("\n=== Test: Basic Conflict (0 → 10 vs 0 → 20) ===")

    base_comp = create_transform_component("4000", {"x": 0, "y": 0, "z": 0})
    ours_comp = create_transform_component("4000", {"x": 10, "y": 0, "z": 0})
    theirs_comp = create_transform_component("4000", {"x": 20, "y": 0, "z": 0})

    conflicts = check_component_conflicts("TestObject", base_comp, ours_comp, theirs_comp)

    print(f"Found {len(conflicts)} conflict(s)")
    for c in conflicts:
        print(f"  - {c.path}")
        print(f"    BASE:   {c.base_value}")
        print(f"    OURS:   {c.ours_value}")
        print(f"    THEIRS: {c.theirs_value}")

    if len(conflicts) == 1:
        print("[PASS] Conflict detected!")
        return True
    else:
        print("[FAIL] Expected 1 conflict")
        return False


def test_same_change_no_conflict():
    """Test: BASE=0, OURS=10, THEIRS=10 → No conflict (same change)"""
    print("\n=== Test: Same Change (0 → 10 vs 0 → 10) ===")

    base_comp = create_transform_component("4000", {"x": 0, "y": 0, "z": 0})
    ours_comp = create_transform_component("4000", {"x": 10, "y": 0, "z": 0})
    theirs_comp = create_transform_component("4000", {"x": 10, "y": 0, "z": 0})

    conflicts = check_component_conflicts("TestObject", base_comp, ours_comp, theirs_comp)

    print(f"Found {len(conflicts)} conflict(s)")

    if len(conflicts) == 0:
        print("[PASS] No conflict (same change on both sides)")
        return True
    else:
        print("[FAIL] Should not have conflicts for identical changes")
        return False


def test_only_ours_changed():
    """Test: BASE=0, OURS=10, THEIRS=0 → No conflict (only ours changed)"""
    print("\n=== Test: Only Ours Changed (0 → 10 vs unchanged) ===")

    base_comp = create_transform_component("4000", {"x": 0, "y": 0, "z": 0})
    ours_comp = create_transform_component("4000", {"x": 10, "y": 0, "z": 0})
    theirs_comp = create_transform_component("4000", {"x": 0, "y": 0, "z": 0})

    conflicts = check_component_conflicts("TestObject", base_comp, ours_comp, theirs_comp)

    print(f"Found {len(conflicts)} conflict(s)")

    if len(conflicts) == 0:
        print("[PASS] No conflict (only one side changed)")
        return True
    else:
        print("[FAIL] Should not have conflicts when only one side changed")
        return False


def test_only_theirs_changed():
    """Test: BASE=0, OURS=0, THEIRS=20 → No conflict (only theirs changed)"""
    print("\n=== Test: Only Theirs Changed (unchanged vs 0 → 20) ===")

    base_comp = create_transform_component("4000", {"x": 0, "y": 0, "z": 0})
    ours_comp = create_transform_component("4000", {"x": 0, "y": 0, "z": 0})
    theirs_comp = create_transform_component("4000", {"x": 20, "y": 0, "z": 0})

    conflicts = check_component_conflicts("TestObject", base_comp, ours_comp, theirs_comp)

    print(f"Found {len(conflicts)} conflict(s)")

    if len(conflicts) == 0:
        print("[PASS] No conflict (only one side changed)")
        return True
    else:
        print("[FAIL] Should not have conflicts when only one side changed")
        return False


def test_component_id_mismatch():
    """Test: Different component file_ids → No comparison happens"""
    print("\n=== Test: Component ID Mismatch ===")

    base_comp = create_transform_component("4001", {"x": 0, "y": 0, "z": 0})
    ours_comp = create_transform_component("4002", {"x": 10, "y": 0, "z": 0})  # Different ID!
    theirs_comp = create_transform_component("4003", {"x": 20, "y": 0, "z": 0})  # Different ID!

    # In the real code, components are matched by file_id first
    # If IDs don't match, check_component_conflicts is never called

    # Simulating the matching logic:
    base_comps = {base_comp.file_id: base_comp}
    ours_comps = {ours_comp.file_id: ours_comp}
    theirs_comps = {theirs_comp.file_id: theirs_comp}

    all_comp_ids = set(base_comps.keys()) | set(ours_comps.keys()) | set(theirs_comps.keys())

    conflicts_found = []
    for comp_id in all_comp_ids:
        b = base_comps.get(comp_id)
        o = ours_comps.get(comp_id)
        t = theirs_comps.get(comp_id)

        if b and o and t:
            # Only check conflicts when ALL THREE have the component
            conflicts_found.extend(check_component_conflicts("TestObject", b, o, t))

    print(f"Matching IDs: {all_comp_ids}")
    print(f"Found {len(conflicts_found)} conflict(s)")

    # Since IDs are all different, no conflicts are found
    if len(conflicts_found) == 0:
        print("[WARNING] No conflicts detected due to file_id mismatch!")
        print("  Base:   file_id=4001")
        print("  Ours:   file_id=4002")
        print("  Theirs: file_id=4003")
        print("  Components don't match, so no comparison happens!")
        return False
    else:
        return True


def test_float_precision():
    """Test: Float precision issues"""
    print("\n=== Test: Float Precision ===")

    # This can happen if Unity saves floats differently
    base_comp = create_transform_component("4000", {"x": 0.0, "y": 0.0, "z": 0.0})
    ours_comp = create_transform_component("4000", {"x": 0.1 + 0.2, "y": 0.0, "z": 0.0})  # 0.30000000000000004
    theirs_comp = create_transform_component("4000", {"x": 0.3, "y": 0.0, "z": 0.0})

    print(f"OURS x value:   {0.1 + 0.2}")
    print(f"THEIRS x value: {0.3}")
    print(f"Are they equal? {(0.1 + 0.2) == 0.3}")

    conflicts = check_component_conflicts("TestObject", base_comp, ours_comp, theirs_comp)

    print(f"Found {len(conflicts)} conflict(s)")

    # Due to float precision, 0.1+0.2 != 0.3 in Python
    if len(conflicts) > 0:
        print("[WARNING] Float precision caused false conflict!")
        return False
    else:
        print("[PASS] No false conflict from float precision")
        return True


def test_multiple_properties():
    """Test: Multiple properties, only one conflicts"""
    print("\n=== Test: Multiple Properties (1 conflict out of 3) ===")

    base_comp = UnityComponent(
        file_id="4000",
        type_name="Transform",
        properties=[
            UnityProperty(name="m_LocalPosition", value={"x": 0, "y": 0, "z": 0}, path="m_LocalPosition"),
            UnityProperty(name="m_LocalRotation", value={"x": 0, "y": 0, "z": 0, "w": 1}, path="m_LocalRotation"),
            UnityProperty(name="m_LocalScale", value={"x": 1, "y": 1, "z": 1}, path="m_LocalScale"),
        ]
    )

    ours_comp = UnityComponent(
        file_id="4000",
        type_name="Transform",
        properties=[
            UnityProperty(name="m_LocalPosition", value={"x": 10, "y": 0, "z": 0}, path="m_LocalPosition"),  # Changed to 10
            UnityProperty(name="m_LocalRotation", value={"x": 0, "y": 0, "z": 0, "w": 1}, path="m_LocalRotation"),  # Unchanged
            UnityProperty(name="m_LocalScale", value={"x": 2, "y": 2, "z": 2}, path="m_LocalScale"),  # Changed to 2
        ]
    )

    theirs_comp = UnityComponent(
        file_id="4000",
        type_name="Transform",
        properties=[
            UnityProperty(name="m_LocalPosition", value={"x": 20, "y": 0, "z": 0}, path="m_LocalPosition"),  # Changed to 20 - CONFLICT!
            UnityProperty(name="m_LocalRotation", value={"x": 0, "y": 0, "z": 0, "w": 1}, path="m_LocalRotation"),  # Unchanged
            UnityProperty(name="m_LocalScale", value={"x": 2, "y": 2, "z": 2}, path="m_LocalScale"),  # Same as ours - NO CONFLICT
        ]
    )

    conflicts = check_component_conflicts("TestObject", base_comp, ours_comp, theirs_comp)

    print(f"Found {len(conflicts)} conflict(s)")
    for c in conflicts:
        print(f"  - {c.path}")

    if len(conflicts) == 1 and "m_LocalPosition" in conflicts[0].path:
        print("[PASS] Only position conflict detected, scale auto-merged")
        return True
    else:
        print("[FAIL] Expected exactly 1 conflict for m_LocalPosition")
        return False


def main():
    print("=" * 60)
    print("Merge Conflict Detection Logic Tests")
    print("=" * 60)

    results = []
    results.append(("Basic Conflict", test_basic_conflict()))
    results.append(("Same Change (No Conflict)", test_same_change_no_conflict()))
    results.append(("Only Ours Changed", test_only_ours_changed()))
    results.append(("Only Theirs Changed", test_only_theirs_changed()))
    results.append(("Component ID Mismatch", test_component_id_mismatch()))
    results.append(("Float Precision", test_float_precision()))
    results.append(("Multiple Properties", test_multiple_properties()))

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    for name, result in results:
        status = "[PASS]" if result else "[FAIL/WARN]"
        print(f"  {status} {name}")

    # List known issues
    print("\n" + "=" * 60)
    print("Known Issues")
    print("=" * 60)
    print("1. Component file_id mismatch: If Unity regenerates IDs, comparison fails")
    print("2. Float precision: 0.1+0.2 != 0.3 can cause false conflicts")
    print("3. No fallback: If IDs don't match, no alternative matching strategy")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
