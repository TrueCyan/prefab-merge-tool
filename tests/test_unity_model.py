"""
Tests for core Unity model.
"""

import pytest

from prefab_diff_tool.core.unity_model import (
    DiffStatus,
    UnityProperty,
    UnityComponent,
    UnityGameObject,
    UnityDocument,
    DiffSummary,
)


class TestDiffStatus:
    def test_values(self):
        assert DiffStatus.UNCHANGED.value == "unchanged"
        assert DiffStatus.ADDED.value == "added"
        assert DiffStatus.REMOVED.value == "removed"
        assert DiffStatus.MODIFIED.value == "modified"


class TestUnityProperty:
    def test_creation(self):
        prop = UnityProperty(
            name="x",
            value=1.5,
            path="m_LocalPosition.x",
        )
        assert prop.name == "x"
        assert prop.value == 1.5
        assert prop.path == "m_LocalPosition.x"
        assert prop.diff_status == DiffStatus.UNCHANGED
        assert prop.old_value is None
    
    def test_modified_property(self):
        prop = UnityProperty(
            name="x",
            value=10.0,
            path="m_LocalPosition.x",
            diff_status=DiffStatus.MODIFIED,
            old_value=5.0,
        )
        assert prop.diff_status == DiffStatus.MODIFIED
        assert prop.old_value == 5.0


class TestUnityComponent:
    def test_creation(self):
        comp = UnityComponent(
            file_id="12345",
            type_name="Transform",
        )
        assert comp.file_id == "12345"
        assert comp.type_name == "Transform"
        assert comp.properties == []
        assert comp.diff_status == DiffStatus.UNCHANGED
    
    def test_get_property(self):
        prop = UnityProperty(name="x", value=1.0, path="m_LocalPosition.x")
        comp = UnityComponent(
            file_id="12345",
            type_name="Transform",
            properties=[prop],
        )
        
        assert comp.get_property("m_LocalPosition.x") == prop
        assert comp.get_property("nonexistent") is None


class TestUnityGameObject:
    def test_creation(self):
        go = UnityGameObject(
            file_id="100",
            name="Player",
        )
        assert go.file_id == "100"
        assert go.name == "Player"
        assert go.components == []
        assert go.children == []
        assert go.parent is None
    
    def test_get_path_root(self):
        go = UnityGameObject(file_id="100", name="Player")
        assert go.get_path() == "Player"
    
    def test_get_path_nested(self):
        parent = UnityGameObject(file_id="100", name="Player")
        child = UnityGameObject(file_id="200", name="Body", parent=parent)
        grandchild = UnityGameObject(file_id="300", name="Head", parent=child)
        
        assert parent.get_path() == "Player"
        assert child.get_path() == "Player/Body"
        assert grandchild.get_path() == "Player/Body/Head"
    
    def test_iter_descendants(self):
        parent = UnityGameObject(file_id="100", name="Parent")
        child1 = UnityGameObject(file_id="200", name="Child1")
        child2 = UnityGameObject(file_id="300", name="Child2")
        grandchild = UnityGameObject(file_id="400", name="GrandChild")
        
        parent.children = [child1, child2]
        child1.children = [grandchild]
        
        descendants = list(parent.iter_descendants())
        assert len(descendants) == 3
        assert child1 in descendants
        assert child2 in descendants
        assert grandchild in descendants


class TestUnityDocument:
    def test_creation(self):
        doc = UnityDocument(file_path="test.prefab")
        assert doc.file_path == "test.prefab"
        assert doc.root_objects == []
        assert doc.object_count == 0
        assert doc.component_count == 0


class TestDiffSummary:
    def test_totals(self):
        summary = DiffSummary(
            added_objects=2,
            removed_objects=1,
            modified_objects=3,
            added_components=4,
            removed_components=2,
            modified_properties=10,
        )
        
        assert summary.added == 6   # 2 + 4
        assert summary.removed == 3  # 1 + 2
        assert summary.modified == 13  # 3 + 10
        assert summary.total == 22
