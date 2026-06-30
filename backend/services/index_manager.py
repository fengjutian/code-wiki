"""
Incremental Index Manager — hash-based sync for FAISS vector store.

Tracks source-file content hashes in a SQLite record table so only
changed / added / deleted files trigger re-embedding.  Essential for
10,000-file scale — avoids re-embedding the entire codebase on every scan.

Uses sqlite3 directly (no external dependency beyond stdlib) so there's
zero coupling to langchain internals.

Layout on disk::

    {wiki_path}/index_record.db   ← SQLite: (source_path, content_hash, updated_at)

Usage::

    mgr = IndexManager(wiki_path)
    added, changed, deleted = mgr.compute_delta(modules)
    store.delete_by_source(del_path)
    store.add_texts(texts_for_new_or_changed, metadatas)
    mgr.mark_synced(new_or_changed_paths)
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Tuple

from models.entities import ModuleInfo

logger = logging.getLogger("code-wiki.index_manager")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DB_FILENAME = "index_record.db"


class IndexManager:
    """Tracks file hashes for incremental index updates.

    Computes an MD5 hash of each source file's content + mtime so we
    can skip unchanged files and only embed what's new or modified.
    """

    def __init__(self, wiki_path: str):
        self._db_path = Path(wiki_path) / DB_FILENAME
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
            self._ensure_schema()
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS file_hash (
                source_path  TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                updated_at   REAL NOT NULL
            )
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Hash computation
    # ------------------------------------------------------------------

    @staticmethod
    def compute_hash(module: ModuleInfo, repo_path: str) -> str | None:
        """Compute an MD5 hash of a source file's content.

        Hashes the actual file bytes — not the ModuleInfo object — so
        any content change (even whitespace) triggers re-indexing.
        """
        full_path = Path(repo_path) / module.path
        try:
            data = full_path.read_bytes()
            return hashlib.md5(data).hexdigest()
        except (OSError, ValueError) as e:
            logger.warning("Cannot hash %s: %s", module.path, e)
            return None

    # ------------------------------------------------------------------
    # Delta computation
    # ------------------------------------------------------------------

    def compute_delta(
        self,
        modules: Dict[str, ModuleInfo],
        repo_path: str,
    ) -> Tuple[List[str], List[str], List[str]]:
        """Compare current modules against stored hashes.

        Returns:
            (added, changed, deleted) — three lists of source_path strings.

        * **added** — files in *modules* but not in the hash table
        * **changed** — files whose hash differs from the stored one
        * **deleted** — files in the hash table but not in *modules*

        A file whose hash can't be computed (e.g. deleted on disk) is
        treated as *deleted*.
        """
        # Load stored hashes
        stored = self._load_all_hashes()

        # Compute current hashes
        current: Dict[str, str] = {}
        for path, module in modules.items():
            h = self.compute_hash(module, repo_path)
            if h is not None:
                current[path] = h

        current_paths = set(current.keys())
        stored_paths = set(stored.keys())

        added = sorted(current_paths - stored_paths)
        changed = sorted(
            p for p in (current_paths & stored_paths)
            if current[p] != stored[p]
        )
        deleted = sorted(stored_paths - current_paths)

        logger.info(
            "Index delta: +%d added, ~%d changed, -%d deleted (of %d total)",
            len(added), len(changed), len(deleted), len(modules),
        )
        return added, changed, deleted

    # ------------------------------------------------------------------
    # Mark synced
    # ------------------------------------------------------------------

    def mark_synced(self, source_paths: List[str], modules: Dict[str, ModuleInfo], repo_path: str):
        """Update the hash table for paths that were just indexed."""
        now = time.time()
        with self.conn:
            for path in source_paths:
                module = modules.get(path)
                if module is None:
                    continue
                h = self.compute_hash(module, repo_path)
                if h is None:
                    continue
                self.conn.execute(
                    "INSERT OR REPLACE INTO file_hash VALUES (?, ?, ?)",
                    (path, h, now),
                )

    def mark_deleted(self, source_paths: List[str]):
        """Remove entries for files that no longer exist."""
        if not source_paths:
            return
        with self.conn:
            placeholders = ",".join("?" for _ in source_paths)
            self.conn.execute(
                f"DELETE FROM file_hash WHERE source_path IN ({placeholders})",
                source_paths,
            )

    # ------------------------------------------------------------------
    # Full rebuild mode
    # ------------------------------------------------------------------

    def clear_all(self):
        """Drop all hash records — forces a full re-index on next sync."""
        with self.conn:
            self.conn.execute("DELETE FROM file_hash")
        logger.info("Index hash table cleared — next sync will be full rebuild")

    def count(self) -> int:
        """Return the number of tracked file hashes."""
        row = self.conn.execute("SELECT COUNT(*) FROM file_hash").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_all_hashes(self) -> Dict[str, str]:
        """Return {source_path: content_hash} for all tracked files."""
        rows = self.conn.execute(
            "SELECT source_path, content_hash FROM file_hash"
        ).fetchall()
        return {row[0]: row[1] for row in rows}
