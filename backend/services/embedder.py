"""
Vector store embedder — indexes source-code AST chunks for RAG retrieval.

Orchestrator that delegates to focused components:

    Embedder
     ├── ASTChunker          (services/ast_chunker.py)
     ├── EmbeddingClient     (services/embedding_client.py)
     ├── FAISSVectorStore    (services/vector_store_faiss.py)
     ├── HybridSearchEngine  (services/hybrid_search.py) ← BM25 + Cosine RRF
     └── Reranker            (services/reranker.py)

Pipeline:
  ModuleInfo → AST chunk (per function/class/method) → Embedding API → FAISS + BM25
Retrieval:
  user question → embed query → BM25 + Cosine RRF → Top-K chunks
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from models.entities import ModuleInfo
from services.ast_chunker import ASTChunker
from services.embedding_client import EmbeddingClient
from services.vector_store_faiss import FAISSVectorStore
from services.hybrid_search import HybridSearchEngine
from services.reranker import Reranker

logger = logging.getLogger("code-wiki.embedder")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DEFAULT_TOP_K = 5
HYBRID_TOP_K = 20   # Candidates to retrieve before optional reranking


class Embedder:
    """Manages vector store for code RAG (FAISS + BM25 hybrid search)."""

    def __init__(
        self,
        repo_path: str,
        wiki_path: str = "",
        api_key: str = "",
        base_url: str = "https://api.deepseek.com",
    ):
        self.repo_path = repo_path
        self.wiki_path = wiki_path or str(Path(self.repo_path) / ".code-wiki")

        self._ast_chunker = ASTChunker(repo_path)
        self._client = EmbeddingClient(api_key=api_key, base_url=base_url)
        self._store = FAISSVectorStore(
            wiki_path=self.wiki_path,
            embedding_client=self._client,
        )
        self._hybrid = HybridSearchEngine(wiki_path=self.wiki_path)
        self._reranker: Optional[Reranker] = None

    # ------------------------------------------------------------------
    # Index build
    # ------------------------------------------------------------------

    async def rebuild_ast_index(self, modules: Dict[str, ModuleInfo]):
        """Rebuild the vector index from analyzed source-code modules.

        Extracts function/class/method-level AST chunks, embeds them ONCE,
        and builds both FAISS and hybrid BM25+Dense index for retrieval.
        """
        chunks = self._ast_chunker.chunk_modules(modules)
        if not chunks:
            logger.warning("ASTChunker produced 0 chunks — index will be empty")
            return

        texts = [c["text"] for c in chunks]
        logger.info("Building FAISS index with %d AST chunks ...", len(texts))

        metadatas = [
            {
                "source": c.get("source", ""),
                "title": c.get("title", ""),
                "symbol_name": c.get("symbol_name", ""),
                "symbol_type": c.get("symbol_type", ""),
                "start_line": c.get("start_line"),
                "end_line": c.get("end_line"),
                "language": c.get("language", ""),
                "parent_class": c.get("parent_class"),
                "wiki_path": c.get("wiki_path", ""),
            }
            for c in chunks
        ]

        embeddings = await self._client.embed_texts(texts)

        self._store.from_embeddings(texts, embeddings, metadatas)
        self._store.save()
        logger.info("FAISS index saved: %d vectors", self._store.count)

        self._hybrid.build_bm25(chunks)

    async def embed_query(self, text: str) -> Optional[List[float]]:
        """Get embedding vector for a query string.

        Returns None when embedding fails, so the caller can fall back
        to keyword-only search.
        """
        return await self._client.embed_query(text)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        query_text: str,
        top_k: int = DEFAULT_TOP_K,
        query_embedding: Optional[List[float]] = None,
    ) -> List[dict]:
        """Hybrid search: BM25 + Cosine RRF fusion → Top-K."""
        if not self._store.is_loaded:
            self._store.load()

        chunks = self._store.get_all_documents()
        if not chunks:
            return []

        return self._hybrid.query(chunks, query_text, top_k, query_embedding)

    def query_with_rerank(
        self,
        query_text: str,
        top_k: int = DEFAULT_TOP_K,
        query_embedding: Optional[List[float]] = None,
        use_reranker: bool = True,
    ) -> List[dict]:
        """Full pipeline: Hybrid search → Reranker → Top-K."""
        if not self._store.is_loaded:
            self._store.load()

        chunks = self._store.get_all_documents()
        if not chunks:
            return []

        candidates = self._hybrid.query(
            chunks, query_text, top_k=HYBRID_TOP_K, query_embedding=query_embedding,
        )
        if not candidates:
            return []

        if use_reranker and len(candidates) > top_k:
            reranker = self._get_reranker()
            if reranker is not None:
                candidates = reranker.rerank(query_text, candidates, top_k=top_k)

        return candidates[:top_k]

    # ------------------------------------------------------------------
    # Reranker (lazy)
    # ------------------------------------------------------------------

    def _get_reranker(self) -> Optional[Reranker]:
        if self._reranker is None:
            self._reranker = Reranker()
        return self._reranker if self._reranker.is_available else None

    async def close(self):
        """Close the underlying HTTP client and clear caches."""
        await self._client.close()
        self._store.clear()
