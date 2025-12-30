"""
Unity GUID resolver for finding asset names from GUIDs.

Searches Unity project .meta files to resolve GUIDs to actual asset names.
Uses SQLite-based persistent cache for fast incremental updates.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from prefab_diff_tool.utils.cache import GuidCache

# Progress callback type: (current, total, message) -> None
ProgressCallback = Callable[[int, int, str], None]


class GuidResolver:
    """
    Resolves Unity GUIDs to asset names by searching .meta files.

    Uses SQLite-based persistent cache for:
    - Fast startup from cached data
    - Incremental updates (only process changed files)
    - Cross-session persistence
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
        self._db_cache: Optional[GuidCache] = None

        # Initialize persistent cache if project root is set
        if project_root:
            self._init_db_cache(project_root)

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

    def _init_db_cache(self, project_root: Path) -> None:
        """Initialize SQLite-based persistent cache."""
        try:
            self._db_cache = GuidCache(project_root)
            # Load existing cache into memory for O(1) lookups
            cached_entries = self._db_cache.get_all()
            for guid, (name, path) in cached_entries.items():
                self._cache[guid] = name
                self._path_cache[guid] = path
            if cached_entries:
                self._indexed = True  # Mark as indexed if we have cached data
        except Exception:
            # Fall back to memory-only cache if DB fails
            self._db_cache = None

    def set_project_root(self, project_root: Path, auto_index: bool = True) -> None:
        """Set project root and initialize cache.

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

            # Initialize persistent cache
            self._init_db_cache(project_root)

    def index_project(
        self,
        progress_callback: Optional[ProgressCallback] = None,
        max_workers: Optional[int] = None,
        force_full: bool = False,
    ) -> None:
        """
        Index .meta files for fast GUID lookup with incremental updates.

        Uses SQLite cache to only process changed/new files since last index.

        Args:
            progress_callback: Optional callback for progress updates.
                              Called with (current, total, message).
            max_workers: Max threads for parallel processing.
                        Defaults to min(32, cpu_count + 4).
            force_full: If True, ignore cache and do full re-index.
        """
        if not self._project_root:
            if progress_callback:
                progress_callback(1, 1, "No project root set")
            return

        # If already indexed in memory and not forcing full re-index, skip
        if self._indexed and not force_full and self._cache:
            if progress_callback:
                progress_callback(1, 1, f"Using cached index: {len(self._cache)} assets")
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

        total_files = len(meta_files)
        if total_files == 0:
            self._indexed = True
            if progress_callback:
                progress_callback(1, 1, "No .meta files found")
            return

        # Determine which files need processing (incremental update)
        files_to_process: list[Path] = meta_files
        guids_to_delete: list[str] = []

        if self._db_cache and not force_full:
            if progress_callback:
                progress_callback(0, 0, "Checking for changes...")

            files_to_process, guids_to_delete = self._db_cache.get_stale_entries(meta_files)

            # Delete stale entries
            if guids_to_delete:
                self._db_cache.delete_guids(guids_to_delete)
                for guid in guids_to_delete:
                    self._cache.pop(guid, None)
                    self._path_cache.pop(guid, None)

        total = len(files_to_process)
        if total == 0:
            self._indexed = True
            if progress_callback:
                progress_callback(1, 1, f"Cache up-to-date: {len(self._cache)} assets")
            return

        if progress_callback:
            if total < total_files:
                progress_callback(0, total, f"Updating {total} changed assets...")
            else:
                progress_callback(0, total, f"Indexing {total} assets...")

        # Use parallel processing for file I/O
        if max_workers is None:
            max_workers = min(32, (os.cpu_count() or 1) + 4)

        processed = 0
        batch_size = max(1, total // 100)  # Update progress ~100 times
        new_entries: list[tuple[str, str, Path, Path, float]] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_path = {
                executor.submit(self._process_meta_file_with_mtime, meta_file): meta_file
                for meta_file in files_to_process
            }

            # Process results as they complete
            for future in as_completed(future_to_path):
                result = future.result()
                if result:
                    guid, asset_name, asset_path, meta_path, mtime = result
                    self._cache[guid] = asset_name
                    self._path_cache[guid] = asset_path
                    new_entries.append((guid, asset_name, asset_path, meta_path, mtime))

                processed += 1

                # Periodic progress callback
                if progress_callback and processed % batch_size == 0:
                    progress_callback(processed, total, f"Indexed {processed}/{total} assets")

        # Batch save to SQLite cache
        if self._db_cache and new_entries:
            self._db_cache.set_many(new_entries)
            self._db_cache.set_last_index_time()

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

    def _process_meta_file_with_mtime(
        self, meta_file: Path
    ) -> Optional[tuple[str, str, Path, Path, float]]:
        """Process a .meta file and return (guid, asset_name, asset_path, meta_path, mtime)."""
        try:
            mtime = meta_file.stat().st_mtime
            guid = self._extract_guid_from_meta(meta_file)
            if guid:
                asset_path = meta_file.with_suffix("")
                asset_name = asset_path.stem

                # Include extension for non-script assets
                if asset_path.suffix and asset_path.suffix != ".cs":
                    asset_name = asset_path.name

                return (guid, asset_name, asset_path, meta_file, mtime)
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
        """Clear the GUID cache (both memory and persistent)."""
        self._cache.clear()
        self._path_cache.clear()
        self._indexed = False
        if self._db_cache:
            self._db_cache.clear()

    def close(self) -> None:
        """Close database connection and cleanup resources."""
        if self._db_cache:
            self._db_cache.close()
            self._db_cache = None


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
