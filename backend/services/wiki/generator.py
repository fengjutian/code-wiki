"""
WikiGenerator — coordinates PromptBuilder, LLMService, MarkdownBuilder,
WikiWriter, and WikiState to produce documentation.

v2: Cross-module context injection + project-level architecture synthesis.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

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
      PromptBuilder   — prompt construction (role-aware + cross-module)
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

        # Sub-components
        self._writer = WikiWriter(self.wiki_path)
        self._state = WikiState(self.wiki_path)
        self._prompt_builder = PromptBuilder()
        self._markdown = MarkdownBuilder(self._writer.source_to_wiki_path)

        # LLM provider (only when API key is real)
        self._llm_service: Optional[LLMService] = None
        if api_key and api_key != "sk-placeholder":
            self._llm_service = self._create_llm_service()

        # Cross-module context cache — populated by generate_all before workers start
        self._dep_graph: Optional[object] = None
        self._all_modules: Dict[str, ModuleInfo] = {}
        self._core_ranking: List[Tuple[str, int]] = []

    def _create_llm_service(self) -> LLMService:
        provider = DeepSeekProvider(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            requests_per_minute=self.requests_per_minute,
        )
        return LLMService(provider)

    # ── Public API ───────────────────────────────────────────────────────

    async def generate_all(
        self,
        modules: Dict[str, ModuleInfo],
        dep_graph_stats: dict,
        dep_graph: object = None,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[WikiPage]:
        """Generate Wiki pages for all modules + index + synthesis."""
        pages: List[WikiPage] = []
        total = len(modules)
        logger.info(
            "generate_all: %d modules, concurrency=%d", total, self.max_concurrency
        )

        # Cache for cross-module context
        self._all_modules = modules
        self._dep_graph = dep_graph
        if dep_graph:
            self._core_ranking = dep_graph.get_core_modules(20)  # type: ignore[union-attr]

        # 1. Index page (stats overview)
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

        # 2. Worker pool
        queue: asyncio.Queue = asyncio.Queue()
        for path, mod in modules.items():
            await queue.put((path, mod))

        done_count = 0
        done_lock = asyncio.Lock()
        results: List[Optional[WikiPage]] = []

        async def worker(worker_id: int) -> None:
            nonlocal done_count
            while True:
                if cancel_check and cancel_check():
                    return
                try:
                    path, module = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
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
                    logger.exception(
                        "Unexpected error in worker %d for %s", worker_id, path
                    )
                    results.append(None)
                finally:
                    queue.task_done()
                async with done_lock:
                    done_count += 1
                    if on_progress:
                        on_progress(done_count, total)

        worker_count = min(self.max_concurrency, total)
        workers = [
            asyncio.create_task(worker(i)) for i in range(worker_count)
        ]

        await queue.join()
        for w in workers:
            if not w.done():
                w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        for r in results:
            if r is not None:
                pages.append(r)

        # 3. Project-level architecture synthesis
        if self._llm_service is not None and not (
            cancel_check and cancel_check()
        ):
            try:
                synthesis_page = await self._generate_synthesis(
                    modules, dep_graph_stats, cancel_check
                )
                if synthesis_page:
                    pages.append(synthesis_page)
            except Exception:
                logger.exception("Synthesis generation failed, continuing without it")

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

        async def generate_one(
            path: str, module: ModuleInfo
        ) -> Optional[WikiPage]:
            async with sem:
                return await self._generate_page(path, module, cancel_check)

        tasks = [generate_one(path, mod) for path, mod in modules.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, WikiPage):
                pages.append(r)
        return pages

    def clean_wiki_dir(self) -> None:
        self._writer.clean_dir()
        logger.info("Wiki directory cleaned: %s", self.wiki_path)

    def write_all(self, pages: List[WikiPage]) -> None:
        self._state.save(pages, mode="full")

    def write_partial(self, pages: List[WikiPage]) -> None:
        self._writer.write_pages(pages)
        self._state.save(pages, mode="partial")

    async def close(self) -> None:
        if self._llm_service is not None:
            await self._llm_service.aclose()
            logger.info("WikiGenerator resources released")

    # ── Private: page generation ─────────────────────────────────────────

    async def _generate_page(
        self,
        path: str,
        module: ModuleInfo,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Optional[WikiPage]:
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
        if module.total_entities == 0 and not module.docstring:
            return self._markdown.build_empty(module)

        if self._llm_service is None:
            return self._markdown.build_fallback(
                module, "未配置 API Key，请在设置中填写"
            )

        # Build cross-module context
        deps_context = self._build_deps_context(module.path)

        # Build prompt
        prompt = self._prompt_builder.build(module, deps_context=deps_context)

        if cancel_check and cancel_check():
            raise asyncio.CancelledError("Cancelled before LLM call")

        language_label = module.language.value.capitalize()
        content = await self._llm_service.generate(
            module_path=module.path,
            language_label=language_label,
            prompt=prompt,
            temperature=self.temperature,
        )

        content += (
            f"\n\n***\n"
            f"*由 Code Wiki 自动生成 · {self.model} · "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        )
        return content

    # ── Project-level architecture synthesis ─────────────────────────────

    async def _generate_synthesis(
        self,
        modules: Dict[str, ModuleInfo],
        dep_stats: dict,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Optional[WikiPage]:
        """Generate a project-level architecture synthesis document via LLM."""
        logger.info("Generating architecture synthesis document...")
        if cancel_check and cancel_check():
            return None

        if not self._llm_service:
            # Without LLM, write a basic stats-based architecture page
            md = self._markdown.build_architecture_overview(modules, dep_stats)
        else:
            prompt = self._prompt_builder.build_synthesis(
                modules, dep_stats, self._core_ranking
            )
            try:
                content = await self._llm_service.generate(
                    module_path="__architecture_synthesis__",
                    language_label="Architecture",
                    prompt=prompt,
                    temperature=0.4,  # Slightly more creative for synthesis
                )
                content += (
                    f"\n\n***\n"
                    f"*由 Code Wiki 自动生成 · {self.model} · "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*"
                )
                md = content
            except Exception as exc:
                logger.warning("LLM synthesis failed: %s, using fallback", exc)
                md = self._markdown.build_architecture_overview(modules, dep_stats)

        page = WikiPage(
            path="architecture.md",
            source_path="",
            markdown=md,
            anchors_count=md.count("[@src:"),
            generated_at=datetime.now(),
            model=self.model if self._llm_service else "fallback",
        )
        self._writer.write_page(page)
        self._state.record_success("architecture.md")
        logger.info("Architecture synthesis done (%d chars)", len(md))
        return page

    # ── Cross-module context builder ─────────────────────────────────────

    def _build_deps_context(self, module_path: str) -> Optional[Dict[str, object]]:
        """Build a deps context dict for a single module.

        Uses the cached DependencyGraph and module summaries.
        Returns None when no graph is available.
        """
        if not self._dep_graph or not self._all_modules:
            return None

        dep_graph = self._dep_graph  # type: ignore[union-attr]

        # Dependencies (what this module imports)
        dep_paths = dep_graph.dependencies_of(module_path)  # type: ignore[union-attr]
        deps = []
        for dp in dep_paths[:8]:  # at most 8 to keep context tight
            m = self._all_modules.get(dp)
            if m:
                deps.append({
                    "path": dp,
                    "summary": m.docstring or (
                        f"{m.total_entities} entities, "
                        f"{m.total_lines} lines"
                    ),
                })

        # Dependents (what imports this module)
        dent_paths = dep_graph.dependents_of(module_path)  # type: ignore[union-attr]
        dents = []
        for dp in dent_paths[:8]:
            m = self._all_modules.get(dp)
            if m:
                dents.append({
                    "path": dp,
                    "summary": m.docstring or (
                        f"{m.total_entities} entities, "
                        f"{m.total_lines} lines"
                    ),
                })

        # Graph rank
        rank_tuple = None
        for rank_idx, (path, score) in enumerate(self._core_ranking):
            if path == module_path:
                rank_tuple = (rank_idx + 1, len(self._core_ranking))
                break

        if not deps and not dents and rank_tuple is None:
            return None

        return {
            "dependencies": deps,
            "dependents": dents,
            "graph_rank": rank_tuple,
        }
