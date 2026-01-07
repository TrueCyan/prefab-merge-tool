"""Tests for the Unity file loader."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from typing import Any

from prefab_diff_tool.core.loader import UnityFileLoader, load_unity_file
from prefab_diff_tool.core.unity_model import (
    UnityDocument,
    UnityGameObject,
    UnityComponent,
)


@dataclass
class MockComponentInfo:
    """Mock unityflow ComponentInfo."""
    file_id: int
    class_id: int
    class_name: str
    data: dict
    is_on_stripped_object: bool = False
    script_guid: str = None
    script_name: str = None
    modifications: list = None


@dataclass
class MockHierarchyNode:
    """Mock unityflow HierarchyNode."""
    file_id: int
    name: str
    transform_id: int = 0
    is_ui: bool = False
    parent: Any = None
    children: list = None
    components: list = None
    is_prefab_instance: bool = False
    source_guid: str = ""
    source_file_id: int = 0
    is_stripped: bool = False
    prefab_instance_id: int = 0
    modifications: list = None
    is_from_nested_prefab: bool = False
    nested_prefab_loaded: bool = False
    _document: Any = None
    _hierarchy: Any = None

    def __post_init__(self):
        if self.children is None:
            self.children = []
        if self.components is None:
            self.components = []
        if self.modifications is None:
            self.modifications = []


class MockHierarchy:
    """Mock unityflow Hierarchy."""
    def __init__(self, root_objects=None):
        self.root_objects = root_objects or []


class TestUnityFileLoader:
    """Tests for UnityFileLoader."""

    def test_loader_initialization(self):
        """Test loader can be instantiated."""
        loader = UnityFileLoader()
        assert loader._raw_doc is None

    @patch("prefab_diff_tool.core.loader.find_unity_project_root")
    @patch("prefab_diff_tool.core.loader.build_hierarchy")
    @patch("prefab_diff_tool.core.loader.UnityYAMLDocument")
    def test_load_empty_document(self, mock_doc_class, mock_build_hierarchy, mock_find_root):
        """Test loading a document with no entries."""
        mock_doc = MagicMock()
        mock_doc.objects = []
        mock_doc_class.load.return_value = mock_doc
        mock_build_hierarchy.return_value = MockHierarchy([])
        mock_find_root.return_value = None

        loader = UnityFileLoader()
        doc = loader.load(Path("/fake/path.prefab"))

        assert isinstance(doc, UnityDocument)
        assert doc.file_path == "/fake/path.prefab"
        assert doc.root_objects == []
        assert doc.object_count == 0

    @patch("prefab_diff_tool.core.loader.find_unity_project_root")
    @patch("prefab_diff_tool.core.loader.build_hierarchy")
    @patch("prefab_diff_tool.core.loader.UnityYAMLDocument")
    def test_load_single_gameobject(self, mock_doc_class, mock_build_hierarchy, mock_find_root):
        """Test loading a document with a single GameObject."""
        mock_doc = MagicMock()
        mock_doc.objects = []
        mock_doc_class.load.return_value = mock_doc
        mock_find_root.return_value = None

        # Create mock hierarchy node
        root_node = MockHierarchyNode(
            file_id=12345,
            name="TestObject",
            components=[],
        )
        mock_build_hierarchy.return_value = MockHierarchy([root_node])

        loader = UnityFileLoader()
        doc = loader.load(Path("/fake/test.prefab"))

        assert doc.object_count == 1
        assert "12345" in doc.all_objects
        assert doc.all_objects["12345"].name == "TestObject"

    @patch("prefab_diff_tool.core.loader.find_unity_project_root")
    @patch("prefab_diff_tool.core.loader.build_hierarchy")
    @patch("prefab_diff_tool.core.loader.UnityYAMLDocument")
    def test_load_gameobject_with_component(self, mock_doc_class, mock_build_hierarchy, mock_find_root):
        """Test loading a GameObject with a Transform component."""
        mock_doc = MagicMock()
        mock_doc.objects = []
        mock_doc_class.load.return_value = mock_doc
        mock_find_root.return_value = None

        # Create mock component and node
        transform_comp = MockComponentInfo(
            file_id=101,
            class_id=4,
            class_name="Transform",
            data={
                "m_LocalPosition": {"x": 0, "y": 0, "z": 0},
            }
        )
        root_node = MockHierarchyNode(
            file_id=100,
            name="Player",
            components=[transform_comp],
        )
        mock_build_hierarchy.return_value = MockHierarchy([root_node])

        loader = UnityFileLoader()
        doc = loader.load(Path("/fake/player.prefab"))

        assert doc.object_count == 1
        player = doc.all_objects["100"]
        assert player.name == "Player"
        assert len(player.components) == 1
        assert player.components[0].type_name == "Transform"


class TestLoadUnityFileFunction:
    """Tests for the convenience function."""

    @patch("prefab_diff_tool.core.loader.find_unity_project_root")
    @patch("prefab_diff_tool.core.loader.build_hierarchy")
    @patch("prefab_diff_tool.core.loader.UnityYAMLDocument")
    def test_load_unity_file_returns_document(self, mock_doc_class, mock_build_hierarchy, mock_find_root):
        """Test that load_unity_file returns a UnityDocument."""
        mock_doc = MagicMock()
        mock_doc.objects = []
        mock_doc_class.load.return_value = mock_doc
        mock_build_hierarchy.return_value = MockHierarchy([])
        mock_find_root.return_value = None

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
