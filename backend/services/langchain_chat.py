"""
LangChain LCEL RAG Chat Service — history-aware retrieval + streaming.

Uses LangChain's standard RAG chain (create_history_aware_retriever +
create_stuff_documents_chain) with FAISS vector store and DeepSeek LLM.

Provides a /api/chat/v2 endpoint that runs alongside the existing
chat_service.py for gradual migration.

Architecture::

    User Question + History
        │
        ▼
    HistoryAwareRetriever (reformulates query from chat history)
        │
        ▼
    FAISS MMR Retriever (top_k=20, fetch_k=40, diversity λ=0.7)
        │
        ▼
    StuffDocumentsChain (DeepSeek Chat → SSE stream)

If LangChain is not installed, falls back to the existing ChatService.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, List, Optional

from httpx import AsyncClient, Timeout

logger = logging.getLogger("code-wiki.langchain_chat")

# ---------------------------------------------------------------------------
# Try importing LangChain — graceful fallback if not installed
# ---------------------------------------------------------------------------
_LANGCHAIN_AVAILABLE = False
try:
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.runnables import RunnablePassthrough
    from langchain_core.runnables.history import RunnableWithMessageHistory
    from langchain.chains import create_history_aware_retriever, create_retrieval_chain
    from langchain.chains.combine_documents import create_stuff_documents_chain
    from langchain_community.chat_models import ChatDeepSeek  # type: ignore[import-untyped]
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    logger.info(
        "LangChain not installed — LCEL RAG chain disabled. "
        "Install with: pip install langchain langchain-community langchain-core"
    )


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TEMPERATURE = 0.3
MMR_FETCH_K = 40       # How many candidates to fetch before MMR diversification
MMR_K = 20             # How many to return after MMR
MMR_LAMBDA = 0.7       # 1.0 = pure similarity, 0.0 = pure diversity


# ---------------------------------------------------------------------------
# System prompts (same as existing chat_service.py for consistency)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_RETRIEVAL = (
    "你是 Code Wiki 智能助手，帮助用户理解项目代码。\n"
    "上方有从代码库中按函数/类/方法提取的相关代码片段。优先参考代码实现逻辑，"
    "结合编程常识回答。信息不完整时可补充说明，但要标明来源。\n"
    "要求：涉及项目结构、接口列表、依赖关系等结构化信息时优先使用 Markdown 表格呈现；"
    "引用代码用 [src:path:line] 格式；中文简洁回答；不重复问题；末尾列出参考来源。"
)

CONTEXTUALIZE_PROMPT = (
    "根据聊天历史，将用户的最新问题改写为一个独立、完整的查询语句，"
    "使其不依赖历史上下文即可理解。不要回答问题，只返回改写后的查询。"
    "\n\n聊天历史：\n{chat_history}\n\n最新问题：{input}\n\n改写后的查询："
)


class LangChainChatService:
    """LCEL-based RAG chat service with history-aware retrieval.

    Usage::

        svc = LangChainChatService(repo_path, api_key, wiki_path)
        async for chunk in svc.chat_stream(question, history):
            yield chunk
    """

    def __init__(
        self,
        repo_path: str,
        api_key: str,
        wiki_path: str = "",
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        temperature: float = DEFAULT_TEMPERATURE,
    ):
        self.repo_path = repo_path
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature

        from services.embedder import Embedder
        self.embedder = Embedder(
            repo_path=repo_path,
            wiki_path=wiki_path,
            api_key=api_key,
            base_url=base_url,
        )

        self._client: Optional[AsyncClient] = None
        self._chain = None

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

    # ------------------------------------------------------------------
    # LCEL Chain (lazy-built on first use)
    # ------------------------------------------------------------------

    def _build_chain(self):
        """Build the LangChain RAG chain with history-aware retriever."""
        if not _LANGCHAIN_AVAILABLE:
            return None
        if self._chain is not None:
            return self._chain

        try:
            # Load FAISS store
            self.embedder._store.load()

            # Build LLM
            llm = ChatDeepSeek(
                model=self.model,
                api_key=self.api_key,
                api_base=self.base_url,
                temperature=self.temperature,
                streaming=True,
            )

            # Build retriever from FAISS
            retriever = self.embedder._store._store.as_retriever(
                search_type="mmr",
                search_kwargs={
                    "k": MMR_K,
                    "fetch_k": MMR_FETCH_K,
                    "lambda_mult": MMR_LAMBDA,
                },
            )

            # 1. History-aware retriever
            history_retriever = create_history_aware_retriever(
                llm,
                retriever,
                ChatPromptTemplate.from_messages([
                    ("system", CONTEXTUALIZE_PROMPT),
                    MessagesPlaceholder("chat_history"),
                    ("human", "{input}"),
                ]),
            )

            # 2. QA chain
            qa_chain = create_stuff_documents_chain(
                llm,
                ChatPromptTemplate.from_messages([
                    ("system", SYSTEM_PROMPT_RETRIEVAL + "\n\n上下文：\n{context}"),
                    MessagesPlaceholder("chat_history"),
                    ("human", "{input}"),
                ]),
            )

            # 3. Full RAG chain
            self._chain = create_retrieval_chain(history_retriever, qa_chain)
            logger.info("LCEL RAG chain built successfully")
            return self._chain

        except Exception as e:
            logger.warning("Failed to build LCEL chain: %s", e)
            return None

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        question: str,
        history: List[dict],
        file_context: List[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """RAG query → SSE stream (LangChain LCEL path with fallback)."""
        chain = self._build_chain()

        if chain is not None:
            # LangChain path
            async for chunk in self._stream_lcel(chain, question, history):
                yield chunk
        else:
            # Fallback to existing ChatService
            from services.chat_service import ChatService
            fallback = ChatService(
                repo_path=self.repo_path,
                api_key=self.api_key,
                wiki_path=self.embedder.wiki_path,
                model=self.model,
                base_url=self.base_url,
                temperature=self.temperature,
            )
            async for chunk in fallback.chat_stream(question, history, file_context):
                yield chunk

    async def _stream_lcel(
        self,
        chain,
        question: str,
        history: List[dict],
    ) -> AsyncGenerator[str, None]:
        """Stream output from the LCEL chain."""
        try:
            # Convert history to LangChain format
            lc_history = [
                {"role": h.get("role", "user"), "content": h.get("content", "")}
                for h in history[-6:]
            ]

            async for event in chain.astream_events(
                {"input": question, "chat_history": lc_history},
                version="v2",
            ):
                kind = event.get("event", "")
                if kind == "on_chat_model_stream":
                    content = event.get("data", {}).get("chunk", {}).content
                    if content:
                        yield content
                elif kind == "on_retriever_end":
                    # Log retrieved sources
                    docs = event.get("data", {}).get("output", [])
                    if docs:
                        sources = set()
                        for doc in docs:
                            src = doc.metadata.get("source", "?") if hasattr(doc, 'metadata') else "?"
                            sources.add(src)
                        logger.info("RAG retrieved %d docs from %d sources", len(docs), len(sources))

        except Exception as e:
            logger.warning("LCEL stream failed: %s — falling back", e)
            # Fall back to direct LLM call
            yield f"\n\n[WARNING] RAG 链出错，使用直接回答: {e}\n\n"
            async for chunk in self._stream_direct(question, history):
                yield chunk

    async def _stream_direct(
        self,
        question: str,
        history: List[dict],
    ) -> AsyncGenerator[str, None]:
        """Direct LLM stream (no RAG) — last-resort fallback."""
        messages = [
            {"role": "system", "content": "你是 Code Wiki 智能助手。"},
        ]
        for h in history[-6:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": question})

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
            yield f"\n\n[ERROR] {e}\n"

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
