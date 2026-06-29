"""
Wiki Generator — uses DeepSeek API to produce Markdown documentation from AST analysis.

Pipeline:
  ModuleInfo (AST structured data) → Prompt → DeepSeek API → Markdown + source anchors
  Write to .code-wiki/ directory.

Supports:
- Full generation: all modules → index.md + per-module .md files
- Partial generation: specified modules only
- Incremental: replace only changed .md files
"""

import os
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from httpx import AsyncClient, HTTPError, Timeout

from models.entities import ModuleInfo, WikiPage


class WikiGenerator:
    """Generates Markdown Wiki pages using DeepSeek API."""

    def __init__(
        self,
        repo_path: str,
        wiki_path: str = "",
        api_key: str = "",
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        temperature: float = 0.3,
    ):
        self.repo_path = repo_path
        self.wiki_path = wiki_path or str(Path(repo_path) / ".code-wiki")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self._client: Optional[AsyncClient] = None

    @property
    def client(self) -> AsyncClient:
        if self._client is None:
            token = self.api_key or "sk-placeholder"
            self._client = AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=Timeout(60.0),
            )
        return self._client

    # ---- Public API ----

    async def generate_all(
        self,
        modules: Dict[str, ModuleInfo],
        dep_graph_stats: dict,
        cancel_check=None,
        on_progress=None,
    ) -> List[WikiPage]:
        """Generate Wiki pages for all modules + index."""
        pages: List[WikiPage] = []

        # 1. Index page (architecture overview)
        if cancel_check and cancel_check():
            return pages
        index_md = self._build_index_markdown(modules, dep_graph_stats)
        index_page = WikiPage(
            path="index.md",
            source_path="",
            markdown=index_md,
            anchors_count=0,
            generated_at=datetime.now(),
            model=self.model,
        )
        pages.append(index_page)
        self._write_one_page(index_page)  # write immediately

        # 2. Per-module pages (concurrent with rate limiting, respect cancel)
        sem = asyncio.Semaphore(5)  # Max 5 concurrent LLM calls
        done_count = 0
        total = len(modules)
        _done_lock = asyncio.Lock()

        async def generate_one(path: str, module: ModuleInfo):
            nonlocal done_count
            if cancel_check and cancel_check():
                return None
            async with sem:
                # Check cancel again after acquiring semaphore
                if cancel_check and cancel_check():
                    return None
                try:
                    md = await self._generate_single(module)
                    page = WikiPage(
                        path=self._source_to_wiki_path(path),
                        source_path=path,
                        markdown=md,
                        anchors_count=md.count("[@src:"),
                        generated_at=datetime.now(),
                        model=self.model,
                    )
                except Exception as e:
                    # Fallback: generate from template without LLM
                    fallback = self._build_fallback_markdown(module, str(e))
                    page = WikiPage(
                        path=self._source_to_wiki_path(path),
                        source_path=path,
                        markdown=fallback,
                        anchors_count=fallback.count("[@src:"),
                        generated_at=datetime.now(),
                        model="fallback",
                    )
                # Write this page to disk immediately
                if page:
                    self._write_one_page(page)
                # Progress tracking
                async with _done_lock:
                    done_count += 1
                    if on_progress:
                        on_progress(done_count, total)
                return page

        # Process in batches to avoid creating N asyncio tasks for N modules
        BATCH_SIZE = 50
        results = []
        batch = []
        for path, mod in modules.items():
            batch.append(generate_one(path, mod))
            if len(batch) >= BATCH_SIZE:
                results.extend(await asyncio.gather(*batch))
                batch = []
        if batch:
            results.extend(await asyncio.gather(*batch))

        for r in results:
            if r is not None:
                pages.append(r)

        return pages

    async def generate_partial(
        self, modules: Dict[str, ModuleInfo]
    ) -> List[WikiPage]:
        """Generate Wiki pages for specific modules only."""
        pages: List[WikiPage] = []
        sem = asyncio.Semaphore(5)

        async def generate_one(path: str, module: ModuleInfo):
            async with sem:
                try:
                    md = await self._generate_single(module)
                    return WikiPage(
                        path=self._source_to_wiki_path(path),
                        source_path=path,
                        markdown=md,
                        anchors_count=md.count("[@src:"),
                        generated_at=datetime.now(),
                        model=self.model,
                    )
                except Exception as e:
                    fallback = self._build_fallback_markdown(module, str(e))
                    return WikiPage(
                        path=self._source_to_wiki_path(path),
                        source_path=path,
                        markdown=fallback,
                        anchors_count=fallback.count("[@src:"),
                        generated_at=datetime.now(),
                        model="fallback",
                    )

        tasks = [generate_one(path, mod) for path, mod in modules.items()]
        results = await asyncio.gather(*tasks)
        pages.extend(results)
        return pages

    @staticmethod
    def _source_to_wiki_path(source_path: str) -> str:
        """Convert a source file path to a wiki .md path.
        e.g. services/user.py → services/user.md
             components/Button.tsx → components/Button.md
        """
        for ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
            if source_path.endswith(ext):
                return source_path[: -len(ext)] + ".md"
        return source_path + ".md"

    # ---- File I/O ----

    def clean_wiki_dir(self):
        """Remove all old .md files before a new full scan (preserves index.md for
        directory structure, it will be overwritten)."""
        wiki_dir = Path(self.wiki_path)
        self._clean_md_files(wiki_dir)

    def write_all(self, pages: List[WikiPage]):
        """Write state.json after full generation (pages already written progressively)."""
        wiki_dir = Path(self.wiki_path)
        # Pages are already written by generate_all via _write_one_page;
        # just update state.json here.
        self._update_state(pages, mode="full")

    def write_partial(self, pages: List[WikiPage]):
        """Partial update: overwrite only specified .md files."""
        wiki_dir = Path(self.wiki_path)
        self._write_pages(wiki_dir, pages)
        self._update_state(pages, mode="partial")

    # ---- Prompt Engineering ----

    def _build_prompt(self, module: ModuleInfo) -> str:
        """Construct the LLM prompt from structured AST data."""
        language_label = module.language.value.capitalize()

        # Summarize classes
        classes_text = ""
        for cls in module.classes:
            classes_text += f"\n### 类: {cls.name}"
            if cls.bases:
                classes_text += f" (继承: {', '.join(cls.bases)})"
            anchor_line = cls.anchor.line if cls.anchor else "?"
            classes_text += f" [@src:{module.path}:{anchor_line}]\n"
            if cls.docstring:
                classes_text += f"  描述: {cls.docstring[:200]}\n"
            if cls.methods:
                classes_text += "  方法:\n"
                for m in cls.methods:
                    sig = m.signature
                    classes_text += f"    - {sig}"
                    if m.anchor:
                        classes_text += f" [@src:{module.path}:{m.anchor.line}]"
                    classes_text += "\n"
                    if m.docstring:
                        classes_text += f"      描述: {m.docstring[:150]}\n"

        # Summarize functions
        funcs_text = ""
        for fn in module.functions:
            anchor_line = fn.anchor.line if fn.anchor else "?"
            funcs_text += f"\n### 函数: {fn.signature} [@src:{module.path}:{anchor_line}]\n"
            if fn.docstring:
                funcs_text += f"  描述: {fn.docstring[:200]}\n"

        # Summarize interfaces (TS)
        ifaces_text = ""
        for iface in module.interfaces:
            anchor_line = iface.anchor.line if iface.anchor else "?"
            ifaces_text += f"\n### 接口: {iface.name} [@src:{module.path}:{anchor_line}]\n"
            if iface.docstring:
                ifaces_text += f"  描述: {iface.docstring[:200]}\n"
            if iface.members:
                ifaces_text += "  成员:\n"
                for m in iface.members[:15]:
                    ifaces_text += f"    - {m['name']}: {m.get('type', 'any')}\n"

        # Summarize React components
        comp_text = ""
        for comp in module.components:
            anchor_line = comp.anchor.line if comp.anchor else "?"
            comp_text += f"\n### 组件: {comp.name} [@src:{module.path}:{anchor_line}]\n"
            if comp.props_type:
                comp_text += f"  属性类型: {comp.props_type}\n"
            if comp.hooks:
                comp_text += f"  使用的 Hook: {', '.join(comp.hooks)}\n"

        # Dependencies
        deps_text = (
            ", ".join(module.imports[:15])
            if module.imports
            else "无内部依赖"
        )

        prompt = f"""你是 {language_label} 代码文档专家。根据以下模块的结构化摘要，生成一份简洁的 Markdown Wiki 文档。

**规则**：
1. 用中文撰写
2. 每个实体（模块、类、方法、接口、组件）使用 [@src:{module.path}:行号] 标注源码位置（我已提供，直接保留）
3. 包含: 模块概述、类描述（含方法表格）、模块级函数、接口/类型定义、组件、依赖关系
4. 输出纯 Markdown，不添加额外解释
5. 对私有成员（以 _ 开头）只列出名称无需详细描述

**模块**: `{module.path}` ({module.total_lines} 行, {language_label})
**概述**: {module.docstring or '无'}

**类** ({len(module.classes)} 个):
{classes_text if classes_text else '无'}

**函数** ({len(module.functions)} 个):
{funcs_text if funcs_text else '无'}

**接口/类型** ({len(module.interfaces)} 个):
{ifaces_text if ifaces_text else '无'}

**React 组件** ({len(module.components)} 个):
{comp_text if comp_text else '无'}

**内部依赖**: {deps_text}
**外部依赖**: {', '.join(module.external_imports[:10]) if module.external_imports else '无'}

输出:"""
        return prompt

    async def _generate_single(self, module: ModuleInfo) -> str:
        """Call DeepSeek API for a single module."""
        prompt = self._build_prompt(module)

        # Skip LLM for empty modules
        if module.total_entities == 0 and not module.docstring:
            return self._build_empty_markdown(module)

        # Skip LLM when no API key is configured
        if not self.api_key:
            return self._build_fallback_markdown(module, "未配置 API Key，请在设置中填写")

        response = await self.client.post(
            "/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": f"你是 {module.language.value.capitalize()} 代码文档专家。只输出 Markdown，不要额外解释。",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
                "max_tokens": 4096,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        # Add metadata footer
        content += f"\n\n***\n*由 Code Wiki 自动生成 · {self.model} · {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        return content

    # ---- Fallback (no LLM) ----

    def _build_fallback_markdown(self, module: ModuleInfo, error: str) -> str:
        """Generate basic Markdown without LLM (when API fails)."""
        language_label = module.language.value.capitalize()
        lines = [
            f"# {module.path}",
            "",
            f"> [WARNING] LLM 生成失败: {error}",
            f"> 以下为基础结构摘要。",
            "",
        ]

        if module.docstring:
            lines += [f"## 模块概述", "", module.docstring, ""]

        # Classes
        if module.classes:
            lines += ["## 类", ""]
            for cls in module.classes:
                lines.append(f"### {cls.name}")
                if cls.anchor:
                    lines.append(f"[@src:{module.path}:{cls.anchor.line}]")
                lines.append("")
                if cls.docstring:
                    lines.append(f"{cls.docstring}\n")
                if cls.methods:
                    lines.append("| 方法 | 签名 |")
                    lines.append("|------|------|")
                    for m in cls.methods:
                        sig = m.signature.replace("|", "\\|")
                        anchor = (
                            f"[@src:{module.path}:{m.anchor.line}]"
                            if m.anchor
                            else ""
                        )
                        lines.append(f"| {m.name} | {sig} {anchor} |")
                    lines.append("")

        # Functions
        if module.functions:
            lines += ["## 函数", ""]
            for fn in module.functions:
                lines.append(f"### {fn.signature}")
                if fn.anchor:
                    lines.append(f"[@src:{module.path}:{fn.anchor.line}]")
                lines.append("")
                if fn.docstring:
                    lines.append(f"{fn.docstring}\n")

        # Interfaces (TS)
        if module.interfaces:
            lines += ["## 接口/类型", ""]
            for iface in module.interfaces:
                lines.append(f"### {iface.name}")
                if iface.anchor:
                    lines.append(f"[@src:{module.path}:{iface.anchor.line}]")
                lines.append("")
                if iface.docstring:
                    lines.append(f"{iface.docstring}\n")
                if iface.members:
                    lines.append("| 成员 | 类型 |")
                    lines.append("|------|------|")
                    for m in iface.members:
                        lines.append(f"| {m['name']} | {m.get('type', 'any')} |")
                    lines.append("")

        # React Components
        if module.components:
            lines += ["## React 组件", ""]
            for comp in module.components:
                lines.append(f"### {comp.name}")
                if comp.anchor:
                    lines.append(f"[@src:{module.path}:{comp.anchor.line}]")
                lines.append("")
                if comp.props_type:
                    lines.append(f"- 属性类型: `{comp.props_type}`")
                if comp.hooks:
                    lines.append(f"- 使用的 Hook: {', '.join(comp.hooks)}")
                lines.append("")

        # Imports
        if module.imports:
            lines += [
                "## 内部依赖",
                "",
                ", ".join(f"`{i}`" for i in module.imports),
                "",
            ]

        lines += [
            "***",
            f"*由 Code Wiki 自动生成（fallback 模板）· {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        ]
        return "\n".join(lines)

    def _build_empty_markdown(self, module: ModuleInfo) -> str:
        """Minimal Markdown for empty modules."""
        language_label = module.language.value.capitalize()
        return (
            f"# {module.path}\n\n"
            f"*空模块（{language_label}），无类、函数或组件定义*\n\n"
            f"***\n"
            f"*由 Code Wiki 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        )

    def _build_index_markdown(
        self, modules: Dict[str, ModuleInfo], dep_graph_stats: dict
    ) -> str:
        """Generate the architecture overview index.md."""
        total_classes = sum(len(m.classes) for m in modules.values())
        total_funcs = sum(len(m.functions) for m in modules.values())
        total_interfaces = sum(len(m.interfaces) for m in modules.values())
        total_components = sum(len(m.components) for m in modules.values())

        # Count by language
        lang_counts = {}
        for m in modules.values():
            lang_counts[m.language.value] = lang_counts.get(m.language.value, 0) + 1

        lang_summary = ", ".join(
            f"{k.capitalize()}: {v}" for k, v in sorted(lang_counts.items())
        )

        lines = [
            "# 项目架构概览",
            "",
            f"> 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 统计",
            "",
            f"| 指标 | 数量 |",
            f"|------|------|",
            f"| 模块 | {len(modules)} ({lang_summary}) |",
            f"| 类 | {total_classes} |",
            f"| 函数 | {total_funcs} |",
            f"| 接口/类型 | {total_interfaces} |",
            f"| React 组件 | {total_components} |",
            f"| 依赖边 | {dep_graph_stats.get('total_edges', 0)} |",
            "",
            "## 模块列表",
            "",
        ]

        # Group by directory
        groups: Dict[str, List[str]] = {}
        for path in sorted(modules.keys()):
            parts = path.replace("\\", "/").split("/")
            group = parts[0] if len(parts) > 1 else "root"
            groups.setdefault(group, []).append(path)

        for group, paths in sorted(groups.items()):
            lines.append(f"### {group}/")
            for path in paths:
                mod = modules[path]
                wiki_path = self._source_to_wiki_path(path)
                entities = f"{len(mod.classes)}C/{len(mod.functions)}F"
                if mod.interfaces:
                    entities += f"/{len(mod.interfaces)}I"
                if mod.components:
                    entities += f"/{len(mod.components)}Comp"
                lang_badge = f"[{mod.language.value}]"
                lines.append(
                    f"- {lang_badge} [{path}]({wiki_path}) "
                    f"({mod.total_lines} 行, {entities})"
                )
            lines.append("")

        # Core modules
        lines += [
            "## 依赖关系",
            "",
            "参见 [架构图](diagrams/architecture.mmd) 和 [依赖图](diagrams/dependencies.mmd)。",
            "",
            "***",
            f"*由 Code Wiki 自动生成*",
        ]

        return "\n".join(lines)

    # ---- Private helpers ----

    def _clean_md_files(self, wiki_dir: Path):
        """Remove all .md files except index.md patterns."""
        if not wiki_dir.exists():
            return
        for md_file in wiki_dir.glob("**/*.md"):
            if md_file.name == "index.md":
                continue
            md_file.unlink()

    def _write_pages(self, wiki_dir: Path, pages: List[WikiPage]):
        """Write WikiPage objects to disk."""
        wiki_dir.mkdir(parents=True, exist_ok=True)
        for page in pages:
            self._write_one_page(page)

    def _write_one_page(self, page: WikiPage):
        """Write a single WikiPage to disk immediately."""
        target = Path(self.wiki_path) / page.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page.markdown, encoding="utf-8")

    def _update_state(self, pages: List[WikiPage], mode: str):
        """Update state.json after generation."""
        state_path = Path(self.wiki_path) / "state.json"

        existing = {}
        if state_path.exists():
            try:
                existing = json.loads(state_path.read_text())
            except (json.JSONDecodeError, IOError):
                pass

        existing.update(
            {
                "last_wiki_generation": datetime.now().isoformat(),
                "wiki_mode": mode,
                "total_pages": len(pages),
                "total_anchors": sum(p.anchors_count for p in pages),
                "llm_model": self.model,
            }
        )

        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
