"""Configuration management routes."""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from config import _config, save_config_to_disk, load_config_from_disk

logger = logging.getLogger("code-wiki.config")

router = APIRouter()


class LLMConfigSchema(BaseModel):
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    temperature: float = 0.3


class ConfigSchema(BaseModel):
    repo_path: str = ""
    wiki_path: str = ""
    languages: list[str] = ["python", "typescript", "javascript"]
    exclude_patterns: list[str] = []
    llm: LLMConfigSchema = LLMConfigSchema()
    theme: str = "system"


@router.get("/config")
async def get_config():
    """Return current config (excluding api_key)."""
    cfg = {k: v for k, v in _config.items()}
    cfg["llm"] = {k: v for k, v in _config["llm"].items() if k != "api_key"}
    return cfg


@router.put("/config")
async def update_config(data: ConfigSchema):
    """Update configuration."""
    _config["repo_path"] = data.repo_path
    _config["wiki_path"] = data.wiki_path
    _config["languages"] = data.languages
    _config["exclude_patterns"] = data.exclude_patterns
    _config["theme"] = data.theme
    # Always update api_key — the frontend explicitly includes it in every PUT.
    # Using a conditional here means a PUT with api_key="" would leave the old value
    # in memory, leading to confusion when the user has already configured a key.
    key_len = len(data.llm.api_key) if data.llm.api_key else 0
    _config["llm"]["api_key"] = data.llm.api_key
    logger.info(f"Config updated: repo={data.repo_path!r}, wiki_path={data.wiki_path!r}, api_key_len={key_len}, model={data.llm.model}")
    _config["llm"]["model"] = data.llm.model
    _config["llm"]["base_url"] = data.llm.base_url
    _config["llm"]["temperature"] = data.llm.temperature
    save_config_to_disk()
    # After saving, try to load any existing config for this repo.
    # IMPORTANT: save_config_to_disk strips api_key for security, so the disk copy
    # has no api_key.  load_config_from_disk would overwrite our in-memory key.
    # Preserve it across the reload.
    if data.repo_path:
        api_key_before = _config["llm"].get("api_key", "")
        load_config_from_disk()
        if api_key_before:
            _config["llm"]["api_key"] = api_key_before
    return {"status": "ok"}
