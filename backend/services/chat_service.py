"""
RAG Chat Service — retrieves relevant Wiki chunks and streams LLM answers.

Pipeline:
  user question → keyword search Embedder → Top-K Wiki chunks
  → construct prompt → DeepSeek Chat API (SSE stream) → yield chunks
"""

import asyncio
import logging
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
            retrieved = self.embedder.query(question, top_k=5, query_embedding=query_vec if query_vec else None)
        except Exception as e:
            logging.warning(f"Embedder query failed: {e}")
            retrieved = []

        # Step 2: Build context from retrieved chunks
        if retrieved:
            context_parts = []
            for i, r in enumerate(retrieved, 1):
                src = r.get("source", "unknown")
                title = r.get("title", "")
                text = r.get("text", "")[:1500]
                context_parts.append(
                    f"[{i}] 来源: {src}\n标题: {title}\n{text}"
                )
            context = "\n\n---\n\n".join(context_parts)
        else:
            context = "（未找到相关 Wiki 文档，请先分析代码生成 Wiki）"

        # Step 3: Build system prompt
        system_prompt = f"""你是 Code Wiki 智能助手。根据以下 Wiki 文档片段回答用户问题。

**规则**：
- 只能基于提供的 Wiki 片段回答，不要编造信息
- 引用代码位置时使用 [src:path:line] 格式
- 如果 Wiki 中没有相关信息，说"未在文档中找到相关信息，建议先运行代码分析生成 Wiki"
- 用中文回答，简洁专业，直接给出答案
- **禁止在回答中重复、转述、引用用户的问题**，直接回答
- 回答末尾列出参考的文档来源

**Wiki 文档片段**：
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
