"""
Embedding API client — talks to the configured embedding provider.

Currently targets the DeepSeek /v1/embeddings endpoint, but the interface
is narrow enough to swap in OpenAI / Jina / Voyage providers later.
"""

import logging
from typing import List, Optional

from httpx import AsyncClient, Timeout

logger = logging.getLogger("code-wiki.embedder")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
ZERO_VECTOR_DIM = 128            # Dimension of a zero fallback vector
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-embed"
REQUEST_TIMEOUT = 30.0           # seconds


class EmbeddingClient:
    """Async client for the embedding API.

    Construction::

        client = EmbeddingClient(api_key="sk-…", base_url="https://…")
        vecs = await client.embed_texts(["hello", "world"])
        await client.close()
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client: Optional[AsyncClient] = None

    @property
    def client(self) -> AsyncClient:
        if self._client is None:
            self._client = AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=Timeout(REQUEST_TIMEOUT),
            )
        return self._client

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for a batch of texts.

        Returns zero vectors on failure so the caller can fall back to
        keyword search without crashing.
        """
        if not texts:
            return []

        try:
            response = await self.client.post(
                "/v1/embeddings",
                json={
                    "model": DEFAULT_MODEL,
                    "input": texts,
                },
            )
            response.raise_for_status()
            data = response.json()
            return [d["embedding"] for d in data["data"]]
        except Exception as e:
            logger.warning(
                "Embedding API failed (%s), returning zero vectors "
                "(keyword search fallback)", e
            )
            return [[0.0] * ZERO_VECTOR_DIM for _ in texts]

    async def embed_query(self, text: str) -> Optional[List[float]]:
        """Get embedding vector for a single query string.

        Returns ``None`` when embedding fails or returns a zero vector,
        so the caller can fall back to keyword search cleanly.
        """
        try:
            embeddings = await self.embed_texts([text])
            if embeddings and embeddings[0]:
                vec = embeddings[0]
                if any(v != 0.0 for v in vec):
                    return vec
        except Exception as e:
            logger.warning("Query embedding failed: %s", e)
        return None
