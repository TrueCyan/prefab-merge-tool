"""
Unity GUID resolver for finding asset names from GUIDs.

Searches Unity project .meta files to resolve GUIDs to actual asset names.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

# Progress callback type: (current, total, message) -> None
ProgressCallback = Callable[[int, int, str], None]


class GuidResolver:
    """
    Resolves Unity GUIDs to asset names by searching .meta files.

    Caches results for performance. Supports auto-indexing for bulk lookups.
    """

    # Pattern to extract GUID from .meta file content
    GUID_PATTERN = re.compile(r"guid:\s*([a-fA-F0-9]{32})")

    def __init__(self, project_root: Optional[Path] = None, auto_index: bool = True):
        """
        Initialize the resolver.

        Args:
            project_root: Unity project root path (containing Assets folder).
                         If None, will be detected from file paths.
            auto_index: If True, automatically index the project on first resolve.
                       This is faster for multiple lookups. Default is True.
        """
        self._project_root = project_root
        self._cache: dict[str, Optional[str]] = {}  # guid -> asset name
        self._path_cache: dict[str, Optional[Path]] = {}  # guid -> full asset path
        self._indexed = False
        self._auto_index = auto_index

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

    def set_project_root(self, project_root: Path, auto_index: bool = True) -> None:
        """Set project root and clear cache.

        Args:
            project_root: Unity project root path.
            auto_index: If True, project will be indexed on first resolve.
        """
        if self._project_root != project_root:
            self._project_root = project_root
            self._cache.clear()
            self._path_cache.clear()
            self._indexed = False
            self._auto_index = auto_index

    def index_project(
        self,
        progress_callback: Optional[ProgressCallback] = None,
        max_workers: Optional[int] = None,
    ) -> None:
        """
        Index all .meta files in the project for fast GUID lookup.

        Call this once after setting project root for better performance
        when resolving many GUIDs.

        Args:
            progress_callback: Optional callback for progress updates.
                              Called with (current, total, message).
            max_workers: Max threads for parallel processing.
                        Defaults to min(32, cpu_count + 4).
        """
        if not self._project_root or self._indexed:
            if progress_callback:
                progress_callback(1, 1, "Already indexed")
            return

        assets_path = self._project_root / "Assets"
        if not assets_path.exists():
            if progress_callback:
                progress_callback(1, 1, "No Assets folder")
            return

        # Collect all .meta file paths first (fast operation)
        if progress_callback:
            progress_callback(0, 0, "Scanning for .meta files...")

        meta_files: list[Path] = []
        search_paths = [assets_path]
        packages_path = self._project_root / "Packages"
        if packages_path.exists():
            search_paths.append(packages_path)

        for search_path in search_paths:
            # Use os.walk for faster directory traversal
            for root, _, files in os.walk(search_path):
                for filename in files:
                    if filename.endswith(".meta"):
                        meta_files.append(Path(root) / filename)

        total = len(meta_files)
        if total == 0:
            self._indexed = True
            if progress_callback:
                progress_callback(1, 1, "No .meta files found")
            return

        if progress_callback:
            progress_callback(0, total, f"Indexing {total} assets...")

        # Use parallel processing for file I/O
        if max_workers is None:
            max_workers = min(32, (os.cpu_count() or 1) + 4)

        processed = 0
        batch_size = max(1, total // 100)  # Update progress ~100 times

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_path = {
                executor.submit(self._process_meta_file, meta_file): meta_file
                for meta_file in meta_files
            }

            # Process results as they complete
            for future in as_completed(future_to_path):
                result = future.result()
                if result:
                    guid, asset_name, asset_path = result
                    self._cache[guid] = asset_name
                    self._path_cache[guid] = asset_path

                processed += 1

                # Periodic progress callback
                if progress_callback and processed % batch_size == 0:
                    progress_callback(processed, total, f"Indexed {processed}/{total} assets")

        self._indexed = True

        if progress_callback:
            progress_callback(total, total, f"Indexing complete: {len(self._cache)} assets")

    def _process_meta_file(self, meta_file: Path) -> Optional[tuple[str, str, Path]]:
        """Process a single .meta file and return (guid, asset_name, asset_path) or None."""
        try:
            guid = self._extract_guid_from_meta(meta_file)
            if guid:
                asset_path = meta_file.with_suffix("")
                asset_name = asset_path.stem

                # Include extension for non-script assets
                if asset_path.suffix and asset_path.suffix != ".cs":
                    asset_name = asset_path.name

                return (guid, asset_name, asset_path)
        except OSError:
            pass
        return None

    def get_meta_file_count(self) -> Optional[int]:
        """
        Get estimated count of .meta files in the project.
        Returns None if project root is not set.
        """
        if not self._project_root:
            return None

        count = 0
        assets_path = self._project_root / "Assets"
        if assets_path.exists():
            for root, _, files in os.walk(assets_path):
                count += sum(1 for f in files if f.endswith(".meta"))

        packages_path = self._project_root / "Packages"
        if packages_path.exists():
            for root, _, files in os.walk(packages_path):
                count += sum(1 for f in files if f.endswith(".meta"))

        return count

    def is_indexed(self) -> bool:
        """Check if the project has been indexed."""
        return self._indexed

    def _extract_guid_from_meta(self, meta_path: Path) -> Optional[str]:
        """Extract GUID from a .meta file."""
        try:
            # Only read first few lines - GUID is always near the top
            with open(meta_path, encoding="utf-8") as f:
                content = f.read(500)  # GUID is in first ~100 bytes typically

            match = self.GUID_PATTERN.search(content)
            if match:
                return match.group(1).lower()
        except (OSError, UnicodeDecodeError):
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

        # If not indexed and we have a project root
        if not self._indexed and self._project_root:
            # Auto-index the entire project for faster bulk lookups
            if self._auto_index:
                self.index_project()
                # After indexing, check cache again
                if guid in self._cache:
                    return self._cache[guid]
            else:
                # Do a targeted search (slower for multiple lookups)
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
                except OSError:
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
        # Reuse resolve() to leverage caching and avoid duplicate rglob scans
        name = self.resolve(guid)
        if name:
            return name, self._guess_asset_type(name)
        return None, None

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

        # Check path cache first
        if guid in self._path_cache:
            return self._path_cache[guid]

        # Ensure indexed (this will also populate path cache)
        self.resolve(guid)

        return self._path_cache.get(guid)

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
        self._path_cache.clear()
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
