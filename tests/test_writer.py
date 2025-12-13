"""Tests for the merge result writer."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from prefab_diff_tool.core.writer import (
    MergeResultWriter,
    write_merge_result,
    perform_text_merge,
)
from prefab_diff_tool.core.unity_model import (
    MergeConflict,
    MergeResult,
    ConflictResolution,
    UnityDocument,
)


class TestMergeResultWriter:
    """Tests for MergeResultWriter class."""

    def test_writer_initialization(self):
        """Test writer can be instantiated."""
        writer = MergeResultWriter(normalize=False)
        assert writer._normalize is False
        assert writer._normalizer is None

    def test_writer_with_normalizer(self):
        """Test writer with normalization enabled."""
        writer = MergeResultWriter(normalize=True)
        assert writer._normalize is True
        assert writer._normalizer is not None

    def test_apply_text_resolutions_use_ours(self):
        """Test applying USE_OURS resolution."""
        writer = MergeResultWriter(normalize=False)

        content = """some content
<<<<<<< ours
value_from_ours
=======
value_from_theirs
>>>>>>> theirs
more content"""

        conflicts = [
            MergeConflict(
                path="test.path",
                ours_value="value_from_ours",
                theirs_value="value_from_theirs",
                resolution=ConflictResolution.USE_OURS,
            )
        ]

        result = writer._apply_text_resolutions(content, conflicts)

        assert "value_from_ours" in result
        assert "<<<<<<< ours" not in result
        assert ">>>>>>> theirs" not in result

    def test_apply_text_resolutions_use_theirs(self):
        """Test applying USE_THEIRS resolution."""
        writer = MergeResultWriter(normalize=False)

        content = """<<<<<<< ours
ours_value
=======
theirs_value
>>>>>>> theirs"""

        conflicts = [
            MergeConflict(
                path="test.path",
                ours_value="ours_value",
                theirs_value="theirs_value",
                resolution=ConflictResolution.USE_THEIRS,
            )
        ]

        result = writer._apply_text_resolutions(content, conflicts)

        assert "theirs_value" in result


class TestTextMerge:
    """Tests for text-based merge functionality."""

    def test_write_text_merge_no_conflicts(self):
        """Test text merge with no conflicts."""
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "base.prefab"
            ours = Path(tmpdir) / "ours.prefab"
            theirs = Path(tmpdir) / "theirs.prefab"
            output = Path(tmpdir) / "output.prefab"

            # Create test files with same content
            base.write_text("line1\nline2\nline3")
            ours.write_text("line1\nline2\nline3")
            theirs.write_text("line1\nline2\nline3")

            writer = MergeResultWriter(normalize=False)
            success, count = writer.write_text_merge(
                base, ours, theirs, output
            )

            assert success is True
            assert count == 0
            assert output.exists()

    def test_write_text_merge_ours_only_change(self):
        """Test text merge with only ours modified."""
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "base.prefab"
            ours = Path(tmpdir) / "ours.prefab"
            theirs = Path(tmpdir) / "theirs.prefab"
            output = Path(tmpdir) / "output.prefab"

            base.write_text("line1\nline2\nline3")
            ours.write_text("line1\nmodified\nline3")
            theirs.write_text("line1\nline2\nline3")

            success, count = perform_text_merge(
                base, ours, theirs, output, normalize=False
            )

            assert success is True
            assert "modified" in output.read_text()

    def test_write_text_merge_with_conflict(self):
        """Test text merge with conflict."""
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "base.prefab"
            ours = Path(tmpdir) / "ours.prefab"
            theirs = Path(tmpdir) / "theirs.prefab"
            output = Path(tmpdir) / "output.prefab"

            base.write_text("line1\nline2\nline3")
            ours.write_text("line1\nours_change\nline3")
            theirs.write_text("line1\ntheirs_change\nline3")

            success, count = perform_text_merge(
                base, ours, theirs, output, normalize=False
            )

            assert success is False  # Has conflict
            assert count > 0


class TestConflictResolution:
    """Tests for conflict resolution handling."""

    def test_conflict_unresolved(self):
        """Test unresolved conflict state."""
        conflict = MergeConflict(
            path="Test/Path.Transform.m_LocalPosition.x",
            base_value=0.0,
            ours_value=1.0,
            theirs_value=2.0,
        )

        assert conflict.is_resolved is False
        assert conflict.resolution == ConflictResolution.UNRESOLVED

    def test_conflict_resolved_ours(self):
        """Test conflict resolved with ours."""
        conflict = MergeConflict(
            path="Test/Path.Transform.m_LocalPosition.x",
            base_value=0.0,
            ours_value=1.0,
            theirs_value=2.0,
            resolution=ConflictResolution.USE_OURS,
            resolved_value=1.0,
        )

        assert conflict.is_resolved is True
        assert conflict.resolved_value == 1.0

    def test_conflict_resolved_theirs(self):
        """Test conflict resolved with theirs."""
        conflict = MergeConflict(
            path="Test/Path.Transform.m_LocalPosition.x",
            base_value=0.0,
            ours_value=1.0,
            theirs_value=2.0,
            resolution=ConflictResolution.USE_THEIRS,
            resolved_value=2.0,
        )

        assert conflict.is_resolved is True
        assert conflict.resolved_value == 2.0


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_perform_text_merge(self):
        """Test perform_text_merge convenience function."""
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "base.prefab"
            ours = Path(tmpdir) / "ours.prefab"
            theirs = Path(tmpdir) / "theirs.prefab"
            output = Path(tmpdir) / "output.prefab"

            # Create test files
            base.write_text("content")
            ours.write_text("content")
            theirs.write_text("content")

            success, count = perform_text_merge(
                base, ours, theirs, output, normalize=False
            )

            assert success is True
            assert count == 0
            assert output.exists()
