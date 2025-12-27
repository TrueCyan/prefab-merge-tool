"""
Unity GUID resolver for finding asset names from GUIDs.

Searches Unity project .meta files to resolve GUIDs to actual asset names.
"""

import re
from pathlib import Path
from typing import Optional


class GuidResolver:
    """
    Resolves Unity GUIDs to asset names by searching .meta files.

    Caches results for performance.
    """

    # Pattern to extract GUID from .meta file content
    GUID_PATTERN = re.compile(r"guid:\s*([a-fA-F0-9]{32})")

    def __init__(self, project_root: Optional[Path] = None):
        """
        Initialize the resolver.

        Args:
            project_root: Unity project root path (containing Assets folder).
                         If None, will be detected from file paths.
        """
        self._project_root = project_root
        self._cache: dict[str, Optional[str]] = {}  # guid -> asset name
        self._indexed = False

    @staticmethod
    def find_project_root(file_path: Path) -> Optional[Path]:
        """
        Find Unity project root by searching upward for Assets folder.

        Args:
            file_path: Path to a file within the Unity project

        Returns:
            Path to project root (parent of Assets folder), or None if not found
        """
        current = file_path.resolve()

        # If it's a file, start from parent
        if current.is_file():
            current = current.parent

        # Search upward for Assets folder
        while current != current.parent:  # Stop at filesystem root
            assets_path = current / "Assets"
            project_settings = current / "ProjectSettings"

            # Unity project has both Assets and ProjectSettings folders
            if assets_path.is_dir() and project_settings.is_dir():
                return current

            # Also check if current folder IS the Assets folder
            if current.name == "Assets" and current.is_dir():
                parent = current.parent
                if (parent / "ProjectSettings").is_dir():
                    return parent

            current = current.parent

        return None

    def set_project_root(self, project_root: Path) -> None:
        """Set project root and clear cache."""
        if self._project_root != project_root:
            self._project_root = project_root
            self._cache.clear()
            self._indexed = False

    def index_project(self) -> None:
        """
        Index all .meta files in the project for fast GUID lookup.

        Call this once after setting project root for better performance
        when resolving many GUIDs.
        """
        if not self._project_root or self._indexed:
            return

        assets_path = self._project_root / "Assets"
        if not assets_path.exists():
            return

        # Also search Packages folder for package assets
        search_paths = [assets_path]
        packages_path = self._project_root / "Packages"
        if packages_path.exists():
            search_paths.append(packages_path)

        for search_path in search_paths:
            for meta_file in search_path.rglob("*.meta"):
                try:
                    guid = self._extract_guid_from_meta(meta_file)
                    if guid:
                        # Get asset name (filename without .meta)
                        asset_path = meta_file.with_suffix("")
                        asset_name = asset_path.stem

                        # Include extension for non-script assets
                        if asset_path.suffix and asset_path.suffix != ".cs":
                            asset_name = asset_path.name

                        self._cache[guid] = asset_name
                except (OSError, IOError):
                    continue

        self._indexed = True

    def _extract_guid_from_meta(self, meta_path: Path) -> Optional[str]:
        """Extract GUID from a .meta file."""
        try:
            # Only read first few lines - GUID is always near the top
            with open(meta_path, "r", encoding="utf-8") as f:
                content = f.read(500)  # GUID is in first ~100 bytes typically

            match = self.GUID_PATTERN.search(content)
            if match:
                return match.group(1).lower()
        except (OSError, IOError, UnicodeDecodeError):
            pass
        return None

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

        # Check cache first
        if guid in self._cache:
            return self._cache[guid]

        # If not indexed and we have a project root, try to find it
        if not self._indexed and self._project_root:
            # Do a targeted search instead of full index
            result = self._search_for_guid(guid)
            self._cache[guid] = result
            return result

        return None

    def _search_for_guid(self, guid: str) -> Optional[str]:
        """Search for a specific GUID in meta files."""
        if not self._project_root:
            return None

        assets_path = self._project_root / "Assets"
        if not assets_path.exists():
            return None

        # Search in Assets and Packages
        search_paths = [assets_path]
        packages_path = self._project_root / "Packages"
        if packages_path.exists():
            search_paths.append(packages_path)

        for search_path in search_paths:
            for meta_file in search_path.rglob("*.meta"):
                try:
                    file_guid = self._extract_guid_from_meta(meta_file)
                    if file_guid == guid:
                        asset_path = meta_file.with_suffix("")
                        asset_name = asset_path.stem

                        # Include extension for non-script assets
                        if asset_path.suffix and asset_path.suffix != ".cs":
                            asset_name = asset_path.name

                        return asset_name
                except (OSError, IOError):
                    continue

        return None

    def resolve_with_type(self, guid: str) -> tuple[Optional[str], Optional[str]]:
        """
        Resolve a GUID to asset name and type.

        Args:
            guid: The GUID to resolve

        Returns:
            Tuple of (asset_name, asset_type) or (None, None)
        """
        if not guid:
            return None, None

        guid = guid.lower()

        # Check if already resolved
        if guid in self._cache:
            name = self._cache[guid]
            if name:
                return name, self._guess_asset_type(name)
            return None, None

        # Search for it
        if self._project_root:
            assets_path = self._project_root / "Assets"
            search_paths = [assets_path] if assets_path.exists() else []
            packages_path = self._project_root / "Packages"
            if packages_path.exists():
                search_paths.append(packages_path)

            for search_path in search_paths:
                for meta_file in search_path.rglob("*.meta"):
                    try:
                        file_guid = self._extract_guid_from_meta(meta_file)
                        if file_guid == guid:
                            asset_path = meta_file.with_suffix("")
                            asset_name = asset_path.stem
                            asset_type = self._guess_asset_type(asset_path.name)

                            # Cache the name
                            if asset_path.suffix and asset_path.suffix != ".cs":
                                self._cache[guid] = asset_path.name
                            else:
                                self._cache[guid] = asset_name

                            return asset_name, asset_type
                    except (OSError, IOError):
                        continue

        self._cache[guid] = None
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

        # Get extension
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
            return ext_map.get(ext, "Asset")

        return "Asset"

    def clear_cache(self) -> None:
        """Clear the GUID cache."""
        self._cache.clear()
        self._indexed = False


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
