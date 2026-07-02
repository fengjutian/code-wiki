"""
Semantic Code Search — pattern-based code search + AST-aware querying.

Enhances the existing hybrid search (BM25 + Cosine RRF) with:
- AST pattern matching via tree-sitter queries
- Regex + AST hybrid query
- Code-aware embedding hints
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from models.entities import ModuleInfo, SupportedLanguage


# Pre-defined code search patterns
CODE_PATTERNS: Dict[str, dict] = {
    "env_read_py": {
        "label": "Environment variable reads (Python)",
        "pattern": r"os\.environ(?:\[|\.get)|\bos\.getenv\b",
        "languages": ["python"],
        "description": "os.environ, os.environ.get(), os.getenv()",
    },
    "env_read_ts": {
        "label": "Environment variable reads (TypeScript)",
        "pattern": r"process\.env\.\w+",
        "languages": ["typescript", "javascript"],
        "description": "process.env.VARIABLE_NAME",
    },
    "sql_query": {
        "label": "SQL query execution",
        "pattern": r"\.execute\s*\(|\.executemany\s*\(|executemany\s*\(|\.raw\s*\(",
        "languages": ["python"],
        "description": "cursor.execute(), cursor.executemany()",
    },
    "http_request": {
        "label": "HTTP requests",
        "pattern": r"(?:requests|httpx|aiohttp)\.(?:get|post|put|delete|patch)\s*\(|fetch\s*\(.*['\"]https?://",
        "languages": ["python", "typescript", "javascript"],
        "description": "requests.get(), fetch(), httpx.post()",
    },
    "file_write": {
        "label": "File write operations",
        "pattern": r"open\s*\([^)]*['\"][wa][^'\"]*['\"]|\.write_text\s*\(|writeFileSync|fs\.writeFile",
        "languages": ["python", "typescript", "javascript"],
        "description": "open(..., 'w'), write_text(), writeFileSync()",
    },
    "exception_handling": {
        "label": "Exception handling",
        "pattern": r"\btry\s*:|\bexcept\s+|\bcatch\s*\(|\bthrow\s+new\s+Error",
        "languages": ["python", "typescript", "javascript"],
        "description": "try/except/catch blocks",
    },
    "async_pattern": {
        "label": "Async/await patterns",
        "pattern": r"\basync\s+def\b|\basync\s+\(|\bawait\s+\w+",
        "languages": ["python", "typescript", "javascript"],
        "description": "async def, async (), await expressions",
    },
    "use_state": {
        "label": "React useState hooks",
        "pattern": r"\buseState\s*<\s*\w+\s*>|\buseState\s*\(|const\s*\[\s*\w+\s*,\s*\w+\s*\]\s*=\s*useState",
        "languages": ["typescript", "javascript"],
        "description": "useState() hook calls",
    },
    "decorator_pattern": {
        "label": "Python decorators",
        "pattern": r"@\w+(?:\.\w+)*(?:\([^)]*\))?\s*\n\s*(?:def|class)\s+\w+",
        "languages": ["python"],
        "description": "Decorated functions/classes",
    },
}


class CodePatternSearch:
    """Search code using pre-defined or custom regex patterns."""

    def __init__(self, patterns: Optional[Dict[str, dict]] = None):
        self.patterns = patterns or CODE_PATTERNS

    def search(
        self,
        modules: Dict[str, ModuleInfo],
        pattern_name: str,
        repo_path: str | Path = ".",
    ) -> List[dict]:
        """Search for a named pattern across modules."""
        pattern_def = self.patterns.get(pattern_name)
        if not pattern_def:
            return []

        repo = Path(repo_path)
        results: List[dict] = []
        regex = re.compile(pattern_def["pattern"], re.MULTILINE)

        for rel_path, module in modules.items():
            lang_value = module.language.value
            if lang_value not in pattern_def["languages"]:
                continue

            full_path = repo / rel_path
            try:
                source = full_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            for match in regex.finditer(source):
                line_num = source[: match.start()].count("\n") + 1
                context = source[max(0, match.start() - 40): match.end() + 40]
                results.append({
                    "file": rel_path,
                    "line": line_num,
                    "match": match.group(0)[:100],
                    "context": context.replace("\n", " ")[:120],
                    "language": lang_value,
                })

        return results

    def search_custom(
        self,
        modules: Dict[str, ModuleInfo],
        query: str,
        repo_path: str | Path = ".",
        languages: Optional[List[str]] = None,
    ) -> List[dict]:
        """Search with a custom regex across modules."""
        repo = Path(repo_path)
        results: List[dict] = []
        try:
            regex = re.compile(query, re.MULTILINE | re.IGNORECASE)
        except re.error:
            return [{"error": f"Invalid regex: {query}"}]

        for rel_path, module in modules.items():
            lang_value = module.language.value
            if languages and lang_value not in languages:
                continue

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
                    "language": lang_value,
                })

        return results

    def search_by_paths(
        self,
        repo_path: str,
        file_paths: List[str],
        pattern_name: str,
    ) -> List[dict]:
        """Search using file paths (lightweight, no ModuleInfo needed)."""
        pattern_def = self.patterns.get(pattern_name)
        if not pattern_def:
            return []

        repo = Path(repo_path)
        results: List[dict] = []
        regex = re.compile(pattern_def["pattern"], re.MULTILINE)

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

    def search_custom_by_paths(
        self,
        repo_path: str,
        file_paths: List[str],
        query: str,
    ) -> List[dict]:
        """Custom regex search using file paths."""
        repo = Path(repo_path)
        results: List[dict] = []
        try:
            regex = re.compile(query, re.MULTILINE | re.IGNORECASE)
        except re.error:
            return [{"error": f"Invalid regex: {query}"}]

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

    def list_patterns(self) -> List[dict]:
        """List all available search patterns."""
        return [
            {"name": name, "label": p["label"], "description": p["description"],
             "languages": p["languages"]}
            for name, p in self.patterns.items()
        ]
