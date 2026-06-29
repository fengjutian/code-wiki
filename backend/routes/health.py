"""Health check endpoint — service status and model info."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Return service health status and which models are configured."""
    from config import get_config

    cfg = get_config()
    llm = cfg.get("llm", {})

    return {
        "status": "ok",
        "service": "code-wiki",
        "version": "0.1.0",
        "models": {
            "configured_model": llm.get("model", "unknown"),
            "base_url": llm.get("base_url", ""),
            "temperature": llm.get("temperature", 0.0),
            "has_api_key": bool(llm.get("api_key", "")),
        },
        "config": {
            "repo_path": cfg.get("repo_path", ""),
            "languages": cfg.get("languages", []),
            "theme": cfg.get("theme", "system"),
        },
    }
