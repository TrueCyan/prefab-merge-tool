"""
Unity GUID resolver - wrapper around unityflow's asset tracking.

Provides a simple interface for resolving GUIDs to asset names/paths
using unityflow's CachedGUIDIndex.
"""

from pathlib import Path
from typing import Callable, Optional

from unityflow.asset_tracker import (
    CachedGUIDIndex,
    GUIDIndex,
    find_unity_project_root,
)

# Progress callback type: (current, total, message) -> None
ProgressCallback = Callable[[int, int, str], None]


class GuidResolver:
    """
    Resolves Unity GUIDs to asset names using unityflow's CachedGUIDIndex.

    This is a thin wrapper providing a convenient interface for the prefab-diff-tool.
    """

    def __init__(self, project_root: Optional[Path] = None, auto_index: bool = True):
        """
        Initialize the resolver.

        Args:
            project_root: Unity project root path (containing Assets folder).
                         If None, will be detected from file paths.
            auto_index: If True, automatically index the project on first resolve.
        """
        self._project_root = project_root
        self._auto_index = auto_index
        self._cached_index: Optional[CachedGUIDIndex] = None
        self._index: Optional[GUIDIndex] = None

        if project_root:
            self._init_cached_index(project_root)

    @staticmethod
    def find_project_root(file_path: Path) -> Optional[Path]:
        """
        Find Unity project root by searching upward for Assets folder.

        Args:
            file_path: Path to a file within the Unity project

        Returns:
            Path to project root (parent of Assets folder), or None if not found
        """
        return find_unity_project_root(file_path)

    def _init_cached_index(self, project_root: Path) -> None:
        """Initialize the cached GUID index."""
        self._cached_index = CachedGUIDIndex(project_root)

    def set_project_root(self, project_root: Path, auto_index: bool = True) -> None:
        """Set project root and initialize cache.

        Args:
            project_root: Unity project root path.
            auto_index: If True, project will be indexed on first resolve.
        """
        if self._project_root != project_root:
            self._project_root = project_root
            self._auto_index = auto_index
            self._index = None
            self._init_cached_index(project_root)

    def index_project(
        self,
        progress_callback: Optional[ProgressCallback] = None,
        include_package_cache: bool = True,
    ) -> None:
        """
        Index the project for fast GUID lookup.

        Args:
            progress_callback: Optional callback for progress updates.
                              Called with (current, total, message).
            include_package_cache: If True, include Library/PackageCache
        """
        if not self._cached_index:
            if progress_callback:
                progress_callback(1, 1, "No project root set")
            return

        if progress_callback:
            progress_callback(0, 1, "인덱싱 중...")

        # Use unityflow's cached index
        self._index = self._cached_index.get_index(include_packages=include_package_cache)

        if progress_callback:
            count = len(self._index) if self._index else 0
            progress_callback(1, 1, f"인덱싱 완료: {count:,}개 에셋")

    def is_indexed(self) -> bool:
        """Check if the project has been indexed."""
        return self._index is not None

    def resolve(self, guid: str) -> Optional[str]:
        """
        Resolve a GUID to an asset name.

        Args:
            guid: The GUID to resolve (32 hex characters)

        Returns:
            Asset name if found, None otherwise
        """
        if not guid:
            return None

        guid = guid.lower()

        # Auto-index if needed
        if self._index is None and self._auto_index and self._cached_index:
            self._index = self._cached_index.get_index(include_packages=True)

        if self._index is None:
            return None

        path = self._index.get_path(guid)
        if path:
            # Return just the filename (with extension for non-scripts)
            if path.suffix and path.suffix != ".cs":
                return path.name
            return path.stem

        return None

    def resolve_path(self, guid: str) -> Optional[Path]:
        """
        Resolve a GUID to full asset file path.

        Args:
            guid: The GUID to resolve

        Returns:
            Full path to the asset file, or None if not found
        """
        if not guid:
            return None

        guid = guid.lower()

        # Auto-index if needed
        if self._index is None and self._auto_index and self._cached_index:
            self._index = self._cached_index.get_index(include_packages=True)

        if self._index is None:
            return None

        return self._index.get_path(guid)

    def resolve_with_type(self, guid: str) -> tuple[Optional[str], Optional[str]]:
        """
        Resolve a GUID to asset name and type.

        Args:
            guid: The GUID to resolve

        Returns:
            Tuple of (asset_name, asset_type) or (None, None)
        """
        name = self.resolve(guid)
        if name:
            return name, self._guess_asset_type(name)
        return None, None

    def _guess_asset_type(self, filename: str) -> str:
        """Guess asset type from filename extension."""
        ext_map = {
            ".cs": "Script",
            ".prefab": "Prefab",
            ".unity": "Scene",
            ".mat": "Material",
            ".png": "Texture",
            ".jpg": "Texture",
            ".jpeg": "Texture",
            ".tga": "Texture",
            ".psd": "Texture",
            ".fbx": "Model",
            ".obj": "Model",
            ".blend": "Model",
            ".anim": "Animation",
            ".controller": "AnimatorController",
            ".asset": "Asset",
            ".shader": "Shader",
            ".cginc": "ShaderInclude",
            ".compute": "ComputeShader",
            ".mp3": "AudioClip",
            ".wav": "AudioClip",
            ".ogg": "AudioClip",
            ".ttf": "Font",
            ".otf": "Font",
            ".fontsettings": "Font",
            ".json": "TextAsset",
            ".txt": "TextAsset",
            ".xml": "TextAsset",
            ".bytes": "TextAsset",
            ".renderTexture": "RenderTexture",
            ".lighting": "LightingSettings",
            ".physicMaterial": "PhysicMaterial",
            ".physicsMaterial2D": "PhysicsMaterial2D",
            ".mixer": "AudioMixer",
            ".mask": "AvatarMask",
            ".overrideController": "AnimatorOverrideController",
            ".flare": "Flare",
            ".giparams": "LightmapParameters",
            ".cubemap": "Cubemap",
            ".guiskin": "GUISkin",
            ".spriteatlas": "SpriteAtlas",
            ".terrainlayer": "TerrainLayer",
            ".brush": "Brush",
            ".signal": "Signal",
            ".playable": "Playable",
        }

        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
            return ext_map.get(ext, "Asset")

        return "Asset"

    def clear_cache(self) -> None:
        """Clear the GUID cache."""
        self._index = None
        if self._cached_index:
            self._cached_index.invalidate()

    def close(self) -> None:
        """Cleanup resources."""
        self._index = None
        self._cached_index = None


# Global resolver instance for convenience
_global_resolver: Optional[GuidResolver] = None


def get_resolver() -> GuidResolver:
    """Get the global GUID resolver instance."""
    global _global_resolver
    if _global_resolver is None:
        _global_resolver = GuidResolver()
    return _global_resolver


def resolve_guid(guid: str, project_root: Optional[Path] = None) -> Optional[str]:
    """
    Convenience function to resolve a GUID.

    Args:
        guid: The GUID to resolve
        project_root: Optional project root path

    Returns:
        Asset name if found, None otherwise
    """
    resolver = get_resolver()
    if project_root:
        resolver.set_project_root(project_root)
    return resolver.resolve(guid)
