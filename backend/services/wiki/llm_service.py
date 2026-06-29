"""
LLMService — abstracted LLM API client with retry, rate limiting, and proper lifecycle.

Provides:
- LLMProvider ABC for multi-model support (DeepSeek, OpenAI, etc.)
- DeepSeekProvider with retry (exponential backoff) and rate limiting
- Proper AsyncClient lifecycle (aclose)
- Cancellation-aware (respects asyncio.CancelledError)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Optional

from httpx import AsyncClient, HTTPError, HTTPStatusError, Timeout, TimeoutException

logger = logging.getLogger("code-wiki.llm")


# ---------------------------------------------------------------------------
# Rate limiter — token bucket
# ---------------------------------------------------------------------------

class TokenBucket:
    """Asyncio-safe token bucket for RPM/TPM rate limiting."""

    def __init__(self, rate: float, burst: int = 10) -> None:
        """
        Args:
            rate: Tokens (requests) per second.
            burst: Maximum burst size.
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self.rate
                # Release lock while sleeping
                self._lock.release()
                try:
                    await asyncio.sleep(wait)
                finally:
                    await self._lock.acquire()
                # Recalculate after sleep
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
                self._last_refill = now
                self._tokens -= 1.0
            else:
                self._tokens -= 1.0


# ---------------------------------------------------------------------------
# LLM Provider ABC
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Abstract base for LLM API providers."""

    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        """Send prompt to LLM and return generated text."""
        ...

    @abstractmethod
    async def aclose(self) -> None:
        """Release underlying HTTP resources."""
        ...


# ---------------------------------------------------------------------------
# DeepSeek provider
# ---------------------------------------------------------------------------

class DeepSeekProvider(LLMProvider):
    """DeepSeek API provider with retry, rate limiting, and cancellation safety."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
        max_retries: int = 3,
        requests_per_minute: int = 100,
    ) -> None:
        if not api_key or api_key == "sk-placeholder":
            raise ValueError("A valid API key is required to create an LLM provider.")

        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries

        self._client: Optional[AsyncClient] = None
        self._timeout = Timeout(timeout)
        self._rate_limiter = TokenBucket(
            rate=requests_per_minute / 60.0,
            burst=max(1, requests_per_minute // 10),
        )

    @property
    def client(self) -> AsyncClient:
        """Lazily create and cache the AsyncClient.

        Call invalidate_client() if api_key changes.
        """
        if self._client is None:
            self._client = AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        return self._client

    def invalidate_client(self) -> None:
        """Force recreation of the HTTP client (e.g. after key rotation)."""
        self._client = None

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        """Send a chat completion request with retry and rate limiting."""
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                await self._rate_limiter.acquire()
                return await self._call_api(system_prompt, user_prompt, temperature)
            except asyncio.CancelledError:
                logger.info("LLM call cancelled, propagating CancelledError")
                raise
            except (HTTPStatusError, TimeoutException) as exc:
                last_error = exc
                status = (
                    exc.response.status_code
                    if isinstance(exc, HTTPStatusError)
                    else None
                )
                # Don't retry 4xx errors (except 429)
                if status is not None and 400 <= status < 500 and status != 429:
                    logger.error(
                        "LLM call failed with client error %s: %s", status, exc
                    )
                    raise
                if attempt < self.max_retries - 1:
                    wait = 2**attempt + random.uniform(0, 1)
                    logger.warning(
                        "LLM call attempt %d/%d failed (status=%s): %s. "
                        "Retrying in %.1fs...",
                        attempt + 1,
                        self.max_retries,
                        status,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)
            except (HTTPError, OSError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait = 2**attempt + random.uniform(0, 1)
                    logger.warning(
                        "LLM call attempt %d/%d failed (network): %s. "
                        "Retrying in %.1fs...",
                        attempt + 1,
                        self.max_retries,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)

        raise last_error  # type: ignore[misc]

    async def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> str:
        """Single API call (no retry)."""
        response = await self.client.post(
            "/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": 4096,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("AsyncClient closed for DeepSeekProvider")


# ---------------------------------------------------------------------------
# LLMService — thin coordinator
# ---------------------------------------------------------------------------

class LLMService:
    """Coordinates provider, retry, fallback, and logging for LLM calls."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def generate(
        self,
        module_path: str,
        language_label: str,
        prompt: str,
        temperature: float = 0.3,
    ) -> str:
        """Generate documentation for one module."""
        system_prompt = (
            f"你是 {language_label} 代码文档专家。只输出 Markdown，不要额外解释。"
        )
        logger.info("LLM generating: %s (%d chars prompt)", module_path, len(prompt))
        t0 = time.monotonic()
        try:
            content = await self.provider.generate(system_prompt, prompt, temperature)
            elapsed = time.monotonic() - t0
            logger.info(
                "LLM done: %s in %.1fs (%d chars output)",
                module_path,
                elapsed,
                len(content),
            )
            return content
        except asyncio.CancelledError:
            logger.info("LLM cancelled for %s", module_path)
            raise
        except Exception:
            elapsed = time.monotonic() - t0
            logger.exception("LLM failed for %s after %.1fs", module_path, elapsed)
            raise

    async def aclose(self) -> None:
        """Release provider resources."""
        await self.provider.aclose()
