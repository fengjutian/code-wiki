"""
JSON-based vector store — simple disk persistence for chunks + embeddings.

Stores two files under ``{wiki_path}/chroma/``:

* ``chunks.json``  – chunk metadata (text, source, title, wiki_path)
* ``embeddings.json`` – parallel list of embedding vectors

Includes an in-memory cache with TTL to avoid repeated disk I/O during
a single request cycle.
"""

import json
import logging
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("code-wiki.embedder")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
INDEX_CACHE_TTL = 300.0          # seconds — index only changes on wiki rebuild
MAX_CHUNK_COUNT = 5000           # cap in-memory chunks to prevent OOM


class JsonVectorStore:
    """Read/write chunks and embeddings to a JSON-backed store on disk."""

    def __init__(self, wiki_path: str):
        self._chroma_path = Path(wiki_path) / "chroma"
        # In-memory cache
        self._cache: Optional[List[dict]] = None
        self._cache_ts: float = 0.0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def save_index(self, chunks: List[dict], embeddings: List[List[float]]):
        """Persist chunks with their embeddings."""
        for chunk, emb in zip(chunks, embeddings):
            chunk["embedding"] = emb
        self.save_raw(chunks)

    def save_raw(self, chunks: List[dict]):
        """Persist chunks and embeddings to disk without mutating input."""
        self._ensure_dir()

        meta_data = []
        emb_data = []
        for c in chunks:
            meta = {k: v for k, v in c.items() if k != "embedding"}
            meta_data.append(meta)
            emb_data.append(c.get("embedding"))

        meta_path = self._chroma_path / "chunks.json"
        emb_path = self._chroma_path / "embeddings.json"

        meta_path.write_text(
            json.dumps(meta_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        emb_path.write_text(
            json.dumps(emb_data, ensure_ascii=False), encoding="utf-8"
        )
        # Invalidate cache
        self._cache = None

    def load_index(self, max_chunks: int = MAX_CHUNK_COUNT) -> List[dict]:
        """Load chunks + embeddings from disk, with in-memory caching.

        *max_chunks* caps how many chunks are loaded into memory at once
        (prevents OOM on very large wikis).  The full file is still on disk;
        only the first *max_chunks* entries are cached and searched.
        """
        now = time.time()
        if (
            self._cache is not None
            and (now - self._cache_ts) < INDEX_CACHE_TTL
        ):
            return self._cache

        meta_path = self._chroma_path / "chunks.json"
        emb_path = self._chroma_path / "embeddings.json"

        if not meta_path.exists():
            self._cache = []
            self._cache_ts = now
            return []

        chunks = json.loads(meta_path.read_text(encoding="utf-8"))

        if emb_path.exists():
            embeddings = json.loads(emb_path.read_text(encoding="utf-8"))
            for c, emb in zip(chunks, embeddings):
                c["embedding"] = emb

        if len(chunks) > max_chunks:
            logger.warning(
                "Index has %d chunks, truncating to %d for in-memory cache",
                len(chunks), max_chunks,
            )
            chunks = chunks[:max_chunks]

        self._cache = chunks
        self._cache_ts = now
        return chunks

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_dir(self):
        self._chroma_path.mkdir(parents=True, exist_ok=True)
