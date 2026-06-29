"""
Vector store embedder — indexes source-code AST chunks for RAG retrieval.

Orchestrator that delegates to focused components:

    Embedder
     ├── ASTChunker          (services/ast_chunker.py)
     ├── EmbeddingClient     (services/embedding_client.py)
     ├── JsonVectorStore     (services/vector_store.py)
     ├── SearchEngine        (services/search.py)       ← legacy, keyword fallback
     └── HybridSearchEngine  (services/hybrid_search.py) ← BM25 + Cosine RRF

Pipeline:
  ModuleInfo → AST chunk (per function/class/method) → Embedding API → JSON index + BM25
Retrieval:
  user question → embed query → BM25 + Cosine RRF → Top-K chunks

Also retains backward-compatible ``rebuild_index(wiki_pages)`` for wiki-based chunks.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from models.entities import WikiPage, ModuleInfo
from services.chunker import MarkdownChunker
from services.ast_chunker import ASTChunker
from services.embedding_client import EmbeddingClient
from services.vector_store import JsonVectorStore
from services.search import SearchEngine
from services.hybrid_search import HybridSearchEngine
from services.reranker import Reranker

logger = logging.getLogger("code-wiki.embedder")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DEFAULT_TOP_K = 5
HYBRID_TOP_K = 20   # Candidates to retrieve before optional reranking


class Embedder:
    """
    Manages vector store for code RAG.

    Supports two indexing modes:
    1. AST chunks (new): ModuleInfo → AST chunks → embeddings → hybrid search
    2. Wiki chunks (legacy): WikiPage → markdown chunks → embeddings → cosine search

    Uses hybrid BM25 + Dense search with optional cross-encoder reranking.
    """

    def __init__(
        self,
        repo_path: str,
        wiki_path: str = "",
        api_key: str = "",
        base_url: str = "https://api.deepseek.com",
    ):
        self.repo_path = repo_path
        self.wiki_path = wiki_path or str(Path(self.repo_path) / ".code-wiki")

        # Components
        self._chunker = MarkdownChunker()
        self._ast_chunker = ASTChunker(repo_path)
        self._client = EmbeddingClient(api_key=api_key, base_url=base_url)
        self._store = JsonVectorStore(wiki_path=self.wiki_path)
        self._search = SearchEngine()
        self._hybrid = HybridSearchEngine(wiki_path=self.wiki_path)
        self._reranker: Optional[Reranker] = None  # Lazy-loaded

    # ------------------------------------------------------------------
    # Chroma path (kept for backward compat — routes/diagrams.py uses it)
    # ------------------------------------------------------------------

    @property
    def chroma_path(self) -> Path:
        return Path(self.wiki_path) / "chroma"

    # ------------------------------------------------------------------
    # Public API — wiki-based (legacy, for backward compat)
    # ------------------------------------------------------------------

    async def rebuild_index(self, pages: List[WikiPage]):
        """Full rebuild: clear existing index, re-embed all wiki pages.

        Uses MarkdownChunker for compatibility with existing wiki pipeline.
        """
        chunks = self._chunker.chunk_pages(pages)
        texts = [c["text"] for c in chunks]
        embeddings = await self._client.embed_texts(texts)
        self._store.save_index(chunks, embeddings)
        # Also build BM25 from wiki chunks for hybrid search
        self._hybrid.build_bm25(chunks)

    async def update_index(self, pages: List[WikiPage]):
        """Incremental update: add/replace chunks for given pages."""
        existing = self._store.load_index()

        # Remove old chunks for these source paths
        source_paths = {p.source_path for p in pages}
        existing = [c for c in existing if c["source"] not in source_paths]

        # Add new chunks
        new_chunks = self._chunker.chunk_pages(pages)
        texts = [c["text"] for c in new_chunks]
        embeddings = await self._client.embed_texts(texts)

        for chunk, emb in zip(new_chunks, embeddings):
            chunk["embedding"] = emb
        existing.extend(new_chunks)

        self._store.save_raw(existing)
        self._hybrid.build_bm25(existing)

    # ------------------------------------------------------------------
    # Public API — AST-chunk based (new, for code-level RAG)
    # ------------------------------------------------------------------

    async def rebuild_ast_index(self, modules: Dict[str, ModuleInfo]):
        """Rebuild the vector index from analyzed source-code modules.

        Extracts function/class/method-level chunks, embeds them, and
        builds a hybrid BM25 + Dense index for retrieval.
        """
        chunks = self._ast_chunker.chunk_modules(modules)
        if not chunks:
            logger.warning("ASTChunker produced 0 chunks — index will be empty")
            return

        texts = [c["text"] for c in chunks]
        logger.info("Embedding %d AST chunks ...", len(texts))
        embeddings = await self._client.embed_texts(texts)
        self._store.save_index(chunks, embeddings)

        # Build hybrid search index (BM25 + cosine)
        self._hybrid.build_bm25(chunks)

    async def embed_query(self, text: str) -> Optional[List[float]]:
        """Get embedding vector for a query string.

        Returns None when embedding fails or returns a zero vector,
        so the caller can fall back to keyword search cleanly.
        """
        return await self._client.embed_query(text)

    # ------------------------------------------------------------------
    # Query — hybrid search (new)
    # ------------------------------------------------------------------

    def query(
        self,
        query_text: str,
        top_k: int = DEFAULT_TOP_K,
        query_embedding: Optional[List[float]] = None,
    ) -> List[dict]:
        """
        Hybrid search: BM25 + Cosine RRF fusion → Top-K.

        Falls back to legacy SearchEngine if BM25 is not available.
        """
        chunks = self._store.load_index()

        # Try to use hybrid engine if chunks available
        if self._hybrid._bm25 is not None:
            return self._hybrid.query(chunks, query_text, top_k, query_embedding)

        # Fallback to legacy search (cosine only or keyword only)
        return self._search.query(chunks, query_text, top_k, query_embedding)

    def query_with_rerank(
        self,
        query_text: str,
        top_k: int = DEFAULT_TOP_K,
        query_embedding: Optional[List[float]] = None,
        use_reranker: bool = True,
    ) -> List[dict]:
        """
        Full pipeline: Hybrid search → Reranker → Top-K.

        Retrieves HYBRID_TOP_K candidates via BM25+Cosine RRF, then
        re-ranks with cross-encoder to select the final Top-K.
        """
        chunks = self._store.load_index()

        # Step 1: Hybrid retrieval (Top-20 candidates)
        if self._hybrid._bm25 is not None:
            candidates = self._hybrid.query(
                chunks, query_text, top_k=HYBRID_TOP_K, query_embedding=query_embedding,
            )
        else:
            candidates = self._search.query(
                chunks, query_text, top_k=HYBRID_TOP_K, query_embedding=query_embedding,
            )

        if not candidates:
            return []

        # Step 2: Rerank (optional)
        if use_reranker and len(candidates) > top_k:
            reranker = self._get_reranker()
            if reranker is not None:
                candidates = reranker.rerank(query_text, candidates, top_k=top_k)

        return candidates[:top_k]

    # ------------------------------------------------------------------
    # Reranker (lazy)
    # ------------------------------------------------------------------

    def _get_reranker(self) -> Optional[Reranker]:
        """Lazy-load the reranker on first use."""
        if self._reranker is None:
            self._reranker = Reranker()
        return self._reranker if self._reranker.is_available else None

    async def close(self):
        """Close the underlying HTTP client and clear caches."""
        await self._client.close()
        self._store.clear_cache()
