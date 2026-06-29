"""LLM connection test endpoint."""

import logging
from fastapi import APIRouter
from pydantic import BaseModel
from httpx import AsyncClient, Timeout

logger = logging.getLogger("code-wiki.llm_test")

router = APIRouter()


class LLMTestRequest(BaseModel):
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    temperature: float = 0.3


@router.post("/llm/test")
async def test_llm_connection(req: LLMTestRequest):
    """Test whether the configured LLM API is reachable and working."""
    if not req.api_key:
        return {"ok": False, "error": "API Key 未配置", "status_code": None}

    base_url = req.base_url.rstrip("/")
    url = f"{base_url}/v1/chat/completions"

    try:
        async with AsyncClient(
            headers={
                "Authorization": f"Bearer {req.api_key}",
                "Content-Type": "application/json",
            },
            timeout=Timeout(15.0),
        ) as client:
            resp = await client.post(
                url,
                json={
                    "model": req.model,
                    "messages": [
                        {"role": "user", "content": "hi"},
                    ],
                    "max_tokens": 5,
                    "temperature": req.temperature,
                },
            )

        if resp.status_code == 200:
            data = resp.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return {
                "ok": True,
                "status_code": resp.status_code,
                "model_used": data.get("model", req.model),
                "response_preview": content,
            }
        else:
            detail = ""
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:500]
            return {
                "ok": False,
                "error": f"API 返回错误 ({resp.status_code})",
                "status_code": resp.status_code,
                "detail": str(detail),
            }
    except Exception as e:
        logger.warning(f"LLM test connection failed: {e}")
        return {
            "ok": False,
            "error": f"连接失败: {e}",
            "status_code": None,
        }
