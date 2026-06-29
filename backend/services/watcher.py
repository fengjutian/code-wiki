"""
File system watcher — monitors repo for .py file changes and triggers incremental analysis.

Uses a simple polling-based approach (no watchdog dependency needed).
On change detection: debounce 500ms → send SSE event → trigger incremental pipeline.
"""

import os
import time
import asyncio
import hashlib
from pathlib import Path
from typing import Dict, Set, Optional, Callable


class FileWatcher:
    """
    Polls the repository for file changes at regular intervals.
    When changes are detected (after debounce), calls the on_change callback.
    """

    def __init__(
        self,
        repo_path: str,
        exclude_patterns: Optional[list] = None,
        poll_interval: float = 1.0,
        debounce_ms: int = 500,
    ):
        self.repo_path = repo_path
        self.poll_interval = poll_interval
        self.debounce_ms = debounce_ms
        self.exclude_patterns = exclude_patterns or []

        # File hash cache: {rel_path: md5_hash}
        self._hashes: Dict[str, str] = {}
        # Pending changes before debounce fires
        self._pending: Set[str] = set()
        self._last_change: float = 0
        # Callback: async function(changed_files: list[str])
        self._on_change: Optional[Callable] = None
        # Running flag
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def on_change(self, callback: Callable):
        """Register callback for file changes. Called with list of changed rel paths."""
        self._on_change = callback
        return self

    async def start(self):
        """Start the polling loop as a background asyncio task."""
        if self._running:
            return
        self._running = True
        # Initial scan to populate hash cache (run in executor to avoid blocking)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._scan_all)
        self._task = asyncio.create_task(self._poll_loop())

    def stop(self):
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def _scan_all(self):
        """Perform initial scan to build hash cache."""
        new_hashes: Dict[str, str] = {}
        for root, dirs, files in os.walk(self.repo_path):
            rel_root = os.path.relpath(root, self.repo_path).replace("\\", "/")
            if rel_root == ".":
                rel_root = ""

            # Filter excluded dirs
            dirs[:] = [
                d for d in dirs
                if not self._is_excluded(
                    os.path.join(rel_root, d).replace("\\", "/") + "/"
                )
            ]

            for f in files:
                if not f.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
                    continue
                rel = (
                    os.path.join(rel_root, f).replace("\\", "/")
                    if rel_root else f
                )
                if self._is_excluded(rel):
                    continue

                full = os.path.join(root, f)
                try:
                    new_hashes[rel] = self._file_hash(full)
                except (OSError, IOError):
                    pass

        self._hashes = new_hashes

    async def _poll_loop(self):
        """Main polling loop — checks for changes every poll_interval seconds."""
        while self._running:
            try:
                changed = self._check_changes()
                if changed:
                    self._pending.update(changed)
                    self._last_change = time.time()
                else:
                    # Check if debounce period has elapsed
                    if self._pending and (
                        time.time() - self._last_change
                    ) * 1000 >= self.debounce_ms:
                        await self._fire_change()

                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(self.poll_interval)

    def _check_changes(self) -> Set[str]:
        """Check for file changes compared to cached hashes. Returns changed files."""
        changed: Set[str] = set()
        current_files: Set[str] = set()

        for root, dirs, files in os.walk(self.repo_path):
            rel_root = os.path.relpath(root, self.repo_path).replace("\\", "/")
            if rel_root == ".":
                rel_root = ""

            dirs[:] = [
                d for d in dirs
                if not self._is_excluded(
                    os.path.join(rel_root, d).replace("\\", "/") + "/"
                )
            ]

            for f in files:
                if not f.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
                    continue
                rel = (
                    os.path.join(rel_root, f).replace("\\", "/")
                    if rel_root else f
                )
                if self._is_excluded(rel):
                    continue
                current_files.add(rel)

                full = os.path.join(root, f)
                try:
                    current_hash = self._file_hash(full)
                    if rel not in self._hashes or self._hashes[rel] != current_hash:
                        changed.add(rel)
                        self._hashes[rel] = current_hash
                except (OSError, IOError):
                    pass

        # Detect deleted files
        deleted = set(self._hashes.keys()) - current_files
        for d in deleted:
            del self._hashes[d]
        changed.update(deleted)

        return changed

    async def _fire_change(self):
        """Fire the change callback with accumulated pending files."""
        if not self._pending:
            return

        changed = list(self._pending)
        self._pending.clear()

        if self._on_change:
            try:
                result = self._on_change(changed)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                print(f"[Watcher] Error in change callback: {e}")

    def _is_excluded(self, rel_path: str) -> bool:
        """Check if path matches exclude patterns."""
        import fnmatch
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            name = os.path.basename(rel_path.rstrip("/"))
            if fnmatch.fnmatch(name, pattern):
                return True
            if pattern.endswith("/") and (
                rel_path == pattern[:-1] or rel_path.startswith(pattern)
            ):
                return True
        return False

    @staticmethod
    def _file_hash(path: str) -> str:
        """Compute MD5 hash of a file."""
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
