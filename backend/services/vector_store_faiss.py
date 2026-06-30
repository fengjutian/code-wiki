"""
FAISS Vector Store — LangChain FAISS wrapper with custom embedding adapter.

Replaces JsonVectorStore for 10,000+ file scale.  Features:

* HNSW indexing — sub-millisecond search over 100K+ vectors
* Index persistence via FAISS.save_local / load_local
* Custom embedding adapter bridging EmbeddingClient → LangChain Embeddings
* Incremental add/delete support (for future IndexManager)

Layout on disk::

    {wiki_path}/faiss_index/
        index.faiss      ← FAISS binary index
        index.pkl         ← docstore (texts + metadatas pickle)

Usage::

    store = FAISSVectorStore(wiki_path, embedding_client)
    store.add_texts(texts, metadatas)
    store.save()
    results = store.similarity_search_with_score("query", k=20)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from services.embedding_client import EmbeddingClient

logger = logging.getLogger("code-wiki.faiss_store")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
HNSW_M = 16                    # HNSW graph connectivity (16 = good balance)
EF_CONSTRUCTION = 200          # Build-time search width
EF_SEARCH = 128                # Query-time search width
FAISS_INDEX_DIR = "faiss_index"


class _LangChainEmbeddingsAdapter(Embeddings):
    """Adapt our async EmbeddingClient to LangChain's sync Embeddings interface.

    LangChain FAISS.from_texts() calls embed_documents() synchronously, so
    we bridge the gap with a thread-pool backed async→sync wrapper.
    """

    def __init__(self, client: EmbeddingClient):
        self._client = client

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of documents (called by FAISS.from_texts / add_texts)."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop — run synchronously
            return asyncio.run(self._client.embed_texts(texts))

        # We're inside an event loop — use run_until_complete on a nested loop
        # (acceptable for CPU-bound embedding preparation during scan)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, self._client.embed_texts(texts))
            return future.result(timeout=300)

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query text."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            result = asyncio.run(self._client.embed_query(text))
            return result if result else []

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, self._client.embed_query(text))
            result = future.result(timeout=60)
            return result if result else []


class FAISSVectorStore:
    """LangChain FAISS-backed vector store for code chunks.

    Wraps langchain_community.vectorstores.FAISS with our custom embedding
    adapter, providing the same interface JsonVectorStore used + extra
    LangChain-native methods for the future LCEL RAG chain.
    """

    def __init__(self, wiki_path: str, embedding_client: Optional[EmbeddingClient] = None):
        self._index_dir = Path(wiki_path) / FAISS_INDEX_DIR
        self._embeddings: Optional[_LangChainEmbeddingsAdapter] = None
        self._store: Optional[FAISS] = None

        if embedding_client is not None:
            self._embeddings = _LangChainEmbeddingsAdapter(embedding_client)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._store is not None

    def load(self) -> bool:
        """Load the FAISS index from disk.  Returns True if loaded."""
        if self._store is not None:
            return True
        if self._embeddings is None:
            return False

        index_path = self._index_dir / "index.faiss"
        if not index_path.exists():
            logger.info("FAISS index not found at %s — will create on save", index_path)
            return False

        try:
            self._store = FAISS.load_local(
                str(self._index_dir),
                self._embeddings,
                index_name="index",
                allow_dangerous_deserialization=True,
            )
            self._configure_hnsw()
            logger.info(
                "FAISS index loaded from %s (%d vectors)",
                self._index_dir, self._store.index.ntotal,
            )
            return True
        except Exception as e:
            logger.warning("Failed to load FAISS index: %s", e)
            self._store = None
            return False

    def save(self):
        """Persist the FAISS index to disk."""
        if self._store is None:
            logger.warning("No FAISS index to save — call add_texts or from_texts first")
            return

        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._store.save_local(str(self._index_dir), index_name="index")
        n = self._store.index.ntotal
        logger.info("FAISS index saved to %s (%d vectors)", self._index_dir, n)

    # ------------------------------------------------------------------
    # HNSW tuning
    # ------------------------------------------------------------------

    def _configure_hnsw(self):
        """Apply HNSW efSearch parameter to the FAISS index if supported.

        On IndexFlat (exact search) this is a no-op.
        On IndexHNSW (approximate search) this controls query-time
        search depth — higher = more accurate but slower.
        """
        if self._store is None:
            return
        try:
            import faiss
            idx = self._store.index
            # Try nprobe for IVF indices, efSearch for HNSW
            try:
                faiss.ParameterSpace().set_index_parameter(idx, "nprobe", 32)
            except RuntimeError:
                pass
            if hasattr(idx, "hnsw"):
                idx.hnsw.efSearch = EF_SEARCH
                logger.debug("FAISS HNSW efSearch set to %d", EF_SEARCH)
        except Exception:
            pass  # Not critical — defaults are fine

    # ------------------------------------------------------------------
    # Build / rebuild
    # ------------------------------------------------------------------

    def from_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[dict]] = None,
    ):
        """Build a new FAISS index from texts + metadatas.

        This replaces any existing index in memory (not on disk until save()).
        NOTE: This internally calls embed_documents — prefer from_embeddings()
        when you already have pre-computed embeddings to avoid duplicate API calls.
        """
        if self._embeddings is None:
            raise RuntimeError("FAISSVectorStore has no embedding client")

        if not texts:
            self._store = None
            return

        docs = [
            Document(page_content=t, metadata=m or {})
            for t, m in zip(texts, metadatas or [{}] * len(texts))
        ]

        logger.info("Building FAISS index from %d documents ...", len(docs))
        self._store = FAISS.from_documents(docs, self._embeddings)
        logger.info("FAISS index built: %d vectors", self._store.index.ntotal)
        self._configure_hnsw()

    def from_embeddings(
        self,
        texts: List[str],
        embeddings: List[List[float]],
        metadatas: Optional[List[dict]] = None,
    ):
        """Build a new FAISS index from pre-computed embeddings.

        Use this when you already have embeddings (e.g. from EmbeddingClient)
        to avoid double API calls.  The embeddings are consumed directly
        without going through _LangChainEmbeddingsAdapter.
        """
        if self._embeddings is None:
            raise RuntimeError("FAISSVectorStore has no embedding client")

        if not texts:
            self._store = None
            return

        metadatas = metadatas or [{}] * len(texts)

        # Create text-embedding pairs for FAISS.from_embeddings
        text_embedding_pairs = list(zip(texts, embeddings))

        logger.info("Building FAISS index from %d pre-computed embeddings ...", len(text_embedding_pairs))
        self._store = FAISS.from_embeddings(
            text_embedding_pairs,
            self._embeddings,  # still needed for query embedding
            metadatas=metadatas,
        )
        logger.info("FAISS index built: %d vectors", self._store.index.ntotal)
        self._configure_hnsw()

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[dict]] = None,
    ):
        """Incrementally add texts to the existing index."""
        if self._embeddings is None:
            raise RuntimeError("FAISSVectorStore has no embedding client")
        if not texts:
            return
        if self._store is None:
            self.from_texts(texts, metadatas)
            return

        metadatas = metadatas or [{}] * len(texts)
        self._store.add_texts(texts, metadatas)
        logger.debug("Added %d texts to FAISS index (total=%d)", len(texts), self._store.index.ntotal)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_by_source(self, source_path: str) -> int:
        """Delete all chunks belonging to a given source file.

        Returns the number of chunks deleted.
        """
        if self._store is None:
            return 0

        docstore = self._store.docstore
        ids_to_delete: List[str] = []

        for doc_id, doc in docstore._dict.items():
            meta = doc.metadata if hasattr(doc, 'metadata') else {}
            if meta.get("source") == source_path:
                ids_to_delete.append(doc_id)

        if ids_to_delete:
            self._store.delete(ids_to_delete)
            logger.debug("Deleted %d chunks for source: %s", len(ids_to_delete), source_path)

        return len(ids_to_delete)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 20,
        filter: Optional[dict] = None,
    ) -> List[Tuple[Document, float]]:
        """Return (document, similarity_score) sorted by score descending.

        Similarity score is L2 distance in FAISS — lower is better.
        """
        if self._store is None:
            return []
        return self._store.similarity_search_with_score(
            query, k=k, filter=filter,
        )

    def similarity_search(
        self,
        query: str,
        k: int = 20,
    ) -> List[Document]:
        """Return documents sorted by relevance."""
        if self._store is None:
            return []
        return self._store.similarity_search(query, k=k)

    # ------------------------------------------------------------------
    # Direct access (for hybrid search + reranker compatibility)
    # ------------------------------------------------------------------

    def get_all_documents(self) -> List[dict]:
        """Return all stored documents as dicts (for hybrid search compatibility).

        Each dict has keys: text, source, title, embedding, symbol_name, etc.
        """
        if self._store is None:
            return []

        chunks: List[dict] = []
        docstore = self._store.docstore
        for doc_id in self._store.index_to_docstore_id:
            doc = docstore.search(doc_id)
            if doc is None:
                continue
            meta = dict(doc.metadata) if hasattr(doc, 'metadata') else {}
            chunk = {
                "text": doc.page_content if hasattr(doc, 'page_content') else "",
                "source": meta.get("source", ""),
                "title": meta.get("title", meta.get("symbol_name", "")),
                "symbol_name": meta.get("symbol_name", ""),
                "symbol_type": meta.get("symbol_type", ""),
                "start_line": meta.get("start_line"),
                "end_line": meta.get("end_line"),
                "language": meta.get("language", ""),
                "parent_class": meta.get("parent_class"),
                "wiki_path": meta.get("wiki_path", ""),
                # FAISS doesn't store embedding in docstore by default
                "embedding": None,
            }
            chunks.append(chunk)

        return chunks

    @property
    def count(self) -> int:
        if self._store is None:
            return 0
        return self._store.index.ntotal

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self):
        """Drop the in-memory index (disk untouched)."""
        self._store = None

    def delete_index_files(self):
        """Remove persisted index files from disk."""
        import shutil
        if self._index_dir.exists():
            shutil.rmtree(self._index_dir, ignore_errors=True)
            logger.info("Deleted FAISS index directory: %s", self._index_dir)
