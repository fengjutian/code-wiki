"""
Hybrid search engine — BM25 (lexical) + Cosine (semantic) with RRF fusion.

Extends the existing SearchEngine with:
1. BM25Okapi index built from chunk texts (using rank_bm25)
2. Parallel BM25 + Cosine retrieval
3. Reciprocal Rank Fusion (RRF) to merge results
4. Optional reranker cross-encoder for final Top-K refinement

The BM25 index is persisted alongside the vector store so it survives restarts.
"""

import json
import logging
import math
from pathlib import Path
from typing import List, Optional, Tuple

from services.search import KeywordTokenizer

logger = logging.getLogger("code-wiki.hybrid_search")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
RRF_K = 60                      # RRF rank constant (higher = less rank-sensitive)
HYBRID_TOP_K = 20               # How many candidates to retrieve before reranking
FINAL_TOP_K = 5                 # Default final results
EXACT_MATCH_BONUS = 20          # SAME as search.py — bonus for verbatim match


class HybridSearchEngine:
    """BM25 + Cosine hybrid search with RRF fusion.

    Persists the BM25 tokenized corpus alongside chunks so the index can
    be reloaded without re-tokenizing on every restart.
    """

    def __init__(self, wiki_path: str = ""):
        self._wiki_path = wiki_path

        # BM25 state
        self._bm25 = None                # BM25Okapi instance
        self._bm25_corpus: List[List[str]] = []  # Tokenized texts (for rebuild)
        self._chunk_texts: List[str] = []        # Raw texts (for keyword fallback)

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def build_bm25(self, chunks: List[dict]):
        """Build BM25 index from chunk texts (lazy import rank_bm25)."""
        texts = [c.get("text", "") for c in chunks]
        self._chunk_texts = texts

        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank_bm25 not installed — hybrid search will use cosine + keyword only")
            self._bm25 = None
            self._bm25_corpus = []
            return

        # Tokenize: use the same CJK-aware tokenizer as keyword search
        tokenized = [KeywordTokenizer.tokenize(t.lower()) for t in texts]
        self._bm25_corpus = tokenized
        self._bm25 = BM25Okapi(tokenized)
        logger.info("BM25 index built: %d documents", len(tokenized))

        # Persist tokenized corpus for reload
        self._save_bm25_corpus(tokenized)

    def load_bm25(self) -> bool:
        """Try to reload BM25 from persisted tokenized corpus. Returns True if loaded."""
        corpus = self._load_bm25_corpus()
        if not corpus:
            return False

        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            return False

        self._bm25_corpus = corpus
        self._bm25 = BM25Okapi(corpus)
        logger.info("BM25 index loaded from disk: %d documents", len(corpus))
        return True

    # ------------------------------------------------------------------
    # Query — hybrid
    # ------------------------------------------------------------------

    def query(
        self,
        chunks: List[dict],
        query_text: str,
        top_k: int = FINAL_TOP_K,
        query_embedding: Optional[List[float]] = None,
    ) -> List[dict]:
        """Hybrid search: BM25 + Cosine → RRF fusion → Top-K.

        Args:
            chunks: List of chunk dicts with optional 'embedding' key.
            query_text: Raw query string.
            top_k: Number of final results to return.
            query_embedding: Optional dense embedding vector.
        """
        if not chunks:
            return []

        # Ensure BM25 is built
        if self._bm25 is None and self._bm25_corpus:
            try:
                from rank_bm25 import BM25Okapi
                self._bm25 = BM25Okapi(self._bm25_corpus)
            except ImportError:
                pass

        # Step 1: Get ranked lists from both retrievers
        bm25_ranked = self._bm25_rank(query_text, top_k=HYBRID_TOP_K)
        dense_ranked = self._dense_rank(chunks, query_embedding, top_k=HYBRID_TOP_K)

        # Step 2: RRF fusion
        fused = self._rrf_fuse(bm25_ranked, dense_ranked, k=RRF_K)

        # Step 3: Resolve to full chunk dicts, return Top-K
        results: List[dict] = []
        for idx, score in fused[:top_k]:
            if 0 <= idx < len(chunks):
                c = chunks[idx]
                results.append({
                    "text": c.get("text", ""),
                    "source": c.get("source", ""),
                    "title": c.get("title", ""),
                    "score": round(score, 4),
                    "chunk_index": idx,
                    "symbol_name": c.get("symbol_name", ""),
                    "symbol_type": c.get("symbol_type", ""),
                    "start_line": c.get("start_line"),
                    "end_line": c.get("end_line"),
                    "language": c.get("language", ""),
                })

        return results

    # ------------------------------------------------------------------
    # BM25 ranking
    # ------------------------------------------------------------------

    def _bm25_rank(self, query_text: str, top_k: int) -> List[Tuple[int, float]]:
        """Return [(chunk_index, bm25_score), ...] sorted descending."""
        if not self._bm25 or not query_text:
            return []

        tokens = KeywordTokenizer.tokenize(query_text.lower())
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        # Pair with indices and sort
        scored = [(i, float(s)) for i, s in enumerate(scores) if s > 0]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    # ------------------------------------------------------------------
    # Dense ranking
    # ------------------------------------------------------------------

    @staticmethod
    def _dense_rank(
        chunks: List[dict],
        query_vec: Optional[List[float]],
        top_k: int,
    ) -> List[Tuple[int, float]]:
        """Return [(chunk_index, cosine_score), ...] sorted descending."""
        if not query_vec:
            return []

        q_norm = math.sqrt(sum(v * v for v in query_vec))
        if q_norm == 0:
            return []

        scored = []
        for i, chunk in enumerate(chunks):
            emb = chunk.get("embedding")
            if not emb:
                continue
            dot = sum(a * b for a, b in zip(query_vec, emb))
            c_norm = math.sqrt(sum(v * v for v in emb))
            if c_norm == 0:
                continue
            score = dot / (q_norm * c_norm)
            scored.append((i, score))

        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    # ------------------------------------------------------------------
    # RRF fusion
    # ------------------------------------------------------------------

    @staticmethod
    def _rrf_fuse(
        list_a: List[Tuple[int, float]],
        list_b: List[Tuple[int, float]],
        k: int = 60,
    ) -> List[Tuple[int, float]]:
        """Reciprocal Rank Fusion — merges two ranked lists.

        Score = 1/(k + rank_in_a) + 1/(k + rank_in_b)

        Returns [(chunk_index, rrf_score), ...] sorted descending.
        """
        scores: dict[int, float] = {}

        for rank, (idx, _) in enumerate(list_a):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)

        for rank, (idx, _) in enumerate(list_b):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)

        fused = sorted(scores.items(), key=lambda x: -x[1])
        return fused

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _bm25_corpus_path(self) -> Path:
        return Path(self._wiki_path) / "faiss_index" / "bm25_corpus.json"

    def _save_bm25_corpus(self, tokenized: List[List[str]]):
        """Persist the tokenized corpus so BM25 can be reloaded."""
        try:
            path = self._bm25_corpus_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(tokenized, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to persist BM25 corpus: %s", e)

    def _load_bm25_corpus(self) -> Optional[List[List[str]]]:
        """Load the persisted tokenized corpus."""
        path = self._bm25_corpus_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load BM25 corpus: %s", e)
            return None
