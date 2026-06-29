"""
Vector store embedder — indexes Wiki Markdown pages for RAG retrieval.

Pipeline:
  WikiPage → chunk (split by ## headings) → Embedding API → JSON index
Retrieval:
  user question → embed query → cosine similarity → Top-K chunks
"""

import json
import logging
import math
import time
from pathlib import Path
from typing import List, Dict, Optional

from httpx import AsyncClient, Timeout

from models.entities import WikiPage

logger = logging.getLogger("code-wiki.embedder")


class Embedder:
    """
    Manages vector store for Wiki RAG.

    Uses the configured embedding API with cosine similarity retrieval.
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
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client: Optional[AsyncClient] = None
        # In-memory cache for loaded index (avoids repeated I/O)
        self._index_cache: Optional[List[dict]] = None
        self._index_cache_ts: float = 0
        self._INDEX_CACHE_TTL: float = 300.0  # seconds — index only changes on wiki rebuild

    @property
    def chroma_path(self) -> Path:
        return Path(self.wiki_path) / "chroma"

    @property
    def client(self) -> AsyncClient:
        if self._client is None:
            self._client = AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=Timeout(30.0),
            )
        return self._client

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._index_cache = None

    # ---- Public API ----

    async def rebuild_index(self, pages: List[WikiPage]):
        """Full rebuild: clear existing index, re-embed all pages."""
        self._ensure_chroma_dir()

        # Chunk all pages
        chunks = self._chunk_pages(pages)

        # Get embeddings
        texts = [c["text"] for c in chunks]
        embeddings = await self._embed_texts(texts)

        # Save to JSON-based index (simple, no Chroma server needed)
        self._save_index(chunks, embeddings)

    async def update_index(self, pages: List[WikiPage]):
        """Incremental update: add/replace chunks for given pages."""
        self._ensure_chroma_dir()

        # Load existing index
        existing = self._load_index()

        # Remove old chunks for these source paths
        source_paths = {p.source_path for p in pages}
        existing = [c for c in existing if c["source"] not in source_paths]

        # Add new chunks
        new_chunks = self._chunk_pages(pages)
        texts = [c["text"] for c in new_chunks]
        embeddings = await self._embed_texts(texts)

        # Merge
        for chunk, emb in zip(new_chunks, embeddings):
            chunk["embedding"] = emb
        existing.extend(new_chunks)

        self._save_raw(existing)

    async def embed_query(self, text: str) -> Optional[List[float]]:
        """Get embedding vector for a query string.
        
        Returns None when embedding fails or returns a zero vector,
        so the caller can fall back to keyword search cleanly.
        """
        try:
            embeddings = await self._embed_texts([text])
            if embeddings and embeddings[0]:
                vec = embeddings[0]
                # Detect zero-vector fallback from _embed_texts
                if any(v != 0.0 for v in vec):
                    return vec
        except Exception as e:
            logger.warning(f"Query embedding failed: {e}")
        return None

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        query_embedding: Optional[List[float]] = None,
    ) -> List[dict]:
        """
        Search over stored chunks.

        When *query_embedding* is provided, uses cosine similarity for
        semantic ranking.  Otherwise falls back to keyword matching
        (token bigrams + exact phrase bonus).
        """
        chunks = self._load_index()
        if not chunks:
            return []

        if query_embedding:
            return self._semantic_search(chunks, query_embedding, top_k)
        return self._keyword_search(chunks, query_text, top_k)

    def _semantic_search(
        self,
        chunks: List[dict],
        query_vec: List[float],
        top_k: int,
    ) -> List[dict]:
        """Rank chunks by cosine similarity to *query_vec*."""
        q_norm = math.sqrt(sum(v * v for v in query_vec))
        if q_norm == 0:
            return self._keyword_search(chunks, "", top_k)

        scored = []
        for chunk in chunks:
            emb = chunk.get("embedding")
            if not emb:
                continue
            # Cosine similarity
            dot = sum(a * b for a, b in zip(query_vec, emb))
            c_norm = math.sqrt(sum(v * v for v in emb))
            if c_norm == 0:
                continue
            score = dot / (q_norm * c_norm)
            scored.append((score, chunk))

        scored.sort(key=lambda x: -x[0])
        return [
            {
                "text": c["text"],
                "source": c["source"],
                "title": c["title"],
                "score": round(s, 4),
            }
            for s, c in scored[:top_k]
        ]

    def _keyword_search(
        self,
        chunks: List[dict],
        query_text: str,
        top_k: int,
    ) -> List[dict]:
        """Fallback: token bigram + exact phrase matching."""
        query_lower = query_text.lower()
        tokens = self._tokenise(query_lower) if query_lower else []
        if not tokens:
            return []

        scored = []
        for chunk in chunks:
            text_lower = chunk["text"].lower()
            score = sum(
                len(token) for token in tokens if token in text_lower
            )
            if query_lower and query_lower in text_lower:
                score += 20
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: -x[0])
        return [
            {
                "text": c["text"],
                "source": c["source"],
                "title": c["title"],
                "score": s,
            }
            for s, c in scored[:top_k]
        ]

    @staticmethod
    def _tokenise(text: str) -> List[str]:
        """Split text into search tokens.
        
        Space-separated words stay as-is, plus sub-word splitting for
        camelCase/PascalCase/snake_case/kebab-case identifiers.
        CJK spans (no spaces) are split into overlapping character bigrams.
        """
        tokens: List[str] = []
        # Split by whitespace first
        for part in text.split():
            if not part:
                continue
            # If the part contains CJK characters, generate bigrams
            if Embedder._has_cjk(part):
                tokens.extend(Embedder._cjk_bigrams(part))
            else:
                tokens.append(part)
                # Also split camelCase/PascalCase/snake_case/kebab-case
                sub_tokens = Embedder._split_identifier(part)
                for st in sub_tokens:
                    st_lower = st.lower()
                    if st_lower not in tokens:
                        tokens.append(st_lower)
        return tokens

    @staticmethod
    def _split_identifier(text: str) -> List[str]:
        """Split camelCase/PascalCase/snake_case/kebab-case into sub-words.
        e.g. 'getUserById' -> ['get', 'User', 'ById', 'By', 'Id']
             'user_service_impl' -> ['user', 'service', 'impl']
        """
        parts: List[str] = []
        # First split by separators
        for seg in text.replace('_', ' ').replace('-', ' ').split():
            if not seg:
                continue
            # Split camelCase/PascalCase
            current = seg[0]
            for ch in seg[1:]:
                if ch.isupper() and current and not current[-1].isupper():
                    parts.append(current)
                    current = ch
                elif ch.islower() and len(current) >= 2 and current[-1].isupper() and current[-2].isupper():
                    # Transition: 'BYId' -> ['BY', 'Id']
                    parts.append(current[:-1])
                    current = current[-1] + ch
                else:
                    current += ch
            if current:
                parts.append(current)
        return [p for p in parts if len(p) >= 2]

    @staticmethod
    def _has_cjk(text: str) -> bool:
        """Return True if text contains any CJK character."""
        for ch in text:
            cp = ord(ch)
            if (0x4E00 <= cp <= 0x9FFF or   # CJK Unified Ideographs
                0x3400 <= cp <= 0x4DBF or   # CJK Unified Ideographs Extension A
                0xF900 <= cp <= 0xFAFF or   # CJK Compatibility Ideographs
                0x3040 <= cp <= 0x309F or   # Hiragana
                0x30A0 <= cp <= 0x30FF or   # Katakana
                0xAC00 <= cp <= 0xD7AF):    # Hangul
                return True
        return False

    @staticmethod
    def _cjk_bigrams(text: str) -> List[str]:
        """Generate overlapping character bigrams from CJK text.
        e.g. '订单模块' → ['订单', '单模', '模块']
        """
        if len(text) <= 2:
            return [text]
        return [text[i:i+2] for i in range(len(text) - 1)]

    # ---- Chunking ----

    # Sentinels used during chunking to protect fenced code blocks
    _CODE_SENTINEL = "\x00CD\x00"

    def _chunk_pages(self, pages: List[WikiPage]) -> List[dict]:
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
                    title = section[:first_newline].strip("# ").strip() if first_newline > 0 else section.strip()
                else:
                    first_newline = section.find("\n")
                    title = section[:first_newline].strip() if first_newline > 0 else section.strip()
                    body = "## " + section

                if len(body.strip()) < 50:
                    continue

                # Safe truncation on UTF-8 boundary
                safe_body = self._truncate_safe(body, 3000)
                chunks.append(
                    {
                        "text": safe_body,
                        "source": page.source_path,
                        "wiki_path": page.path,
                        "title": title or page.path,
                    }
                )
        return chunks

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
            if text[i:i + 3] == "```" and not in_fence:
                in_fence = True
                fence_buf = ["```"]
                i += 3
            elif text[i:i + 3] == "```" and in_fence:
                fence_buf.append("```")
                idx = len(fences)
                fences.append("".join(fence_buf))
                result.append(f"{self._CODE_SENTINEL}{idx}{self._CODE_SENTINEL}")
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

    @staticmethod
    def _truncate_safe(text: str, max_bytes: int) -> str:
        """Truncate text to at most *max_bytes* UTF-8 bytes,
        without splitting a multi-byte character."""
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        # Walk back to a valid UTF-8 boundary
        truncated = encoded[:max_bytes]
        # Strip incomplete trailing bytes (10xxxxxx continuation bytes)
        while truncated:
            try:
                return truncated.decode("utf-8")
            except UnicodeDecodeError:
                truncated = truncated[:-1]
        return ""

    # ---- Embedding ----

    async def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings from DeepSeek API (or return zeros on failure)."""
        if not texts:
            return []

        # Try batch embedding
        try:
            response = await self.client.post(
                "/v1/embeddings",
                json={
                    "model": "deepseek-embed",
                    "input": texts,
                },
            )
            response.raise_for_status()
            data = response.json()
            return [d["embedding"] for d in data["data"]]
        except Exception as e:
            logging.warning(f"Embedding API failed ({e}), returning zero vectors (keyword search fallback)")
            return [[0.0] * 128 for _ in texts]

    # ---- Persistence ----

    def _ensure_chroma_dir(self):
        self.chroma_path.mkdir(parents=True, exist_ok=True)

    def _save_index(self, chunks: List[dict], embeddings: List[List[float]]):
        for chunk, emb in zip(chunks, embeddings):
            chunk["embedding"] = emb
        self._save_raw(chunks)

    def _save_raw(self, chunks: List[dict]):
        """Persist chunks and embeddings to disk without mutating input."""
        meta_data = []
        emb_data = []
        for c in chunks:
            # Copy metadata, omitting the embedding
            meta = {k: v for k, v in c.items() if k != "embedding"}
            meta_data.append(meta)
            emb_data.append(c.get("embedding"))

        meta_path = self.chroma_path / "chunks.json"
        emb_path = self.chroma_path / "embeddings.json"

        meta_path.write_text(
            json.dumps(meta_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        emb_path.write_text(
            json.dumps(emb_data, ensure_ascii=False), encoding="utf-8"
        )
        # Invalidate in-memory cache
        self._index_cache = None

    def _load_index(self, max_chunks: int = 5000) -> List[dict]:
        """Load chunks + embeddings from disk, with in-memory caching.

        *max_chunks* caps how many chunks are loaded into memory at once
        (prevents OOM on very large wikis).  The full file is still on disk;
        only the first *max_chunks* entries are cached and searched.
        """
        now = time.time()
        if (
            self._index_cache is not None
            and (now - self._index_cache_ts) < self._INDEX_CACHE_TTL
        ):
            return self._index_cache

        meta_path = self.chroma_path / "chunks.json"
        emb_path = self.chroma_path / "embeddings.json"

        if not meta_path.exists():
            self._index_cache = []
            self._index_cache_ts = now
            return []

        chunks = json.loads(meta_path.read_text(encoding="utf-8"))

        if emb_path.exists():
            embeddings = json.loads(emb_path.read_text(encoding="utf-8"))
            for c, emb in zip(chunks, embeddings):
                c["embedding"] = emb

        # Cap at max_chunks to prevent OOM on very large wikis
        if len(chunks) > max_chunks:
            logger.warning(f"Index has {len(chunks)} chunks, truncating to {max_chunks} for in-memory cache")
            chunks = chunks[:max_chunks]

        self._index_cache = chunks
        self._index_cache_ts = now
        return chunks
