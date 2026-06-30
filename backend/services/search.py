"""
Keyword tokenizer — CJK-aware, identifier-splitting tokenizer for keyword search.

Used by hybrid_search.py for BM25 index tokenization.
"""

from typing import List


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
