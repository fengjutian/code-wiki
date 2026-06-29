"""
RAG Chat Service — retrieves relevant Wiki chunks + source code and streams LLM answers.

Pipeline:
  user question → keyword search Embedder → Top-K Wiki chunks
  → read source files → construct prompt → DeepSeek Chat API (SSE stream)
  → yield chunks
"""

import asyncio
import logging
from pathlib import Path
from typing import List, AsyncGenerator, Optional

from httpx import AsyncClient, Timeout

from services.embedder import Embedder

# ---------------------------------------------------------------------------
# Token budget (approximate: 1 char ≈ 0.25 token for CJK, ≈ 0.3 for English)
# ---------------------------------------------------------------------------
MAX_CONTEXT_CHARS = 16_000   # ~4000-5000 tokens
MAX_WIKI_CHUNK_CHARS = 1000
MAX_SOURCE_CHARS = 1500
MAX_SOURCE_FILES = 3
DEFAULT_TOP_K = 5


class PromptBuilder:
    """Assemble chat messages with a token budget — prevents context explosion."""

    def __init__(self, budget_chars: int = MAX_CONTEXT_CHARS):
        self._budget = budget_chars
        self._used = 0
        self._system = ""
        self._context_parts: list[str] = []
        self._history: list[dict] = []
        self._question = ""

    # -- fluent API --

    def add_system(self, text: str) -> "PromptBuilder":
        self._system = text
        self._used += len(text)
        return self

    def add_file_context(self, files: list[dict]) -> "PromptBuilder":
        """Add user-attached local file contents as context."""
        if not files:
            return self
        remaining = self._budget - self._used
        if remaining <= 0:
            return self

        # Build a prominent file manifest first
        file_names = [f.get("name", "?") for f in files]
        manifest = "**用户附加了以下本地文件，请基于这些文件内容回答问题：**\n" + \
                   "\n".join(f"- `{n}`" for n in file_names) + \
                   "\n\n---\n\n**文件内容详情**：\n\n"
        parts: list[str] = [manifest]
        remaining -= len(manifest)

        for f in files:
            name = f.get("name", "unknown")
            content = f.get("content", "")
            # Truncate each file to fit budget
            header = f"### 📄 {name}\n"
            max_content = min(len(content), remaining - len(header) - 50)
            if max_content <= 0:
                header_only = f"### 📄 {name}\n(内容过长，已省略)\n"
                self._used += len(header_only)
                parts.append(header_only)
                remaining = self._budget - self._used
                continue
            part = header + content[:max_content]
            if len(content) > max_content:
                part += "\n... (truncated)"
            self._used += len(part)
            parts.append(part)
            remaining = self._budget - self._used
            if remaining <= 200:
                break
        self._context_parts = parts + (self._context_parts if isinstance(self._context_parts, list) else [])
        return self

    def add_context(self, wiki_chunks: list[dict], source_codes: list[str]) -> "PromptBuilder":
        remaining = self._budget - self._used
        if remaining <= 0:
            return self

        # Preserve any previously added context (e.g. file attachments)
        parts: list[str] = list(self._context_parts) if isinstance(self._context_parts, list) else []
        for i, r in enumerate(wiki_chunks, 1):
            src = r.get("source", "unknown")
            title = r.get("title", "")
            text = r.get("text", "")[:MAX_WIKI_CHUNK_CHARS]
            part = f"[{i}] {src} — {title}\n{text}"
            if self._used + len(part) > self._budget * 0.7:
                part = part[: self._budget * 7 // 10 - self._used]
                if part:
                    parts.append(part)
                break
            self._used += len(part)
            parts.append(part)

        if source_codes and self._used < self._budget * 0.85:
            src_header = "\n\n**相关源代码**：\n\n"
            self._used += len(src_header)
            parts.append(src_header)
            for sc in source_codes[:MAX_SOURCE_FILES]:
                if self._used + len(sc) > self._budget:
                    sc = sc[: self._budget - self._used - 20] + "\n... (truncated)"
                if not sc.strip():
                    continue
                self._used += len(sc)
                parts.append(sc)

        self._context_parts = parts
        return self

    def add_history(self, history: list[dict], max_turns: int = 6) -> "PromptBuilder":
        # Keep only recent turns; estimate ~200 chars/turn budget for history
        hist_budget = self._budget // 10
        kept: list[dict] = []
        used = 0
        for turn in reversed(history[-max_turns:]):
            content = turn.get("content", "")
            if used + len(content) > hist_budget:
                break
            used += len(content)
            kept.insert(0, turn)
        self._history = kept
        return self

    def add_question(self, question: str) -> "PromptBuilder":
        self._question = f"直接回答下面的问题，不要重复问题原文：{question}"
        return self

    def build(self) -> list[dict]:
        parts = [self._system]
        if self._context_parts:
            parts.append("\n\n---\n\n".join(self._context_parts))
        ctx = "\n\n".join(parts)
        messages: list[dict] = [{"role": "system", "content": ctx}]
        messages.extend(self._history)
        messages.append({"role": "user", "content": self._question})
        return messages


class ChatService:
    """RAG-based chat using Wiki embeddings and DeepSeek API."""

    def __init__(
        self,
        repo_path: str,
        api_key: str,
        wiki_path: str = "",
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        temperature: float = 0.3,
    ):
        self.repo_path = repo_path
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.embedder = Embedder(
            repo_path=repo_path,
            wiki_path=wiki_path,
            api_key=api_key,
            base_url=base_url,
        )
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
                timeout=Timeout(60.0),
            )
        return self._client

    # ---- Source reading ----

    @staticmethod
    def _read_source(repo_path: str, source_path: str, max_bytes: int = 2000) -> str:
        """Read a source file from the repo, truncated to *max_bytes* UTF-8 bytes."""
        full = Path(repo_path) / source_path
        try:
            if not full.is_file():
                return ""
            data = full.read_bytes()
            if len(data) <= max_bytes:
                return data.decode("utf-8", errors="replace")
            # Truncate without splitting a multi-byte character
            truncated = data[:max_bytes]
            while truncated:
                try:
                    return truncated.decode("utf-8") + "\n... (truncated)"
                except UnicodeDecodeError:
                    truncated = truncated[:-1]
            return ""
        except (OSError, ValueError):
            return ""

    # ---- Public API ----

    async def chat_stream(
        self,
        question: str,
        history: List[dict],
        file_context: List[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        RAG query → SSE stream.
        Yields plain text chunks; frontend wraps in `data: ...\n\n`.
        """
        # Step 1: Retrieve relevant code chunks (hybrid search + optional reranker)
        try:
            query_vec = await self.embedder.embed_query(question)
            retrieved = self.embedder.query_with_rerank(
                question, top_k=DEFAULT_TOP_K, query_embedding=query_vec, use_reranker=True,
            )
        except Exception as e:
            logging.warning(f"Embedder query failed: {e}")
            retrieved = []

        # Step 2: Read source code for unique paths (limit before reading)
        loop = asyncio.get_running_loop()
        source_codes: list[str] = []
        seen_sources: set[str] = set()
        for r in retrieved:
            src = r.get("source", "")
            if not src or src in seen_sources:
                continue
            seen_sources.add(src)
            if len(source_codes) >= MAX_SOURCE_FILES:
                break
            code = await loop.run_in_executor(None, self._read_source, self.repo_path, src)
            if code:
                source_codes.append(f"### 源代码: {src}\n```\n{code}\n```")

        # Step 3: Build messages with token budget via PromptBuilder
        has_files = file_context and len(file_context) > 0
        if retrieved or has_files:
            if retrieved and has_files:
                system_prompt = (
                    "你是 Code Wiki 智能助手，帮助用户理解项目代码。\n"
                    "上方有：1) 从代码库中提取的相关代码片段；2) 用户附加的本地文件（含完整内容清单）。"
                    "优先参考这些材料回答，结合编程常识补充。\n"
                    "当用户询问有哪些文件时，直接从文件清单中列出。\n"
                    "要求：涉及项目结构、技术栈、接口、配置等结构化信息时优先使用 Markdown 表格呈现；"
                    "引用代码用 [src:path:line] 格式；引用文件用 `文件名`；中文简洁回答；不重复问题；末尾列出参考来源。"
                )
            elif retrieved:
                system_prompt = (
                    "你是 Code Wiki 智能助手，帮助用户理解项目代码。\n"
                    "上方有从代码库中按函数/类/方法提取的相关代码片段。优先参考代码实现逻辑，"
                    "结合编程常识回答。信息不完整时可补充说明，但要标明来源。\n"
                    "要求：涉及项目结构、接口列表、依赖关系等结构化信息时优先使用 Markdown 表格呈现；"
                    "引用代码用 [src:path:line] 格式；中文简洁回答；不重复问题；末尾列出参考来源。"
                )
            else:  # has_files only
                system_prompt = (
                    "你是 Code Wiki 智能助手。\n"
                    "上方列出了用户附加的本地文件及其完整内容。你必须基于这些文件内容回答，不要使用外部知识。\n"
                    "回答时请按以下流程：\n"
                    "1. 先简要分析附加文件的内容（文件用途、关键结构、主要函数/类等）\n"
                    "2. 再针对用户的具体问题，从文件内容中提取答案\n"
                    "当用户询问文件列表时，直接从文件清单列出；询问代码问题时引用具体文件内容。\n"
                    "要求：涉及项目结构、配置、API等结构化信息优先用 Markdown 表格呈现；"
                    "中文简洁回答；引用文件用 `文件名` 标明；不编造不存在的内容。"
                )
            builder = (
                PromptBuilder()
                .add_system(system_prompt)
                .add_file_context(file_context or [])
                .add_context(retrieved, source_codes)
                .add_history(history, max_turns=6)
                .add_question(question)
            )
            messages = builder.build()
        else:
            system_prompt = (
                "你是 Code Wiki 智能助手。未找到相关 Wiki 文档，以下回答基于通用知识，"
                "可能不够准确。建议运行代码分析以获取更精准的结果。\n"
                "涉及结构化信息时请多使用 Markdown 表格。"
            )
            messages = [
                {"role": "system", "content": system_prompt},
                *history[-6:],
                {"role": "user", "content": question},
            ]

        # Step 4: Stream from DeepSeek
        try:
            async with self.client.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": 2048,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            import json
                            chunk = json.loads(data)
                            delta = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if delta:
                                yield delta
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

        except Exception as e:
            # Fallback: simple keyword-based response
            yield f"\n\n[WARNING] LLM 调用失败: {e}\n\n"

            # Return retrieved chunks as fallback
            if retrieved:
                yield "**基于关键词检索到的相关文档片段：**\n\n"
                for r in retrieved[:3]:
                    yield f"- [{r.get('source', '?')}] {r.get('title', '')}\n"
                    yield f"  {r.get('text', '')[:300]}...\n\n"
            else:
                yield "请确保已配置有效的 DeepSeek API Key 并已运行代码分析。\n"

    async def chat_simple(
        self,
        question: str,
        history: List[dict],
    ) -> str:
        """Non-streaming version — collects full response."""
        parts: List[str] = []
        async for chunk in self.chat_stream(question, history):
            parts.append(chunk)
        return "".join(parts)
