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
    ) -> AsyncGenerator[str, None]:
        """
        RAG query → SSE stream.
        Yields plain text chunks; frontend wraps in `data: ...\n\n`.
        """
        # Step 1: Retrieve relevant Wiki chunks (semantic search)
        try:
            query_vec = await self.embedder.embed_query(question)
            retrieved = self.embedder.query(question, top_k=8, query_embedding=query_vec)
        except Exception as e:
            logging.warning(f"Embedder query failed: {e}")
            retrieved = []

        # Step 2: Build context from retrieved chunks
        if retrieved:
            # Build a project overview from the source paths
            sources = list(dict.fromkeys(r.get("source", "unknown") for r in retrieved))  # deduplicate, keep order
            overview_lines = ["**项目文档概览（基于检索到的 Wiki 文档）**："]
            for src in sources[:20]:
                overview_lines.append(f"  - {src}")
            if len(sources) > 20:
                overview_lines.append(f"  ... 共 {len(sources)} 个文件")
            overview = "\n".join(overview_lines)

            context_parts = []
            for i, r in enumerate(retrieved, 1):
                src = r.get("source", "unknown")
                title = r.get("title", "")
                text = r.get("text", "")[:1500]
                context_parts.append(
                    f"[{i}] 来源: {src}\n标题: {title}\n{text}"
                )
            context = overview + "\n\n---\n\n" + "\n\n---\n\n".join(context_parts)

            # Step 2.5: Read actual source code for each unique source path
            loop = asyncio.get_running_loop()
            source_parts = []
            seen_sources = set()
            for r in retrieved:
                src = r.get("source", "")
                if not src or src in seen_sources:
                    continue
                seen_sources.add(src)
                code = await loop.run_in_executor(None, self._read_source, self.repo_path, src)
                if code:
                    source_parts.append(f"### 源代码: {src}\n```\n{code}\n```")
            if source_parts:
                source_context = "\n\n---\n\n".join(source_parts[:5])  # at most 5 source files to save budget
                context += "\n\n---\n\n**相关源代码**：\n\n" + source_context
        else:
            context = "（未找到相关 Wiki 文档，以下回答基于通用知识，可能不够准确，建议运行代码分析以获取更精准的结果）"

        # Step 3: Build system prompt
        system_prompt = f"""你是 Code Wiki 智能助手，帮助用户理解项目代码。

上方提供了 **Wiki 文档** 和 **相关源代码**。Wiki 是 AI 生成的代码分析，源代码是项目原始文件。
回答问题时，优先参考 Wiki 文档了解高层逻辑，再结合源代码确认具体实现细节。如果信息不完整，可以结合编程常识补充，但要说明哪些来自项目文件、哪些是推断的。

**要求**：
- 引用代码位置时使用 [src:path:line] 格式
- 用中文回答，简洁专业，直接给出答案
- **禁止重复或转述用户的问题**，直接回答
- 回答末尾列出参考的文档和文件来源

**上下文**：
{context}"""

        # Prepend a short instruction to the question to prevent model from echoing
        enhanced_question = f"直接回答下面的问题，不要重复问题原文：{question}"
        messages = [
            {"role": "system", "content": system_prompt},
            *history[-10:],  # Last 10 turns
            {"role": "user", "content": enhanced_question},
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
