"""Semantic Code Search Service — pattern-based regex search across repo files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("code-wiki.search_service")


class SearchService:
    """Searches repository files using pre-defined or custom regex patterns."""

    def __init__(self, patterns: Optional[Dict[str, dict]] = None):
        from services.code_search import CODE_PATTERNS
        self._patterns = patterns or CODE_PATTERNS

    def list_patterns(self) -> List[dict]:
        """Return available search patterns."""
        return [
            {"name": name, "label": p["label"], "description": p["description"],
             "languages": p.get("languages", [])}
            for name, p in self._patterns.items()
        ]

    def search(self, repo_path: str, file_paths: List[str], pattern_name: str) -> List[dict]:
        """Search files for a named pattern."""
        pattern_def = self._patterns.get(pattern_name)
        if not pattern_def:
            return []

        import re
        regex = re.compile(pattern_def["pattern"], re.MULTILINE)
        repo = Path(repo_path)
        results: List[dict] = []

        for rel_path in file_paths:
            full_path = repo / rel_path
            try:
                source = full_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            for match in regex.finditer(source):
                line_num = source[: match.start()].count("\n") + 1
                results.append({
                    "file": rel_path,
                    "line": line_num,
                    "match": match.group(0)[:100],
                })

        return results

    def search_custom(self, repo_path: str, file_paths: List[str], query: str) -> List[dict]:
        """Search files with a custom regex."""
        import re
        try:
            regex = re.compile(query, re.MULTILINE | re.IGNORECASE)
        except re.error:
            return [{"file": "", "line": 0, "match": f"Invalid regex: {query}"}]

        repo = Path(repo_path)
        results: List[dict] = []

        for rel_path in file_paths:
            full_path = repo / rel_path
            try:
                source = full_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            for match in regex.finditer(source):
                line_num = source[: match.start()].count("\n") + 1
                results.append({
                    "file": rel_path,
                    "line": line_num,
                    "match": match.group(0)[:100],
                })

        return results
