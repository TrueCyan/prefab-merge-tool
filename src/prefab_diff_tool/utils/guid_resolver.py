"""
Unity GUID resolver - wrapper around unityflow's asset tracking.

Provides a simple interface for resolving GUIDs to asset names/paths
using unityflow's CachedGUIDIndex.

Supports two modes:
1. Lazy mode (default): Query SQLite directly on each resolve() call.
   - Fast startup, no memory overhead
   - Good for viewing a single file with few GUID lookups
2. Full index mode: Load all GUIDs into memory first.
   - Slower startup (~5s for 180k assets)
   - Fast repeated lookups
   - Good for batch operations
"""

import logging
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Callable, Optional

from unityflow.asset_tracker import (
    CachedGUIDIndex,
    GUIDIndex,
    find_unity_project_root,
    CACHE_DIR_NAME,
    CACHE_DB_NAME,
)

# Set up logging
logger = logging.getLogger(__name__)

# Progress callback type: (current, total, message) -> None
ProgressCallback = Callable[[int, int, str], None]


class GuidResolver:
    """
    Resolves Unity GUIDs to asset names using unityflow's CachedGUIDIndex.

    This is a thin wrapper providing a convenient interface for the prefab-diff-tool.

    Supports two modes:
    - Lazy mode (default): Query SQLite directly per resolve() call
    - Full index mode: Load all GUIDs into memory (set auto_index=True and call index_project())
    """

    def __init__(self, project_root: Optional[Path] = None, auto_index: bool = False):
        """
        Initialize the resolver.

        Args:
            project_root: Unity project root path (containing Assets folder).
                         If None, will be detected from file paths.
            auto_index: If True, load full index on first resolve (slow for large projects).
                       If False (default), use lazy SQLite queries (fast startup).
        """
        self._project_root = project_root
        self._auto_index = auto_index
        self._cached_index: Optional[CachedGUIDIndex] = None
        self._index: Optional[GUIDIndex] = None
        self._db_path: Optional[Path] = None
        self._db_lock = Lock()
        # Persistent SQLite connection (reused to avoid frequent open/close)
        self._db_conn: Optional[sqlite3.Connection] = None
        # In-memory cache for recently resolved GUIDs (LRU-like)
        self._resolve_cache: dict[str, Optional[str]] = {}
        self._cache_max_size = 1000

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
        """Initialize the cached GUID index and DB path."""
        logger.debug(f"Initializing CachedGUIDIndex for: {project_root}")
        self._cached_index = CachedGUIDIndex(project_root)
        self._db_path = project_root / CACHE_DIR_NAME / CACHE_DB_NAME
        logger.debug(f"GUID cache DB path: {self._db_path}")

    def set_project_root(self, project_root: Path, auto_index: bool = False) -> None:
        """Set project root and initialize cache.

        Args:
            project_root: Unity project root path.
            auto_index: If True, load full index on first resolve (slow).
                       If False (default), use lazy SQLite queries (fast).
        """
        if self._project_root != project_root:
            logger.info(f"Setting project root: {project_root}")
            # Close existing connection when changing project
            self._close_db_connection()
            self._project_root = project_root
            self._auto_index = auto_index
            self._index = None
            self._resolve_cache.clear()
            self._init_cached_index(project_root)

    def _get_db_connection(self) -> Optional[sqlite3.Connection]:
        """Get or create persistent SQLite connection.

        Returns:
            SQLite connection, or None if DB doesn't exist
        """
        if self._db_conn is not None:
            return self._db_conn

        if not self._db_path or not self._db_path.exists():
            return None

        try:
            self._db_conn = sqlite3.connect(
                str(self._db_path),
                timeout=5.0,
                check_same_thread=False,  # Allow cross-thread access (we use lock)
            )
            logger.debug(f"Opened persistent DB connection: {self._db_path}")
            return self._db_conn
        except sqlite3.Error as e:
            logger.debug(f"Failed to open DB connection: {e}")
            return None

    def _close_db_connection(self) -> None:
        """Close the persistent SQLite connection."""
        if self._db_conn is not None:
            try:
                self._db_conn.close()
                logger.debug("Closed persistent DB connection")
            except sqlite3.Error:
                pass
            self._db_conn = None

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
            logger.warning("index_project called without project root")
            if progress_callback:
                progress_callback(1, 1, "No project root set")
            return

        if progress_callback:
            progress_callback(0, 1, "인덱싱 중...")

        # Wrap the progress callback to add message
        def unityflow_progress(current: int, total: int) -> None:
            if progress_callback:
                if total > 0:
                    progress_callback(current, total, f"인덱싱 중... {current:,}/{total:,}")
                else:
                    progress_callback(current, 1, "인덱싱 중...")

        # Use unityflow's cached index with progress callback
        logger.info(f"Starting index with include_packages={include_package_cache}")
        self._index = self._cached_index.get_index(
            include_packages=include_package_cache,
            progress_callback=unityflow_progress,
        )

        count = len(self._index) if self._index else 0
        logger.info(f"Indexing complete: {count} assets")

        if progress_callback:
            progress_callback(1, 1, f"인덱싱 완료: {count:,}개 에셋")

    def is_indexed(self) -> bool:
        """Check if the project has been indexed."""
        return self._index is not None

    def _query_db(self, guid: str) -> Optional[Path]:
        """Query the SQLite cache directly for a single GUID.

        Uses persistent connection to avoid frequent open/close overhead.

        Args:
            guid: The GUID to look up (already lowercased)

        Returns:
            Path to the asset, or None if not found
        """
        try:
            with self._db_lock:
                conn = self._get_db_connection()
                if conn is None:
                    return None

                cursor = conn.execute(
                    "SELECT path FROM guid_cache WHERE guid = ?",
                    (guid,)
                )
                row = cursor.fetchone()
                if row:
                    return Path(row[0])
        except sqlite3.Error as e:
            logger.debug(f"DB query error for GUID {guid[:8]}...: {e}")
            # Connection might be stale, close it so next call will reconnect
            self._close_db_connection()

        return None

    def _ensure_db_exists(self) -> bool:
        """Ensure the GUID cache database exists, creating if needed.

        Returns:
            True if DB exists or was created successfully
        """
        if self._db_path and self._db_path.exists():
            return True

        # Need to build the index first to create the DB
        if self._cached_index:
            logger.info("Building GUID cache (first run)...")
            self._index = self._cached_index.get_index(include_packages=True)
            count = len(self._index) if self._index else 0
            logger.info(f"GUID cache built: {count:,} entries")
            return self._db_path and self._db_path.exists()

        return False

    def resolve(self, guid: str) -> Optional[str]:
        """
        Resolve a GUID to an asset name.

        Uses lazy SQLite queries by default for fast startup.
        Falls back to full index if auto_index=True was set.

        Args:
            guid: The GUID to resolve (32 hex characters)

        Returns:
            Asset name if found, None otherwise
        """
        if not guid:
            return None

        original_guid = guid
        guid = guid.lower()

        # Check in-memory cache first (O(1))
        if guid in self._resolve_cache:
            return self._resolve_cache[guid]

        # If full index is loaded, use it
        if self._index is not None:
            path = self._index.get_path(guid)
            if path:
                result = self._path_to_name(path)
                self._add_to_cache(guid, result)
                return result
            self._add_to_cache(guid, None)
            return None

        # Auto-index if requested (slow startup mode)
        if self._auto_index and self._cached_index:
            logger.debug("Auto-indexing on first resolve (slow mode)")
            self._index = self._cached_index.get_index(include_packages=True)
            return self.resolve(original_guid)  # Retry with index

        # Lazy mode: query SQLite directly (fast startup)
        if not self._ensure_db_exists():
            logger.warning(f"Cannot resolve GUID {guid[:8]}...: no cache available")
            return None

        path = self._query_db(guid)
        if path:
            result = self._path_to_name(path)
            logger.debug(f"Resolved GUID {guid[:8]}... -> {result}")
            self._add_to_cache(guid, result)
            return result

        # Not found
        logger.debug(f"Failed to resolve GUID: {original_guid}")
        self._add_to_cache(guid, None)
        return None

    def _path_to_name(self, path: Path) -> str:
        """Convert a path to a display name."""
        if path.suffix and path.suffix != ".cs":
            return path.name
        return path.stem

    def _add_to_cache(self, guid: str, name: Optional[str]) -> None:
        """Add a resolved GUID to the in-memory cache."""
        # Simple cache eviction when too large
        if len(self._resolve_cache) >= self._cache_max_size:
            # Remove oldest entries (first 100)
            keys_to_remove = list(self._resolve_cache.keys())[:100]
            for key in keys_to_remove:
                del self._resolve_cache[key]

        self._resolve_cache[guid] = name

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

        # If full index is loaded, use it
        if self._index is not None:
            return self._index.get_path(guid)

        # Auto-index if requested
        if self._auto_index and self._cached_index:
            self._index = self._cached_index.get_index(include_packages=True)
            return self._index.get_path(guid) if self._index else None

        # Lazy mode: query SQLite directly
        if not self._ensure_db_exists():
            return None

        path = self._query_db(guid)
        # DB stores relative paths - convert to absolute using project root
        if path and self._project_root and not path.is_absolute():
            path = self._project_root / path
        return path

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

    def get_index_stats(self) -> dict:
        """Get statistics about the current index for debugging."""
        if self._index is None:
            return {"indexed": False, "count": 0}

        # Count by extension
        ext_counts: dict[str, int] = {}
        for path in self._index.guid_to_path.values():
            ext = path.suffix.lower() if path.suffix else "(no ext)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

        return {
            "indexed": True,
            "count": len(self._index),
            "by_extension": ext_counts,
        }

    def clear_cache(self) -> None:
        """Clear the GUID cache."""
        self._index = None
        self._close_db_connection()
        if self._cached_index:
            self._cached_index.invalidate()

    def close(self) -> None:
        """Cleanup resources."""
        self._close_db_connection()
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
