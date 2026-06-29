"""
Vector store embedder — indexes Wiki Markdown pages for RAG retrieval.

Orchestrator that delegates to focused components:

    Embedder
     ├── MarkdownChunker   (services/chunker.py)
     ├── EmbeddingClient   (services/embedding_client.py)
     ├── JsonVectorStore   (services/vector_store.py)
     └── SearchEngine      (services/search.py)

Pipeline:
  WikiPage → chunk (split by ## headings) → Embedding API → JSON index
Retrieval:
  user question → embed query → cosine similarity → Top-K chunks
"""

import logging
from pathlib import Path
from typing import List, Optional

from models.entities import WikiPage
from services.chunker import MarkdownChunker
from services.embedding_client import EmbeddingClient
from services.vector_store import JsonVectorStore
from services.search import SearchEngine

logger = logging.getLogger("code-wiki.embedder")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DEFAULT_TOP_K = 5


class Embedder:
    """
    Manages vector store for Wiki RAG.

    Uses the configured embedding API with cosine similarity retrieval.

    This is now a thin *orchestrator* — chunking, embedding, storage, and
    search are each handled by their own focused class.
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
        self._client = EmbeddingClient(api_key=api_key, base_url=base_url)
        self._store = JsonVectorStore(wiki_path=self.wiki_path)
        self._search = SearchEngine()

    # ------------------------------------------------------------------
    # Chroma path (kept for backward compat — routes/diagrams.py uses it)
    # ------------------------------------------------------------------

    @property
    def chroma_path(self) -> Path:
        return Path(self.wiki_path) / "chroma"

    # ------------------------------------------------------------------
    # Public API — identical to the original
    # ------------------------------------------------------------------

    async def rebuild_index(self, pages: List[WikiPage]):
        """Full rebuild: clear existing index, re-embed all pages."""
        chunks = self._chunker.chunk_pages(pages)
        texts = [c["text"] for c in chunks]
        embeddings = await self._client.embed_texts(texts)
        self._store.save_index(chunks, embeddings)

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

    async def embed_query(self, text: str) -> Optional[List[float]]:
        """Get embedding vector for a query string.

        Returns None when embedding fails or returns a zero vector,
        so the caller can fall back to keyword search cleanly.
        """
        return await self._client.embed_query(text)

    def query(
        self,
        query_text: str,
        top_k: int = DEFAULT_TOP_K,
        query_embedding: Optional[List[float]] = None,
    ) -> List[dict]:
        """
        Search over stored chunks.

        When *query_embedding* is provided, uses cosine similarity for
        semantic ranking.  Otherwise falls back to keyword matching
        (token bigrams + exact phrase bonus).
        """
        chunks = self._store.load_index()
        return self._search.query(chunks, query_text, top_k, query_embedding)

    async def close(self):
        """Close the underlying HTTP client and clear caches."""
        await self._client.close()
        self._store._cache = None
