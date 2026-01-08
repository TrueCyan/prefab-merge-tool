"""
Test script for verifying diff detection logic.
Simulates the _perform_diff() logic with mock data.
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
    old_value: Optional[Any] = None


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
class Change:
    path: str
    status: DiffStatus
    left_value: Optional[Any] = None
    right_value: Optional[Any] = None
    object_id: Optional[str] = None
    component_type: Optional[str] = None


def perform_diff(left_objects: dict, right_objects: dict) -> list[Change]:
    """Simplified version of _perform_diff() for testing."""
    changes = []

    # Find added objects
    for file_id, go in right_objects.items():
        if file_id not in left_objects:
            go.diff_status = DiffStatus.ADDED
            changes.append(Change(
                path=go.get_path(),
                status=DiffStatus.ADDED,
                right_value=go.name,
                object_id=file_id,
            ))

    # Find removed objects
    for file_id, go in left_objects.items():
        if file_id not in right_objects:
            go.diff_status = DiffStatus.REMOVED
            changes.append(Change(
                path=go.get_path(),
                status=DiffStatus.REMOVED,
                left_value=go.name,
                object_id=file_id,
            ))

    # Compare existing objects
    for file_id in left_objects.keys() & right_objects.keys():
        left_go = left_objects[file_id]
        right_go = right_objects[file_id]

        left_comps = {c.file_id: c for c in left_go.components}
        right_comps = {c.file_id: c for c in right_go.components}

        has_changes = False
        for comp_id in left_comps.keys() & right_comps.keys():
            left_comp = left_comps[comp_id]
            right_comp = right_comps[comp_id]

            left_props = {p.path: p for p in left_comp.properties}
            right_props = {p.path: p for p in right_comp.properties}

            for prop_path in left_props.keys() | right_props.keys():
                left_prop = left_props.get(prop_path)
                right_prop = right_props.get(prop_path)

                if left_prop and right_prop:
                    if left_prop.value != right_prop.value:
                        right_prop.diff_status = DiffStatus.MODIFIED
                        right_prop.old_value = left_prop.value
                        left_comp.diff_status = DiffStatus.MODIFIED
                        right_comp.diff_status = DiffStatus.MODIFIED
                        has_changes = True

                        changes.append(Change(
                            path=f"{right_go.get_path()}.{right_comp.type_name}.{prop_path}",
                            status=DiffStatus.MODIFIED,
                            left_value=left_prop.value,
                            right_value=right_prop.value,
                            object_id=file_id,
                            component_type=right_comp.type_name,
                        ))
                elif left_prop and not right_prop:
                    # Property removed
                    changes.append(Change(
                        path=f"{left_go.get_path()}.{left_comp.type_name}.{prop_path}",
                        status=DiffStatus.REMOVED,
                        left_value=left_prop.value,
                        object_id=file_id,
                        component_type=left_comp.type_name,
                    ))
                    has_changes = True
                elif right_prop and not left_prop:
                    # Property added
                    changes.append(Change(
                        path=f"{right_go.get_path()}.{right_comp.type_name}.{prop_path}",
                        status=DiffStatus.ADDED,
                        right_value=right_prop.value,
                        object_id=file_id,
                        component_type=right_comp.type_name,
                    ))
                    has_changes = True

        if has_changes:
            left_go.diff_status = DiffStatus.MODIFIED
            right_go.diff_status = DiffStatus.MODIFIED

    return changes


def test_scalar_property_change():
    """Test detecting scalar property changes."""
    print("\n=== Test: Scalar Property Change ===")

    # LEFT: position.x = 0
    left_transform = UnityComponent(
        file_id="4000000000000000",
        type_name="Transform",
        properties=[
            UnityProperty(name="m_LocalPosition", value={"x": 0, "y": 0, "z": 0}, path="m_LocalPosition"),
        ]
    )
    left_go = UnityGameObject(
        file_id="1000000000000000",
        name="TestObject",
        components=[left_transform]
    )

    # RIGHT: position.x = 10
    right_transform = UnityComponent(
        file_id="4000000000000000",
        type_name="Transform",
        properties=[
            UnityProperty(name="m_LocalPosition", value={"x": 10, "y": 0, "z": 0}, path="m_LocalPosition"),
        ]
    )
    right_go = UnityGameObject(
        file_id="1000000000000000",
        name="TestObject",
        components=[right_transform]
    )

    left_objects = {left_go.file_id: left_go}
    right_objects = {right_go.file_id: right_go}

    changes = perform_diff(left_objects, right_objects)

    print(f"Found {len(changes)} change(s)")
    for change in changes:
        print(f"  - {change.path}: {change.left_value} -> {change.right_value}")

    if len(changes) == 1:
        print("[PASS] Scalar property change detected!")
        return True
    else:
        print("[FAIL] Expected 1 change, got", len(changes))
        return False


def test_nested_dict_property_change():
    """Test detecting nested dict property changes (like m_LocalPosition.x)."""
    print("\n=== Test: Nested Dict Property (Flattened) ===")

    # Simulating if properties were flattened like m_LocalPosition.x, m_LocalPosition.y, etc.
    left_transform = UnityComponent(
        file_id="4000000000000000",
        type_name="Transform",
        properties=[
            UnityProperty(name="x", value=0, path="m_LocalPosition.x"),
            UnityProperty(name="y", value=0, path="m_LocalPosition.y"),
            UnityProperty(name="z", value=0, path="m_LocalPosition.z"),
        ]
    )
    left_go = UnityGameObject(
        file_id="1000000000000000",
        name="TestObject",
        components=[left_transform]
    )

    right_transform = UnityComponent(
        file_id="4000000000000000",
        type_name="Transform",
        properties=[
            UnityProperty(name="x", value=10, path="m_LocalPosition.x"),  # Changed!
            UnityProperty(name="y", value=0, path="m_LocalPosition.y"),
            UnityProperty(name="z", value=0, path="m_LocalPosition.z"),
        ]
    )
    right_go = UnityGameObject(
        file_id="1000000000000000",
        name="TestObject",
        components=[right_transform]
    )

    left_objects = {left_go.file_id: left_go}
    right_objects = {right_go.file_id: right_go}

    changes = perform_diff(left_objects, right_objects)

    print(f"Found {len(changes)} change(s)")
    for change in changes:
        print(f"  - {change.path}: {change.left_value} -> {change.right_value}")

    if len(changes) == 1 and "m_LocalPosition.x" in changes[0].path:
        print("[PASS] Nested property change detected!")
        return True
    else:
        print("[FAIL] Expected 1 change for m_LocalPosition.x")
        return False


def test_added_object():
    """Test detecting added objects."""
    print("\n=== Test: Added Object ===")

    left_go = UnityGameObject(file_id="1000", name="ExistingObject", components=[])
    new_go = UnityGameObject(file_id="2000", name="NewObject", components=[])

    left_objects = {left_go.file_id: left_go}
    right_objects = {left_go.file_id: left_go, new_go.file_id: new_go}

    changes = perform_diff(left_objects, right_objects)

    print(f"Found {len(changes)} change(s)")
    for change in changes:
        print(f"  - {change.status.value}: {change.path}")

    added = [c for c in changes if c.status == DiffStatus.ADDED]
    if len(added) == 1 and added[0].path == "NewObject":
        print("[PASS] Added object detected!")
        return True
    else:
        print("[FAIL] Expected 1 added object")
        return False


def test_removed_object():
    """Test detecting removed objects."""
    print("\n=== Test: Removed Object ===")

    existing_go = UnityGameObject(file_id="1000", name="ExistingObject", components=[])
    removed_go = UnityGameObject(file_id="2000", name="RemovedObject", components=[])

    left_objects = {existing_go.file_id: existing_go, removed_go.file_id: removed_go}
    right_objects = {existing_go.file_id: existing_go}

    changes = perform_diff(left_objects, right_objects)

    print(f"Found {len(changes)} change(s)")
    for change in changes:
        print(f"  - {change.status.value}: {change.path}")

    removed = [c for c in changes if c.status == DiffStatus.REMOVED]
    if len(removed) == 1 and removed[0].path == "RemovedObject":
        print("[PASS] Removed object detected!")
        return True
    else:
        print("[FAIL] Expected 1 removed object")
        return False


def test_component_mismatch():
    """Test when components have different file_ids (won't be compared)."""
    print("\n=== Test: Component File ID Mismatch ===")

    # Same GameObject, but Transform has different file_ids
    left_transform = UnityComponent(
        file_id="4000000000000001",  # Different!
        type_name="Transform",
        properties=[
            UnityProperty(name="m_LocalPosition", value={"x": 0, "y": 0, "z": 0}, path="m_LocalPosition"),
        ]
    )
    left_go = UnityGameObject(
        file_id="1000000000000000",
        name="TestObject",
        components=[left_transform]
    )

    right_transform = UnityComponent(
        file_id="4000000000000002",  # Different!
        type_name="Transform",
        properties=[
            UnityProperty(name="m_LocalPosition", value={"x": 10, "y": 0, "z": 0}, path="m_LocalPosition"),
        ]
    )
    right_go = UnityGameObject(
        file_id="1000000000000000",
        name="TestObject",
        components=[right_transform]
    )

    left_objects = {left_go.file_id: left_go}
    right_objects = {right_go.file_id: right_go}

    changes = perform_diff(left_objects, right_objects)

    print(f"Found {len(changes)} change(s)")
    for change in changes:
        print(f"  - {change.path}: {change.left_value} -> {change.right_value}")

    # With different component file_ids, the change won't be detected!
    if len(changes) == 0:
        print("[WARNING] No changes detected - component file_ids don't match!")
        print("  This is a potential issue if Unity regenerates component file_ids")
        return False
    else:
        print("[PASS] Changes detected despite different component file_ids")
        return True


def main():
    print("=" * 60)
    print("Diff Logic Verification Tests")
    print("=" * 60)

    results = []
    results.append(("Scalar Property Change", test_scalar_property_change()))
    results.append(("Nested Dict Property", test_nested_dict_property_change()))
    results.append(("Added Object", test_added_object()))
    results.append(("Removed Object", test_removed_object()))
    results.append(("Component File ID Mismatch", test_component_mismatch()))

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
