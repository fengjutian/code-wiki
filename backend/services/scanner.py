"""
File system scanner with glob-based exclude rules.
Multi-language support: scans .py, .ts, .tsx, .js, .jsx based on configuration.

Supports three scan modes:
- FULL: scan entire repo, applying all exclude rules
- PARTIAL: scan only user-specified files (still subject to excludes)
- TREE: build a file tree structure for the frontend
"""

import os
import fnmatch
from pathlib import Path
from typing import List, Optional, Dict, Tuple

from models.entities import SupportedLanguage


class Scanner:
    """Scans a repository for files, respecting exclude patterns and language config."""

    # Immutable excludes — never scanned
    HARD_EXCLUDES = [".code-wiki/"]

    # Default excludes — user can remove
    DEFAULT_EXCLUDES = [
        "__pycache__/",
        ".git/",
        "node_modules/",
        ".venv/",
        "venv/",
        "dist/",
        "build/",
        "*.pyc",
        ".mypy_cache/",
        ".pytest_cache/",
        ".tox/",
        "*.egg-info/",
    ]

    # Supported extensions by language
    SUPPORTED_EXTENSIONS = SupportedLanguage.all_extensions()

    def __init__(
        self,
        repo_path: str,
        user_excludes: Optional[List[str]] = None,
        languages: Optional[List[str]] = None,
    ):
        self.repo_path = repo_path
        self.user_excludes = user_excludes or []
        # Languages to scan: default to [python] for backward compat, or all if explicitly configured
        self.languages = languages or ["python"]
        self._extensions = self._extensions_for_languages(self.languages)

    @staticmethod
    def _extensions_for_languages(languages: List[str]) -> List[str]:
        """Resolve language list to file extensions."""
        exts = []
        for lang_name in languages:
            for lang in SupportedLanguage:
                if lang.value == lang_name:
                    exts.extend(SupportedLanguage.extensions()[lang])
        return exts or [".py"]

    @property
    def all_excludes(self) -> List[str]:
        """Merge all exclude patterns: hard + default + user."""
        seen = set()
        merged = []
        for p in self.HARD_EXCLUDES + self.DEFAULT_EXCLUDES + self.user_excludes:
            if p not in seen:
                seen.add(p)
                merged.append(p)
        return merged

    def is_excluded(self, relative_path: str) -> bool:
        """Check if a relative path matches any exclude pattern."""
        for pattern in self.all_excludes:
            # Exact match
            if fnmatch.fnmatch(relative_path, pattern):
                return True
            # fnmatch on name only (for patterns like "*.pyc")
            name = os.path.basename(relative_path)
            if fnmatch.fnmatch(name, pattern):
                return True
            # Directory prefix match (e.g., "__pycache__/" matches "__pycache__/foo.py")
            if pattern.endswith("/") and (
                relative_path == pattern[:-1]
                or relative_path.startswith(pattern)
                # Also check for nested matches (e.g., "node_modules/" should match
                # "code-wiki-frontend/node_modules/foo")
                or ("/" + pattern) in ("/" + relative_path)
            ):
                return True
        return False

    def scan_all(self) -> List[str]:
        """
        Full scan: return all supported file relative paths, excluding matches.

        Uses os.walk with in-place dir filtering for efficiency.
        """
        matched_files: List[str] = []
        excludes = self.all_excludes

        for root, dirs, files in os.walk(self.repo_path):
            # Filter directories in-place: excluded dirs are not descended
            rel_root = os.path.relpath(root, self.repo_path).replace("\\", "/")
            if rel_root == ".":
                rel_root = ""

            dirs[:] = [
                d
                for d in dirs
                if not self._dir_excluded(
                    os.path.join(rel_root, d).replace("\\", "/") + "/", excludes
                )
            ]

            for f in files:
                rel_path = (
                    os.path.join(rel_root, f).replace("\\", "/")
                    if rel_root
                    else f
                )
                # Only scan supported extensions
                ext = os.path.splitext(f)[1].lower()
                if ext not in self._extensions:
                    continue
                if self.is_excluded(rel_path):
                    continue
                matched_files.append(rel_path)

        return sorted(matched_files)

    def scan_partial(self, target_files: List[str]) -> List[str]:
        """
        Partial scan: only include specified files, still apply excludes.
        """
        return sorted(
            f for f in target_files
            if not self.is_excluded(f)
            and os.path.splitext(f)[1].lower() in self._extensions
        )

    def get_file_tree(self) -> List[dict]:
        """
        Build a file tree for the frontend Code tab.
        Returns list of tree nodes with analysis status stubs.
        """
        return self._build_tree(self.repo_path, "")

    def _build_tree(self, base: str, rel_prefix: str) -> List[dict]:
        """Recursively build file tree dict."""
        items: List[dict] = []
        full = os.path.join(base, rel_prefix) if rel_prefix else base

        try:
            entries = sorted(os.listdir(full))
        except (PermissionError, FileNotFoundError):
            return items

        for name in entries:
            rel = (
                os.path.join(rel_prefix, name).replace("\\", "/")
                if rel_prefix
                else name
            )

            full_path = os.path.join(full, name)
            if os.path.isdir(full_path):
                # Check directory exclusion
                if self._dir_excluded(rel + "/", self.all_excludes):
                    continue
                children = self._build_tree(base, rel)
                items.append(
                    {
                        "name": name,
                        "path": rel,
                        "type": "directory",
                        "status": "pending",
                        "excluded": False,
                        "children": children,
                    }
                )
            elif os.path.splitext(name)[1].lower() in self.SUPPORTED_EXTENSIONS:
                if self.is_excluded(rel):
                    continue
                items.append(
                    {
                        "name": name,
                        "path": rel,
                        "type": "file",
                        "status": "pending",
                        "excluded": False,
                    }
                )

        return items

    def _dir_excluded(self, rel_dir: str, excludes: List[str]) -> bool:
        """Check if a directory (ending with '/') should be excluded."""
        for pattern in excludes:
            # Pattern like "__pycache__/" or ".git/"
            if pattern.endswith("/"):
                if rel_dir == pattern or rel_dir.startswith(pattern):
                    return True
                # Also check if pattern matches any path component (nested dirs)
                # e.g. "node_modules/" should match "code-wiki-frontend/node_modules/"
                if "/" + pattern in "/" + rel_dir:
                    return True
            # Pattern like "__pycache__" (no trailing slash)
            name = rel_dir.rstrip("/").rsplit("/", 1)[-1]
            if fnmatch.fnmatch(name, pattern):
                return True
            # Exact glob match
            if fnmatch.fnmatch(rel_dir.rstrip("/"), pattern):
                return True
        return False

    def get_file_count(self, pre_scanned: Optional[List[str]] = None) -> Dict[str, int]:
        """Return counts: total supported files, excluded files.

        If *pre_scanned* is provided (result from scan_all()), uses that
        instead of re-walking the filesystem — avoiding a double traversal.
        """
        if pre_scanned is not None:
            return {"total": len(pre_scanned), "excluded": 0, "to_analyze": len(pre_scanned)}

        total = 0
        excluded = 0
        for root, dirs, files in os.walk(self.repo_path):
            rel_root = os.path.relpath(root, self.repo_path).replace("\\", "/")
            if rel_root == ".":
                rel_root = ""

            dirs[:] = [
                d
                for d in dirs
                if not self._dir_excluded(
                    os.path.join(rel_root, d).replace("\\", "/") + "/",
                    self.all_excludes,
                )
            ]

            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in self._extensions:
                    total += 1
                    rel = (
                        os.path.join(rel_root, f).replace("\\", "/")
                        if rel_root
                        else f
                    )
                    if self.is_excluded(rel):
                        excluded += 1

        return {"total": total, "excluded": excluded, "to_analyze": total - excluded}
