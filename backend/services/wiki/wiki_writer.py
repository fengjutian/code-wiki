"""
WikiWriter — handles file I/O for Wiki pages.

Operations: write single page, write batch, clean old files, path conversion.
"""

import logging
from pathlib import Path
from typing import List

from models.entities import WikiPage

logger = logging.getLogger("code-wiki.wiki_writer")


class WikiWriter:
    """Writes WikiPage objects to disk under a wiki directory."""

    # Extensions whose .md paths are derived by swapping the extension
    _KNOWN_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}

    def __init__(self, wiki_path: str) -> None:
        self._wiki_dir = Path(wiki_path)

    # ---- Public API ----

    def write_page(self, page: WikiPage) -> None:
        """Write a single WikiPage to disk immediately."""
        target = self._wiki_dir / page.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page.markdown, encoding="utf-8")
        logger.debug("Wrote: %s (%d bytes)", page.path, len(page.markdown))

    def write_pages(self, pages: List[WikiPage]) -> None:
        """Write multiple WikiPage objects to disk."""
        self._wiki_dir.mkdir(parents=True, exist_ok=True)
        for page in pages:
            self.write_page(page)

    def clean_dir(self) -> None:
        """Remove all .md files except index.md."""
        if not self._wiki_dir.exists():
            return
        for md_file in self._wiki_dir.glob("**/*.md"):
            if md_file.name == "index.md":
                continue
            md_file.unlink()
            logger.debug("Cleaned: %s", md_file)

    @staticmethod
    def source_to_wiki_path(source_path: str) -> str:
        """Convert a source file path to a wiki .md path.

        e.g. services/user.py → services/user.md
             components/Button.tsx → components/Button.md
        """
        for ext in WikiWriter._KNOWN_EXTENSIONS:
            if source_path.endswith(ext):
                return source_path[: -len(ext)] + ".md"
        return source_path + ".md"

    @property
    def wiki_dir(self) -> Path:
        return self._wiki_dir
