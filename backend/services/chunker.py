"""
Markdown chunker — splits Wiki pages into searchable chunks.

v2: Smart chunking with paragraph-aware re-splitting, heading context
    preservation, and code block integrity.
"""

from typing import List, Optional

from models.entities import WikiPage

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
MAX_CHUNK_BYTES = 3000         # Maximum bytes per chunk (UTF-8 safe)
MIN_CHUNK_CHARS = 50           # Drop chunks shorter than this
PREFERRED_CHUNK_BYTES = 2000   # Target size — split at this point if possible


class MarkdownChunker:
    """Split WikiPage Markdown into heading-delimited chunks.

    Strategy (v2):
    1. Split on ## headings (protecting fenced code blocks).
    2. If a section exceeds MAX_CHUNK_BYTES, re-split at paragraph
       boundaries (double newlines), trying to stay near PREFERRED_CHUNK_BYTES.
    3. For sub-chunks from the same heading, prepend the heading as context.
    4. Drop chunks shorter than MIN_CHUNK_CHARS.
    """

    _CODE_SENTINEL = "\x00CD\x00"

    def chunk_pages(self, pages: List[WikiPage]) -> List[dict]:
        """Split Wiki pages into chunks by ## headings (outside code blocks)."""
        chunks: List[dict] = []
        for page in pages:
            content = page.markdown
            # Protect fenced code blocks
            protected, fences = self._protect_fences(content)
            sections = protected.split("\n## ")
            for i, section in enumerate(sections):
                section = self._restore_fences(section, fences)
                heading, body = self._extract_heading(section, is_first=(i == 0))

                # Split oversized chunks at paragraph boundaries
                sub_chunks = self._split_oversized(body, heading)
                for sc_body, sc_suffix in sub_chunks:
                    chunk_text = sc_body
                    if heading and sc_suffix:
                        # Keep heading context for sub-chunks
                        chunk_text = f"## {heading}\n\n{sc_body}"

                    if len(chunk_text.strip()) < MIN_CHUNK_CHARS:
                        continue

                    safe_text = self._truncate_safe(chunk_text, MAX_CHUNK_BYTES)
                    chunks.append({
                        "text": safe_text,
                        "source": page.source_path,
                        "wiki_path": page.path,
                        "title": heading or page.path,
                    })

        return chunks

    # ── Heading extraction ───────────────────────────────────────────────

    @staticmethod
    def _extract_heading(section: str, is_first: bool) -> tuple:
        """Return (heading, body_text) from a section.

        For the first section, the heading is the H1 title (first # line).
        For other sections, the heading is the ## text up to the next newline.
        """
        first_newline = section.find("\n")
        if first_newline <= 0:
            raw_title = section.strip()
            body = section
        else:
            raw_title = section[:first_newline].strip()
            body = section

        # Clean the heading
        title = raw_title.strip("# ").strip()
        return title, body

    # ── Paragraph-aware re-splitting ─────────────────────────────────────

    def _split_oversized(
        self, body: str, heading: str
    ) -> List[tuple]:
        """Split oversized body text at paragraph boundaries.

        Returns list of (chunk_body, has_suffix_marker) tuples.
        has_suffix_marker=True means this is a continuation and should
        have the heading prepended.
        """
        body_bytes = len(body.encode("utf-8"))
        if body_bytes <= MAX_CHUNK_BYTES:
            return [(body, False)]

        # Split on paragraph boundaries (double newline)
        # But protect code blocks first
        protected, fences = self._protect_fences(body)
        paragraphs = protected.split("\n\n")

        chunks: List[tuple] = []
        current: List[str] = []
        current_bytes = 0
        is_first = True

        for para in paragraphs:
            para = self._restore_fences(para, fences)
            para_bytes = len(para.encode("utf-8"))

            if current_bytes + para_bytes > MAX_CHUNK_BYTES and current:
                # Flush current chunk
                chunks.append(("\n\n".join(current), not is_first))
                current = []
                current_bytes = 0
                is_first = False

            current.append(para)
            current_bytes += para_bytes

            # Also split if we're past preferred size and hit a good boundary
            if (
                current_bytes > PREFERRED_CHUNK_BYTES
                and len(current) > 1
                and para.endswith((".", "。", ")", "：", ":", "?", "？", "!", "！"))
            ):
                chunks.append(("\n\n".join(current), not is_first))
                current = []
                current_bytes = 0
                is_first = False

        if current:
            chunks.append(("\n\n".join(current), not is_first))

        # If a single paragraph is still too big, split at sentence boundaries
        final_chunks: List[tuple] = []
        for chunk_body, is_continuation in chunks:
            if len(chunk_body.encode("utf-8")) <= MAX_CHUNK_BYTES:
                final_chunks.append((chunk_body, is_continuation))
            else:
                # Last resort: sentence-level split
                sub_parts = self._split_sentences(chunk_body)
                for i, sp in enumerate(sub_parts):
                    final_chunks.append((sp, is_continuation or i > 0))

        return final_chunks or [(body, False)]

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """Split text at sentence boundaries as a last resort."""
        parts: List[str] = []
        current: List[str] = []
        current_bytes = 0

        # Split on sentence-ending punctuation followed by newline or space
        import re
        sentences = re.split(r"(?<=[.。!！?？])\s+", text)

        for sent in sentences:
            sent_bytes = len(sent.encode("utf-8"))
            if current_bytes + sent_bytes > MAX_CHUNK_BYTES and current:
                parts.append(" ".join(current))
                current = []
                current_bytes = 0
            current.append(sent)
            current_bytes += sent_bytes
        if current:
            parts.append(" ".join(current))
        return parts or [text]

    # ── Fence protection ─────────────────────────────────────────────────

    def _protect_fences(self, text: str) -> tuple:
        """Replace fenced code blocks with sentinels."""
        fences: List[str] = []
        result: List[str] = []
        in_fence = False
        fence_buf: List[str] = []
        i = 0
        while i < len(text):
            if text[i: i + 3] == "```" and not in_fence:
                in_fence = True
                fence_buf = ["```"]
                i += 3
            elif text[i: i + 3] == "```" and in_fence:
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

    # ── UTF-8 safe truncation ────────────────────────────────────────────

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
