"""
AST Symbol Chunker — extracts function/class/method-level chunks from source code.

Unlike the MarkdownChunker which splits Wiki pages by ## headings, this chunks
the actual source code at semantic boundaries (functions, classes, methods),
giving RAG retrieval precise, self-contained units of code.

v2 — Integrates LangChain RecursiveCharacterTextSplitter for fine-grained
     secondary splitting of oversized chunks (functions > 6000 bytes).

Input:  Dict[str, ModuleInfo] from the analysis step
Output: List[dict] — chunk dicts with text, source, symbol_name, symbol_type, etc.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from models.entities import (
    ModuleInfo, ClassInfo, FunctionInfo, InterfaceInfo, ReactComponentInfo,
    SupportedLanguage,
)

logger = logging.getLogger("code-wiki.ast_chunker")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
MAX_CHUNK_BYTES = 6000          # Soft cap per chunk (bytes) — above this, fine-split
FINE_SPLIT_SIZE = 2000          # Target chars for fine-split sub-chunks
FINE_SPLIT_OVERLAP = 200        # Overlap between sub-chunks
TRUNCATE_NOTICE = "\n... (truncated)"

# LangChain fine-splitting (lazy import)
_FINE_SPLIT_AVAILABLE = False
_SplitterCache: dict = {}

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
    _FINE_SPLIT_AVAILABLE = True
except ImportError:
    pass


class ASTChunker:
    """Extract symbol-level chunks from analyzed modules."""

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_modules(self, modules: Dict[str, ModuleInfo]) -> List[dict]:
        """Convert a batch of ModuleInfo objects into searchable chunks.

        Each chunk represents one function, method, class, interface, or
        React component — a self-contained semantic unit of code.

        Oversized chunks (>MAX_CHUNK_BYTES) are fine-split using
        LangChain's RecursiveCharacterTextSplitter (language-aware).
        """
        all_chunks: List[dict] = []
        for rel_path, module in sorted(modules.items()):
            try:
                chunks = self._chunk_one_module(module)
                # Fine-split oversized chunks
                chunks = self._fine_split_chunks(chunks, module.language.value)
                all_chunks.extend(chunks)
            except Exception as e:
                logger.warning("AST chunking failed for %s: %s", rel_path, e)

        logger.info(
            "ASTChunker: %d chunks from %d modules",
            len(all_chunks), len(modules),
        )
        return all_chunks

    # ------------------------------------------------------------------
    # Fine-splitting (LangChain RecursiveCharacterTextSplitter)
    # ------------------------------------------------------------------

    def _fine_split_chunks(self, chunks: List[dict], language: str) -> List[dict]:
        """Apply language-aware fine-splitting to oversized chunks.

        Chunks under MAX_CHUNK_BYTES pass through unchanged.  Oversized
        chunks are split into sub-chunks that inherit the parent's
        metadata (source, symbol_name, etc.).
        """
        if not _FINE_SPLIT_AVAILABLE:
            # Fallback: truncate (original behavior)
            return chunks

        splitter = self._get_splitter(language)
        if splitter is None:
            return chunks

        result: List[dict] = []
        for chunk in chunks:
            text = chunk.get("text", "")
            if len(text.encode("utf-8")) <= MAX_CHUNK_BYTES:
                result.append(chunk)
                continue

            # Fine-split this oversized chunk
            try:
                sub_texts = splitter.split_text(text)
            except Exception:
                sub_texts = [text]

            if len(sub_texts) <= 1:
                # Splitter couldn't split — keep original (truncated)
                result.append(chunk)
                continue

            # Create sub-chunks inheriting parent metadata
            for i, sub_text in enumerate(sub_texts):
                suffix = f" [{i+1}/{len(sub_texts)}]" if len(sub_texts) > 1 else ""
                sub_chunk = {
                    "text": sub_text,
                    "source": chunk.get("source", ""),
                    "wiki_path": chunk.get("wiki_path", ""),
                    "title": chunk.get("title", "") + suffix,
                    "symbol_name": chunk.get("symbol_name", ""),
                    "symbol_type": chunk.get("symbol_type", ""),
                    "start_line": chunk.get("start_line"),
                    "end_line": chunk.get("end_line"),
                    "parent_class": chunk.get("parent_class"),
                    "language": chunk.get("language", language),
                }
                result.append(sub_chunk)

        return result

    def _get_splitter(self, language: str):
        """Return a cached language-aware RecursiveCharacterTextSplitter."""
        if not _FINE_SPLIT_AVAILABLE:
            return None

        lang_key = language.lower()
        if lang_key in _SplitterCache:
            return _SplitterCache[lang_key]

        try:
            lang = {
                "python": Language.PYTHON,
                "typescript": Language.TS,
                "javascript": Language.JS,
            }.get(lang_key)
        except (AttributeError, NameError):
            lang = None

        try:
            if lang is not None:
                splitter = RecursiveCharacterTextSplitter.from_language(
                    language=lang,
                    chunk_size=FINE_SPLIT_SIZE,
                    chunk_overlap=FINE_SPLIT_OVERLAP,
                )
            else:
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=FINE_SPLIT_SIZE,
                    chunk_overlap=FINE_SPLIT_OVERLAP,
                    separators=["\n\n", "\n", " ", ""],
                )
            _SplitterCache[lang_key] = splitter
            return splitter
        except Exception as e:
            logger.debug("Failed to create splitter for %s: %s", language, e)
            return None

    # ------------------------------------------------------------------
    # Per-module chunking
    # ------------------------------------------------------------------

    def _chunk_one_module(self, module: ModuleInfo) -> List[dict]:
        """Extract chunks from a single module."""
        source = self._read_source(module.path)
        if not source:
            return []

        lines = source.split("\n")
        chunks: List[dict] = []

        # 1. Top-level functions
        for fn in module.functions:
            chunk = self._make_function_chunk(fn, module, lines, parent_class=None)
            if chunk:
                chunks.append(chunk)

        # 2. Classes (full class + individual methods)
        for cls in module.classes:
            # Full class chunk
            class_chunk = self._make_class_chunk(cls, module, lines)
            if class_chunk:
                chunks.append(class_chunk)

            # Individual method chunks (with class context)
            for method in cls.methods:
                method_chunk = self._make_function_chunk(
                    method, module, lines, parent_class=cls.name,
                )
                if method_chunk:
                    chunks.append(method_chunk)

        # 3. TypeScript interfaces
        for iface in getattr(module, 'interfaces', []) or []:
            chunk = self._make_interface_chunk(iface, module, lines)
            if chunk:
                chunks.append(chunk)

        # 4. React components
        for comp in getattr(module, 'components', []) or []:
            chunk = self._make_component_chunk(comp, module, lines)
            if chunk:
                chunks.append(chunk)

        return chunks

    # ------------------------------------------------------------------
    # Chunk builders
    # ------------------------------------------------------------------

    def _make_function_chunk(
        self,
        fn: FunctionInfo,
        module: ModuleInfo,
        lines: List[str],
        parent_class: Optional[str] = None,
    ) -> Optional[dict]:
        """Build a chunk for a function or method."""
        code = self._extract_lines(lines, fn.anchor.line if fn.anchor else 1, fn.end_line)
        signature = fn.signature

        full_name = f"{parent_class}.{fn.name}" if parent_class else fn.name
        symbol_type = "method" if parent_class else "function"

        text = self._build_text(
            symbol_name=full_name,
            symbol_type=symbol_type,
            file_path=module.path,
            language=module.language.value,
            signature=signature,
            docstring=fn.docstring,
            parent_class=parent_class,
            decorators=fn.decorators,
            code=code,
        )

        return {
            "text": text,
            "source": module.path,
            "wiki_path": "",  # Not wiki-based
            "title": full_name,
            "symbol_name": full_name,
            "symbol_type": symbol_type,
            "start_line": fn.anchor.line if fn.anchor else 1,
            "end_line": fn.end_line,
            "parent_class": parent_class,
            "language": module.language.value,
        }

    def _make_class_chunk(
        self,
        cls: ClassInfo,
        module: ModuleInfo,
        lines: List[str],
    ) -> Optional[dict]:
        """Build a chunk for a full class."""
        code = self._extract_lines(lines, cls.anchor.line if cls.anchor else 1, cls.end_line)

        method_list = [m.name for m in cls.methods]
        method_summary = ", ".join(method_list) if method_list else "none"

        text = self._build_text(
            symbol_name=cls.name,
            symbol_type="class",
            file_path=module.path,
            language=module.language.value,
            signature=f"class {cls.name}({', '.join(cls.bases)})" if cls.bases else f"class {cls.name}",
            docstring=cls.docstring,
            parent_class=None,
            decorators=cls.decorators,
            extra_meta=f"Methods: [{method_summary}]",
            code=code,
        )

        return {
            "text": text,
            "source": module.path,
            "wiki_path": "",
            "title": cls.name,
            "symbol_name": cls.name,
            "symbol_type": "class",
            "start_line": cls.anchor.line if cls.anchor else 1,
            "end_line": cls.end_line,
            "parent_class": None,
            "language": module.language.value,
        }

    def _make_interface_chunk(
        self,
        iface: InterfaceInfo,
        module: ModuleInfo,
        lines: List[str],
    ) -> Optional[dict]:
        """Build a chunk for a TypeScript interface."""
        code = self._extract_lines(lines, iface.anchor.line if iface.anchor else 1, iface.end_line)

        member_list = ", ".join(
            f"{m.get('name', '?')}: {m.get('type', 'any')}"
            for m in (iface.members or [])
        ) if iface.members else "none"

        text = self._build_text(
            symbol_name=iface.name,
            symbol_type="interface",
            file_path=module.path,
            language=module.language.value,
            signature=f"interface {iface.name}",
            docstring=getattr(iface, 'docstring', None),
            parent_class=None,
            decorators=[],
            extra_meta=f"Members: {{{member_list}}}",
            code=code,
        )

        return {
            "text": text,
            "source": module.path,
            "wiki_path": "",
            "title": iface.name,
            "symbol_name": iface.name,
            "symbol_type": "interface",
            "start_line": iface.anchor.line if iface.anchor else 1,
            "end_line": iface.end_line,
            "parent_class": None,
            "language": module.language.value,
        }

    def _make_component_chunk(
        self,
        comp: ReactComponentInfo,
        module: ModuleInfo,
        lines: List[str],
    ) -> Optional[dict]:
        """Build a chunk for a React component."""
        code = self._extract_lines(lines, comp.anchor.line if comp.anchor else 1, comp.end_line)

        hooks_str = ", ".join(comp.hooks) if comp.hooks else "none"

        text = self._build_text(
            symbol_name=comp.name,
            symbol_type="react-component",
            file_path=module.path,
            language=module.language.value,
            signature=f"function {comp.name}(props: {comp.props_type or 'any'})",
            docstring=getattr(comp, 'docstring', None),
            parent_class=None,
            decorators=[],
            extra_meta=f"Hooks: [{hooks_str}]",
            code=code,
        )

        return {
            "text": text,
            "source": module.path,
            "wiki_path": "",
            "title": comp.name,
            "symbol_name": comp.name,
            "symbol_type": "react-component",
            "start_line": comp.anchor.line if comp.anchor else 1,
            "end_line": comp.end_line,
            "parent_class": None,
            "language": module.language.value,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_source(self, rel_path: str) -> str:
        """Read a source file from the repo."""
        full_path = Path(self.repo_path) / rel_path
        try:
            return full_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as e:
            logger.warning("Cannot read source for chunking: %s: %s", rel_path, e)
            return ""

    @staticmethod
    def _extract_lines(lines: List[str], start: int, end: int) -> str:
        """Extract code lines (1-based, inclusive) with bounds safety."""
        start_line = max(1, int(start)) - 1
        end_line = max(start_line + 1, int(end))
        if start_line >= len(lines):
            return ""
        selected = lines[start_line:end_line]
        return "\n".join(selected)

    @staticmethod
    def _build_text(
        *,
        symbol_name: str,
        symbol_type: str,
        file_path: str,
        language: str,
        signature: str,
        docstring: Optional[str],
        parent_class: Optional[str],
        decorators: List[str],
        code: str,
        extra_meta: Optional[str] = None,
    ) -> str:
        """Build the embedding-ready text representation of a chunk.

        Oversized code bodies are passed through — fine-splitting is
        handled by _fine_split_chunks() at the module level.
        """
        parts = [
            f"Symbol: {symbol_name}",
            f"Type: {symbol_type}",
            f"Language: {language}",
            f"File: {file_path}",
            f"Signature: {signature}",
        ]
        if parent_class:
            parts.append(f"Class: {parent_class}")
        if decorators:
            parts.append(f"Decorators: {', '.join(decorators)}")
        if docstring:
            parts.append(f"Docstring: {docstring}")
        if extra_meta:
            parts.append(extra_meta)

        # Soft-truncate at a high ceiling to avoid pathologically huge chunks
        # Fine-splitting in _fine_split_chunks() handles the real sizing
        code_bytes = code.encode("utf-8")
        SOFT_CEILING = 24_000  # bytes — well above MAX_CHUNK_BYTES, safety net only
        if len(code_bytes) > SOFT_CEILING:
            truncated = _truncate_utf8_safe(code_bytes, SOFT_CEILING)
            code = truncated.decode("utf-8", errors="replace") + TRUNCATE_NOTICE

        parts.append(f"Code:\n{code}")
        return "\n".join(parts)


def _truncate_utf8_safe(data: bytes, max_bytes: int) -> bytes:
    """Truncate bytes at a valid UTF-8 boundary."""
    if len(data) <= max_bytes:
        return data
    truncated = data[:max_bytes]
    while truncated:
        try:
            truncated.decode("utf-8")
            return truncated
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return b""
