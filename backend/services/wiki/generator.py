"""
WikiGenerator — coordinates PromptBuilder, LLMService, MarkdownBuilder,
WikiWriter, and WikiState to produce documentation.

This is the public API consumed by routes/scan.py. It keeps the same
constructor signature and method names as the original monolithic class
so the caller needs only an import-path change.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from models.entities import ModuleInfo, WikiPage

from .llm_service import DeepSeekProvider, LLMProvider, LLMService
from .markdown_builder import MarkdownBuilder
from .prompt_builder import PromptBuilder
from .wiki_state import WikiState
from .wiki_writer import WikiWriter

logger = logging.getLogger("code-wiki.wiki_generator")


class WikiGenerator:
    """Generates Markdown Wiki pages using LLM (DeepSeek by default).

    Delegates to:
      PromptBuilder   — prompt construction
      LLMService      — API calls with retry + rate limiting
      MarkdownBuilder — fallback / empty / index Markdown
      WikiWriter      — file I/O
      WikiState       — state.json persistence
    """

    def __init__(
        self,
        repo_path: str,
        wiki_path: str = "",
        api_key: str = "",
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        temperature: float = 0.3,
        max_concurrency: int = 5,
        requests_per_minute: int = 100,
    ):
        self.repo_path = repo_path
        self.wiki_path = wiki_path or str(Path(repo_path) / ".code-wiki")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_concurrency = max_concurrency
        self.requests_per_minute = requests_per_minute

        # Sub-components (created lazily so they can be tested independently)
        self._writer = WikiWriter(self.wiki_path)
        self._state = WikiState(self.wiki_path)
        self._prompt_builder = PromptBuilder()
        self._markdown = MarkdownBuilder(self._writer.source_to_wiki_path)

        # LLM provider — only created when an API key is present
        self._llm_service: Optional[LLMService] = None
        if api_key and api_key != "sk-placeholder":
            self._llm_service = self._create_llm_service()

    def _create_llm_service(self) -> LLMService:
        provider = DeepSeekProvider(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            requests_per_minute=self.requests_per_minute,
        )
        return LLMService(provider)

    # ---- Public API ----

    async def generate_all(
        self,
        modules: Dict[str, ModuleInfo],
        dep_graph_stats: dict,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[WikiPage]:
        """Generate Wiki pages for all modules + index.

        Uses a worker-pool pattern: fixed number of workers consume from
        a queue, instead of creating N coroutines for N modules.
        """
        pages: List[WikiPage] = []
        total = len(modules)
        logger.info("generate_all: %d modules, concurrency=%d", total, self.max_concurrency)

        # 1. Index page (architecture overview)
        if cancel_check and cancel_check():
            return pages
        index_md = self._markdown.build_index(modules, dep_graph_stats)
        index_page = WikiPage(
            path="index.md",
            source_path="",
            markdown=index_md,
            anchors_count=0,
            generated_at=datetime.now(),
            model=self.model,
        )
        pages.append(index_page)
        self._writer.write_page(index_page)
        self._state.record_success("index.md")

        # 2. Worker pool consuming from a queue
        queue: asyncio.Queue = asyncio.Queue()
        for path, mod in modules.items():
            await queue.put((path, mod))

        done_count = 0
        done_lock = asyncio.Lock()
        results: List[Optional[WikiPage]] = []

        async def worker(worker_id: int) -> None:
            nonlocal done_count
            while True:
                # Check cancel before blocking on queue
                if cancel_check and cancel_check():
                    return

                try:
                    path, module = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    # No more items
                    return

                try:
                    page = await self._generate_page(path, module, cancel_check)
                    if page:
                        self._writer.write_page(page)
                    results.append(page)
                except asyncio.CancelledError:
                    queue.task_done()
                    raise
                except Exception:
                    logger.exception("Unexpected error in worker %d for %s", worker_id, path)
                    results.append(None)
                finally:
                    queue.task_done()

                async with done_lock:
                    done_count += 1
                    if on_progress:
                        on_progress(done_count, total)

        # Start workers
        worker_count = min(self.max_concurrency, total)
        workers = [
            asyncio.create_task(worker(i))
            for i in range(worker_count)
        ]

        # Wait for all queue items to be processed
        await queue.join()

        # Cancel any workers still waiting on the empty queue
        for w in workers:
            if not w.done():
                w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        # Collect results
        for r in results:
            if r is not None:
                pages.append(r)

        logger.info(
            "generate_all done: %d pages (%d success, %d failed)",
            len(pages),
            len(self._state.success_modules),
            len(self._state.failed_modules),
        )
        return pages

    async def generate_partial(
        self,
        modules: Dict[str, ModuleInfo],
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[WikiPage]:
        """Generate Wiki pages for specific modules only."""
        pages: List[WikiPage] = []
        logger.info("generate_partial: %d modules", len(modules))

        sem = asyncio.Semaphore(self.max_concurrency)

        async def generate_one(path: str, module: ModuleInfo) -> Optional[WikiPage]:
            async with sem:
                return await self._generate_page(path, module, cancel_check)

        tasks = [generate_one(path, mod) for path, mod in modules.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, WikiPage):
                pages.append(r)
        return pages

    def clean_wiki_dir(self) -> None:
        """Remove all old .md files before a new full scan."""
        self._writer.clean_dir()
        logger.info("Wiki directory cleaned: %s", self.wiki_path)

    def write_all(self, pages: List[WikiPage]) -> None:
        """Write state.json after full generation (pages already written progressively)."""
        self._state.save(pages, mode="full")

    def write_partial(self, pages: List[WikiPage]) -> None:
        """Partial update: overwrite only specified .md files."""
        self._writer.write_pages(pages)
        self._state.save(pages, mode="partial")

    async def close(self) -> None:
        """Release LLM provider resources (HTTP client)."""
        if self._llm_service is not None:
            await self._llm_service.aclose()
            logger.info("WikiGenerator resources released")

    # ---- Private: unified page generation ----

    async def _generate_page(
        self,
        path: str,
        module: ModuleInfo,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Optional[WikiPage]:
        """Generate a single WikiPage — used by both generate_all and generate_partial.

        Returns None if cancelled.
        """
        if cancel_check and cancel_check():
            return None

        try:
            md = await self._generate_single(module, cancel_check)
            page = WikiPage(
                path=self._writer.source_to_wiki_path(path),
                source_path=path,
                markdown=md,
                anchors_count=md.count("[@src:"),
                generated_at=datetime.now(),
                model=self.model,
            )
            self._state.record_success(path)
            return page
        except asyncio.CancelledError:
            logger.info("Cancelled during generation of %s", path)
            raise
        except Exception as exc:
            logger.warning("LLM generation failed for %s: %s", path, exc)
            fallback = self._markdown.build_fallback(module, str(exc))
            page = WikiPage(
                path=self._writer.source_to_wiki_path(path),
                source_path=path,
                markdown=fallback,
                anchors_count=fallback.count("[@src:"),
                generated_at=datetime.now(),
                model="fallback",
            )
            self._state.record_failure(path)
            return page

    async def _generate_single(
        self,
        module: ModuleInfo,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """Generate Markdown for one module — LLM or fallback."""
        # Empty modules don't need LLM
        if module.total_entities == 0 and not module.docstring:
            return self._markdown.build_empty(module)

        # No LLM service means no API key configured
        if self._llm_service is None:
            return self._markdown.build_fallback(
                module, "未配置 API Key，请在设置中填写"
            )

        # Build prompt
        prompt = self._prompt_builder.build(module)

        # Periodic cancel check before the (potentially long) LLM call
        if cancel_check and cancel_check():
            raise asyncio.CancelledError("Cancelled before LLM call")

        # Call LLM (supports cancellation via asyncio task cancel)
        language_label = module.language.value.capitalize()
        content = await self._llm_service.generate(
            module_path=module.path,
            language_label=language_label,
            prompt=prompt,
            temperature=self.temperature,
        )

        # Add metadata footer
        content += (
            f"\n\n***\n"
            f"*由 Code Wiki 自动生成 · {self.model} · "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        )
        return content
