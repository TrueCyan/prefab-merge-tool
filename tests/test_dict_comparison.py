"""
Test script to verify how dict/property comparison works.
"""

# Simulate the property values as they would be loaded from prefab files
base_val = {"x": 0, "y": 0, "z": 0}
ours_val = {"x": 10, "y": 0, "z": 0}
theirs_val = {"x": 20, "y": 0, "z": 0}

print("=== Dictionary Comparison Test ===")
print(f"BASE:   {base_val}")
print(f"OURS:   {ours_val}")
print(f"THEIRS: {theirs_val}")
print()

ours_changed = ours_val != base_val
theirs_changed = theirs_val != base_val
values_differ = ours_val != theirs_val

print(f"OURS changed from BASE: {ours_changed}")
print(f"THEIRS changed from BASE: {theirs_changed}")
print(f"OURS != THEIRS: {values_differ}")
print()

if ours_changed and theirs_changed and values_differ:
    print("[PASS] This SHOULD be detected as a conflict!")
else:
    print("[FAIL] This should have been a conflict but wasn't detected")

# Now test with floats (potential precision issues)
print("\n=== Float Comparison Test ===")
base_val_f = {"x": 0.0, "y": 0.0, "z": 0.0}
ours_val_f = {"x": 10.0, "y": 0.0, "z": 0.0}
theirs_val_f = {"x": 20.0, "y": 0.0, "z": 0.0}

print(f"BASE:   {base_val_f}")
print(f"OURS:   {ours_val_f}")
print(f"THEIRS: {theirs_val_f}")

ours_changed_f = ours_val_f != base_val_f
theirs_changed_f = theirs_val_f != base_val_f
values_differ_f = ours_val_f != theirs_val_f

print(f"OURS changed from BASE: {ours_changed_f}")
print(f"THEIRS changed from BASE: {theirs_changed_f}")
print(f"OURS != THEIRS: {values_differ_f}")

if ours_changed_f and theirs_changed_f and values_differ_f:
    print("[PASS] Float comparison works!")
else:
    print("[FAIL] Float comparison failed")
