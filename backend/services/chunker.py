"""
Markdown chunker — splits Wiki pages into searchable chunks.

Splits on ## headings (outside fenced code blocks), with safe UTF-8
truncation and configurable size limits.
"""

from typing import List

from models.entities import WikiPage

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
MAX_CHUNK_BYTES = 3000         # Maximum bytes per chunk (UTF-8 safe)
MIN_CHUNK_CHARS = 50           # Drop chunks shorter than this


class MarkdownChunker:
    """Split WikiPage Markdown into heading-delimited chunks."""

    # Sentinel used during chunking to protect fenced code blocks
    _CODE_SENTINEL = "\x00CD\x00"

    def chunk_pages(self, pages: List[WikiPage]) -> List[dict]:
        """Split Wiki pages into chunks by ## headings (outside code blocks)."""
        chunks = []
        for page in pages:
            content = page.markdown
            # Protect fenced code blocks so '##' inside them won't split
            protected, fences = self._protect_fences(content)
            sections = protected.split("\n## ")
            # Restore fences in each section
            for i in range(len(sections)):
                sections[i] = self._restore_fences(sections[i], fences)

            for i, section in enumerate(sections):
                title = ""
                body = section
                if i == 0:
                    first_newline = section.find("\n")
                    title = (
                        section[:first_newline].strip("# ").strip()
                        if first_newline > 0
                        else section.strip()
                    )
                else:
                    first_newline = section.find("\n")
                    title = (
                        section[:first_newline].strip()
                        if first_newline > 0
                        else section.strip()
                    )
                    body = "## " + section

                if len(body.strip()) < MIN_CHUNK_CHARS:
                    continue

                safe_body = self._truncate_safe(body, MAX_CHUNK_BYTES)
                chunks.append(
                    {
                        "text": safe_body,
                        "source": page.source_path,
                        "wiki_path": page.path,
                        "title": title or page.path,
                    }
                )
        return chunks

    # ------------------------------------------------------------------
    # Fence protection (keep '##' inside `````` from acting as splitters)
    # ------------------------------------------------------------------

    def _protect_fences(self, text: str) -> tuple:
        """Replace fenced code blocks with sentinels.

        Returns (protected_text, fence_list) where fence_list maps
        sentinel indices to original code block text.
        """
        fences = []
        result = []
        in_fence = False
        fence_buf = []
        i = 0
        while i < len(text):
            if text[i : i + 3] == "```" and not in_fence:
                in_fence = True
                fence_buf = ["```"]
                i += 3
            elif text[i : i + 3] == "```" and in_fence:
                fence_buf.append("```")
                idx = len(fences)
                fences.append("".join(fence_buf))
                result.append(
                    f"{self._CODE_SENTINEL}{idx}{self._CODE_SENTINEL}"
                )
                fence_buf = []
                in_fence = False
                i += 3
            elif in_fence:
                fence_buf.append(text[i])
                i += 1
            else:
                result.append(text[i])
                i += 1
        if fence_buf:
            result.append("".join(fence_buf))
        return "".join(result), fences

    def _restore_fences(self, text: str, fences: list) -> str:
        """Restore fenced code blocks from sentinels."""
        for idx, fence in enumerate(fences):
            text = text.replace(
                f"{self._CODE_SENTINEL}{idx}{self._CODE_SENTINEL}", fence
            )
        return text

    # ------------------------------------------------------------------
    # UTF-8 safe truncation
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate_safe(text: str, max_bytes: int) -> str:
        """Truncate text to at most *max_bytes* UTF-8 bytes,
        without splitting a multi-byte character."""
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        truncated = encoded[:max_bytes]
        while truncated:
            try:
                return truncated.decode("utf-8")
            except UnicodeDecodeError:
                truncated = truncated[:-1]
        return ""
