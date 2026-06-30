"""
Embedding API client — talks to the configured embedding provider.

Currently targets the DeepSeek /v1/embeddings endpoint, but the interface
is narrow enough to swap in OpenAI / Jina / Voyage providers later.

v2 — Batch splitting + retry + rate limiting for 10,000-file scale.
"""

import asyncio
import logging
from typing import List, Optional

from httpx import AsyncClient, Timeout, HTTPStatusError, RequestError

logger = logging.getLogger("code-wiki.embedder")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
ZERO_VECTOR_DIM = 128            # Dimension of a zero fallback vector
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-embed"
REQUEST_TIMEOUT = 30.0           # seconds

# Batch / retry settings
EMBED_BATCH_SIZE = 100           # Max texts per API call
EMBED_MAX_RETRIES = 3            # Retries before giving up
EMBED_RETRY_BASE_DELAY = 1.0     # Base delay for exponential backoff (seconds)
EMBED_RATE_LIMIT_DELAY = 0.2     # Delay between batches to avoid rate limits (seconds)


class EmbeddingClient:
    """Async client for the embedding API with batching + retry.

    Splits large text lists into batches of *EMBED_BATCH_SIZE*, retries
    failed batches with exponential backoff, and inserts rate-limit delays
    between batches.

    Construction::

        client = EmbeddingClient(api_key="sk-…", base_url="https://…")
        vecs = await client.embed_texts(["hello", "world"])
        await client.close()
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        batch_size: int = EMBED_BATCH_SIZE,
        max_retries: int = EMBED_MAX_RETRIES,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size
        self.max_retries = max_retries
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for a batch of texts.

        Splits into sub-batches, retries on failure, rate-limits between
        batches.  Returns zero vectors for texts in failed batches.
        """
        if not texts:
            return []

        # If the list is small enough, do a single call
        if len(texts) <= self.batch_size:
            return await self._embed_batch_with_retry(texts)

        # Split into batches
        all_embeddings: List[List[float]] = []
        total_batches = (len(texts) + self.batch_size - 1) // self.batch_size

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1

            if batch_num > 1:
                # Rate-limit delay between batches
                await asyncio.sleep(EMBED_RATE_LIMIT_DELAY)

            result = await self._embed_batch_with_retry(batch)
            all_embeddings.extend(result)

            if len(texts) > self.batch_size and batch_num % 10 == 0:
                logger.info(
                    "Embedding progress: batch %d/%d (%d texts)",
                    batch_num, total_batches, len(all_embeddings),
                )

        return all_embeddings

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

    # ------------------------------------------------------------------
    # Internal: single-batch with retry
    # ------------------------------------------------------------------

    async def _embed_batch_with_retry(self, texts: List[str]) -> List[List[float]]:
        """Embed a single batch with exponential-backoff retry."""
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                return await self._embed_batch(texts)
            except HTTPStatusError as e:
                status = e.response.status_code if e.response else 0
                if status == 429:  # Rate limited — back off more
                    delay = EMBED_RETRY_BASE_DELAY * (4 ** attempt)
                    logger.warning(
                        "Embedding rate-limited (429), retry %d/%d after %.1fs",
                        attempt + 1, self.max_retries, delay,
                    )
                elif status >= 500:  # Server error — retry
                    delay = EMBED_RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Embedding server error (%d), retry %d/%d after %.1fs",
                        status, attempt + 1, self.max_retries, delay,
                    )
                else:
                    # Client error — don't retry
                    logger.warning("Embedding client error (%d): %s", status, e)
                    break
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
            except (RequestError, asyncio.TimeoutError) as e:
                delay = EMBED_RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Embedding network error: %s, retry %d/%d after %.1fs",
                    e, attempt + 1, self.max_retries, delay,
                )
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)

        logger.warning(
            "Embedding failed after %d retries: %s — returning zero vectors",
            self.max_retries, last_error,
        )
        return [[0.0] * ZERO_VECTOR_DIM for _ in texts]

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Send a single POST /v1/embeddings request."""
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
