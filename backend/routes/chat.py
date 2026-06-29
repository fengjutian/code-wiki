"""SSE streaming chat endpoint — RAG-based Q&A."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import _config, get_wiki_path
from services.chat_service import ChatService

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []


@router.post("/chat")
async def chat(request: ChatRequest):
    """RAG Chat with SSE streaming."""
    repo_path = _config.get("repo_path", "")
    llm_config = _config.get("llm", {})
    api_key = llm_config.get("api_key", "")

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="请先在设置中配置 DeepSeek API Key",
        )

    chat_service = ChatService(
        repo_path=repo_path,
        api_key=api_key,
        wiki_path=str(get_wiki_path()),
        model=llm_config.get("model", "deepseek-v4-flash"),
        base_url=llm_config.get("base_url", "https://api.deepseek.com"),
        temperature=llm_config.get("temperature", 0.3),
    )

    async def generate():
        try:
            async for chunk in chat_service.chat_stream(
                request.question, request.history
            ):
                # Send raw text chunk (SSE doesn't require JSON)
                safe = chunk.replace("\n", "\ndata: ")
                yield f"data: {safe}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [错误] {str(e)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
