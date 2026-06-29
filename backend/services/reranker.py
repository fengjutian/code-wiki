"""
Cross-Encoder Reranker — refines top candidates from hybrid search.

Uses BGE-Reranker-v2-m3 (BAAI) to compute fine-grained relevance scores
for (query, candidate) pairs, selecting the most relevant Top-5 from
a larger candidate pool (Top-20).

Lazy-loads the model on first use to avoid startup cost and GPU memory
when not needed.
"""

import logging
from typing import List, Optional

logger = logging.getLogger("code-wiki.reranker")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
FALLBACK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker:
    """Cross-encoder reranker using FlagEmbedding (BGE-Reranker).

    Usage::

        reranker = Reranker()
        top5 = reranker.rerank(query, top20_chunks, top_k=5)
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        use_fp16: bool = True,
    ):
        self._model_name = model_name
        self._use_fp16 = use_fp16
        self._model = None
        self._init_attempted = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        candidates: List[dict],
        top_k: int = 5,
    ) -> List[dict]:
        """Rerank candidates using cross-encoder scoring.

        Args:
            query: The search query text.
            candidates: List of chunk dicts with at least 'text' key.
            top_k: How many results to return.

        Returns:
            Top-K candidates reordered by cross-encoder score.
        """
        if not candidates:
            return []

        if len(candidates) <= top_k:
            # No need to rerank — not enough candidates
            for c in candidates:
                c["rerank_score"] = c.get("score", 0.0)
            return candidates

        # Lazy init
        model = self._get_model()
        if model is None:
            # Fallback: return candidates as-is (keep hybrid scores)
            logger.warning("Reranker model unavailable — returning un-reranked results")
            candidates[0]["rerank_score"] = candidates[0].get("score", 0.0)
            return candidates[:top_k]

        # Build pairs
        pairs = [[query, c.get("text", "")] for c in candidates]

        try:
            scores = model.compute_score(
                pairs,
                batch_size=min(len(pairs), 16),
                normalize=True,
            )
        except Exception as e:
            logger.warning("Reranker compute failed: %s — falling back to original order", e)
            for c in candidates:
                c["rerank_score"] = c.get("score", 0.0)
            return candidates[:top_k]

        # Handle single score vs list
        if not isinstance(scores, list):
            scores = [scores]

        # Attach scores and sort
        for c, s in zip(candidates, scores):
            c["rerank_score"] = round(float(s), 4)

        candidates.sort(key=lambda c: c.get("rerank_score", 0), reverse=True)
        return candidates[:top_k]

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _get_model(self):
        """Lazy-load the reranker model (called on first use)."""
        if self._model is not None:
            return self._model
        if self._init_attempted:
            return None

        self._init_attempted = True

        # Try BGE-Reranker first (best quality)
        try:
            from FlagEmbedding import FlagReranker
            logger.info("Loading reranker: %s (use_fp16=%s)", self._model_name, self._use_fp16)
            self._model = FlagReranker(
                self._model_name,
                use_fp16=self._use_fp16,
            )
            logger.info("Reranker loaded successfully")
            return self._model
        except ImportError:
            logger.warning(
                "FlagEmbedding not installed (pip install FlagEmbedding). "
                "Reranker will be disabled."
            )
        except Exception as e:
            logger.warning(
                "Failed to load %s: %s. Trying fallback %s ...",
                self._model_name, e, FALLBACK_MODEL,
            )

        # Try sentence-transformers fallback (lighter, works offline)
        try:
            from sentence_transformers import CrossEncoder
            logger.info("Loading fallback reranker: %s", FALLBACK_MODEL)
            self._model = CrossEncoder(FALLBACK_MODEL)
            logger.info("Fallback reranker loaded successfully")
            return self._model
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Install 'FlagEmbedding' or 'sentence-transformers' for reranking."
            )
        except Exception as e:
            logger.warning("Failed to load fallback reranker: %s", e)

        return None

    @property
    def is_available(self) -> bool:
        """Return True if the reranker model can be loaded."""
        return self._get_model() is not None
