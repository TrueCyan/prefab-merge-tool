"""
SQLite-based cache for GUID resolver and other persistent data.

Stores GUID → asset mappings with mtime-based invalidation for fast incremental updates.
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Callable, Iterator, Optional

# Progress callback type: (current, total, message) -> None
ProgressCallback = Callable[[int, int, str], None]


class GuidCache:
    """
    SQLite-based cache for GUID → asset name/path mappings.

    Features:
    - Persistent storage in project root as .prefab_merge_cache.db
    - mtime-based invalidation for incremental updates
    - Thread-safe with connection pooling
    - Automatic schema migration
    """

    CACHE_FILENAME = ".prefab_merge_cache.db"
    SCHEMA_VERSION = 1

    def __init__(self, project_root: Path):
        """
        Initialize cache for the given project root.

        Args:
            project_root: Unity project root directory
        """
        self._project_root = project_root
        self._cache_path = project_root / self.CACHE_FILENAME
        self._lock = Lock()
        self._connection: Optional[sqlite3.Connection] = None
        self._init_database()

    def _init_database(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Create tables if not exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guid_cache (
                    guid TEXT PRIMARY KEY,
                    asset_name TEXT NOT NULL,
                    asset_path TEXT NOT NULL,
                    meta_path TEXT NOT NULL,
                    mtime REAL NOT NULL
                )
            """)

            # Create indices for fast lookup
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_meta_path
                ON guid_cache(meta_path)
            """)

            # Check and update schema version
            cursor.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )

            conn.commit()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with thread safety."""
        with self._lock:
            if self._connection is None:
                self._connection = sqlite3.connect(
                    str(self._cache_path),
                    check_same_thread=False,
                    timeout=30.0,
                )
                # Enable WAL mode for better concurrent read/write
                self._connection.execute("PRAGMA journal_mode=WAL")
                self._connection.execute("PRAGMA synchronous=NORMAL")
                self._connection.execute("PRAGMA cache_size=10000")

            yield self._connection

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None

    def get(self, guid: str) -> Optional[tuple[str, Path]]:
        """
        Get cached asset info for a GUID.

        Args:
            guid: The GUID to lookup

        Returns:
            Tuple of (asset_name, asset_path) or None if not cached
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT asset_name, asset_path FROM guid_cache WHERE guid = ?",
                (guid.lower(),),
            )
            row = cursor.fetchone()
            if row:
                return row[0], Path(row[1])
            return None

    def set(
        self,
        guid: str,
        asset_name: str,
        asset_path: Path,
        meta_path: Path,
        mtime: float,
    ) -> None:
        """
        Store asset info for a GUID.

        Args:
            guid: The GUID
            asset_name: Display name of the asset
            asset_path: Full path to the asset file
            meta_path: Path to the .meta file
            mtime: Modification time of the .meta file
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO guid_cache
                (guid, asset_name, asset_path, meta_path, mtime)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guid.lower(), asset_name, str(asset_path), str(meta_path), mtime),
            )
            conn.commit()

    def set_many(
        self,
        entries: list[tuple[str, str, Path, Path, float]],
    ) -> None:
        """
        Batch insert multiple entries.

        Args:
            entries: List of (guid, asset_name, asset_path, meta_path, mtime) tuples
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT OR REPLACE INTO guid_cache
                (guid, asset_name, asset_path, meta_path, mtime)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (guid.lower(), name, str(apath), str(mpath), mtime)
                    for guid, name, apath, mpath, mtime in entries
                ],
            )
            conn.commit()

    def get_all(self) -> dict[str, tuple[str, Path]]:
        """
        Get all cached entries.

        Returns:
            Dict mapping GUID to (asset_name, asset_path)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT guid, asset_name, asset_path FROM guid_cache")
            return {
                row[0]: (row[1], Path(row[2]))
                for row in cursor.fetchall()
            }

    def get_stale_entries(
        self,
        meta_files: list[Path],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> tuple[list[Path], list[str]]:
        """
        Find which meta files need re-indexing.

        Compares current file mtimes with cached mtimes.

        Args:
            meta_files: List of .meta file paths to check
            progress_callback: Optional callback for progress updates (current, total, message)

        Returns:
            Tuple of (files_to_update, guids_to_delete):
            - files_to_update: .meta files that have changed or are new
            - guids_to_delete: GUIDs whose .meta files no longer exist
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get all cached meta paths and their mtimes
            cursor.execute("SELECT meta_path, mtime, guid FROM guid_cache")
            cached = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

        # Find files that need updating
        files_to_update: list[Path] = []
        current_paths = set()
        total = len(meta_files)

        # Counter-based progress updates (avoid time.time() overhead)
        update_interval = max(1, total // 100)  # ~100 updates

        for i, meta_path in enumerate(meta_files):
            path_str = str(meta_path)
            current_paths.add(path_str)

            try:
                current_mtime = meta_path.stat().st_mtime
            except OSError:
                continue

            cached_entry = cached.get(path_str)
            if cached_entry is None:
                # New file
                files_to_update.append(meta_path)
            elif cached_entry[0] < current_mtime:
                # Modified file
                files_to_update.append(meta_path)

            # Counter-based progress updates
            if progress_callback and i % update_interval == 0:
                progress_callback(i + 1, total, f"변경 확인 중... {i + 1:,}/{total:,}")

        # Find deleted files
        guids_to_delete: list[str] = []
        for path_str, (_, guid) in cached.items():
            if path_str not in current_paths:
                guids_to_delete.append(guid)

        return files_to_update, guids_to_delete

    def delete_guids(self, guids: list[str]) -> None:
        """
        Delete entries for the given GUIDs.

        Args:
            guids: List of GUIDs to delete
        """
        if not guids:
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(guids))
            cursor.execute(
                f"DELETE FROM guid_cache WHERE guid IN ({placeholders})",
                [g.lower() for g in guids],
            )
            conn.commit()

    def get_entry_count(self) -> int:
        """Get number of cached entries."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM guid_cache")
            return cursor.fetchone()[0]

    def get_last_index_time(self) -> Optional[float]:
        """Get timestamp of last full index."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM meta WHERE key = 'last_index_time'"
            )
            row = cursor.fetchone()
            if row:
                return float(row[0])
            return None

    def set_last_index_time(self, timestamp: Optional[float] = None) -> None:
        """Set timestamp of last full index."""
        if timestamp is None:
            timestamp = time.time()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_index_time', ?)",
                (str(timestamp),),
            )
            conn.commit()

    def clear(self) -> None:
        """Clear all cached data."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM guid_cache")
            cursor.execute("DELETE FROM meta WHERE key = 'last_index_time'")
            conn.commit()

    def vacuum(self) -> None:
        """Compact the database file."""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
