"""
Search engine — semantic (cosine) and keyword retrieval over chunks.

Also includes CJK-aware tokenisation for keyword matching.
"""

import math
from typing import List, Optional

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DEFAULT_TOP_K = 5
EXACT_MATCH_BONUS = 20            # Score bonus when the full query appears verbatim


class SearchEngine:
    """Stateless search over in-memory chunks."""

    def query(
        self,
        chunks: List[dict],
        query_text: str,
        top_k: int = DEFAULT_TOP_K,
        query_embedding: Optional[List[float]] = None,
    ) -> List[dict]:
        """Search over *chunks*.

        When *query_embedding* is provided, uses cosine similarity for
        semantic ranking.  Otherwise falls back to keyword matching.
        """
        if not chunks:
            return []

        if query_embedding:
            return self._semantic_search(chunks, query_embedding, top_k)
        return self._keyword_search(chunks, query_text, top_k)

    # ------------------------------------------------------------------
    # Semantic (cosine similarity)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Keyword (token bigram + exact match)
    # ------------------------------------------------------------------

    def _keyword_search(
        self,
        chunks: List[dict],
        query_text: str,
        top_k: int,
    ) -> List[dict]:
        """Fallback: token bigram + exact phrase matching."""
        query_lower = query_text.lower()
        tokens = KeywordTokenizer.tokenize(query_lower) if query_lower else []
        if not tokens:
            return []

        scored = []
        for chunk in chunks:
            text_lower = chunk["text"].lower()
            score = sum(
                len(token) for token in tokens if token in text_lower
            )
            if query_lower and query_lower in text_lower:
                score += EXACT_MATCH_BONUS
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


# ---------------------------------------------------------------------------
# Tokenization (extracted as its own tiny namespace)
# ---------------------------------------------------------------------------

class KeywordTokenizer:
    """CJK-aware, identifier-splitting tokenizer for keyword search."""

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Split text into search tokens.

        Space-separated words stay as-is, plus sub-word splitting for
        camelCase/PascalCase/snake_case/kebab-case identifiers.
        CJK spans (no spaces) are split into overlapping character bigrams.
        """
        tokens: List[str] = []
        for part in text.split():
            if not part:
                continue
            if KeywordTokenizer._has_cjk(part):
                tokens.extend(KeywordTokenizer._cjk_bigrams(part))
            else:
                tokens.append(part)
                sub_tokens = KeywordTokenizer._split_identifier(part)
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
        for seg in text.replace("_", " ").replace("-", " ").split():
            if not seg:
                continue
            current = seg[0]
            for ch in seg[1:]:
                if ch.isupper() and current and not current[-1].isupper():
                    parts.append(current)
                    current = ch
                elif (
                    ch.islower()
                    and len(current) >= 2
                    and current[-1].isupper()
                    and current[-2].isupper()
                ):
                    parts.append(current[:-1])
                    current = current[-1] + ch
                else:
                    current += ch
            if current:
                parts.append(current)
        return [p for p in parts if len(p) >= 2]

    # ------------------------------------------------------------------
    # CJK helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_cjk(text: str) -> bool:
        """Return True if text contains any CJK character."""
        for ch in text:
            cp = ord(ch)
            if (
                0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
                or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
                or 0xF900 <= cp <= 0xFAFF  # CJK Compatibility
                or 0x3040 <= cp <= 0x309F  # Hiragana
                or 0x30A0 <= cp <= 0x30FF  # Katakana
                or 0xAC00 <= cp <= 0xD7AF  # Hangul
            ):
                return True
        return False

    @staticmethod
    def _cjk_bigrams(text: str) -> List[str]:
        """Generate overlapping character bigrams from CJK text.

        e.g. '订单模块' → ['订单', '单模', '模块']
        """
        if len(text) <= 2:
            return [text]
        return [text[i : i + 2] for i in range(len(text) - 1)]
