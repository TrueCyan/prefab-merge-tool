"""Tests for the Unity file loader."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from prefab_diff_tool.core.loader import UnityFileLoader, load_unity_file
from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
)


class MockEntry:
    """Mock prefab-tool entry."""

    def __init__(self, class_name: str, anchor: str, **kwargs):
        self.__class__.__name__ = class_name
        self.anchor = anchor
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestUnityFileLoader:
    """Tests for UnityFileLoader."""

    def test_loader_initialization(self):
        """Test loader can be instantiated."""
        loader = UnityFileLoader()
        assert loader._raw_doc is None
        assert loader._entries_by_id == {}

    @patch("prefab_diff_tool.core.loader.UnityYAMLDocument")
    def test_load_empty_document(self, mock_doc_class):
        """Test loading a document with no entries."""
        mock_doc = MagicMock()
        mock_doc.entries = []
        mock_doc_class.load.return_value = mock_doc

        loader = UnityFileLoader()
        doc = loader.load(Path("/fake/path.prefab"))

        assert isinstance(doc, UnityDocument)
        assert doc.file_path == "/fake/path.prefab"
        assert doc.root_objects == []
        assert doc.object_count == 0

    @patch("prefab_diff_tool.core.loader.UnityYAMLDocument")
    def test_load_single_gameobject(self, mock_doc_class):
        """Test loading a document with a single GameObject."""
        # Create mock entries
        go_entry = MockEntry(
            "GameObject",
            "12345",
            m_Name="TestObject",
            m_Layer=0,
            m_TagString="Untagged",
            m_IsActive=1,
        )

        mock_doc = MagicMock()
        mock_doc.entries = [go_entry]
        mock_doc_class.load.return_value = mock_doc

        loader = UnityFileLoader()
        doc = loader.load(Path("/fake/test.prefab"))

        assert doc.object_count == 1
        assert "12345" in doc.all_objects
        assert doc.all_objects["12345"].name == "TestObject"

    @patch("prefab_diff_tool.core.loader.UnityYAMLDocument")
    def test_load_gameobject_with_component(self, mock_doc_class):
        """Test loading a GameObject with a Transform component."""
        go_entry = MockEntry(
            "GameObject",
            "100",
            m_Name="Player",
            m_Layer=0,
            m_TagString="Player",
            m_IsActive=1,
        )

        transform_entry = MockEntry(
            "Transform",
            "101",
            m_GameObject={"fileID": 100},
            m_LocalPosition={"x": 0, "y": 0, "z": 0},
            m_Father={"fileID": 0},
            m_Children=[],
        )

        mock_doc = MagicMock()
        mock_doc.entries = [go_entry, transform_entry]
        mock_doc_class.load.return_value = mock_doc

        loader = UnityFileLoader()
        doc = loader.load(Path("/fake/player.prefab"))

        assert doc.object_count == 1
        player = doc.all_objects["100"]
        assert player.name == "Player"
        assert player.tag == "Player"
        assert len(player.components) == 1
        assert player.components[0].type_name == "Transform"


class TestLoadUnityFileFunction:
    """Tests for the convenience function."""

    @patch("prefab_diff_tool.core.loader.UnityYAMLDocument")
    def test_load_unity_file_returns_document(self, mock_doc_class):
        """Test that load_unity_file returns a UnityDocument."""
        mock_doc = MagicMock()
        mock_doc.entries = []
        mock_doc_class.load.return_value = mock_doc

        result = load_unity_file(Path("/test.prefab"))

        assert isinstance(result, UnityDocument)


class TestTreeModel:
    """Tests for the tree model."""

    def test_hierarchy_model_initialization(self):
        """Test HierarchyTreeModel can be instantiated."""
        from prefab_diff_tool.models.tree_model import HierarchyTreeModel

        model = HierarchyTreeModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 1

    def test_set_empty_document(self):
        """Test setting an empty document."""
        from prefab_diff_tool.models.tree_model import HierarchyTreeModel

        model = HierarchyTreeModel()
        doc = UnityDocument(file_path="/test.prefab")

        model.set_document(doc)

        assert model.rowCount() == 0

    def test_set_document_with_objects(self):
        """Test setting a document with objects."""
        from prefab_diff_tool.models.tree_model import HierarchyTreeModel

        doc = UnityDocument(file_path="/test.prefab")
        go = UnityGameObject(file_id="1", name="TestObject")
        doc.root_objects.append(go)
        doc.all_objects["1"] = go

        model = HierarchyTreeModel()
        model.set_document(doc)

        assert model.rowCount() == 1
