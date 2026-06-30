"""Shared configuration for Code Wiki backend."""

import json
import os
import sys as _sys
from pathlib import Path


def _to_native_path(path_str: str) -> str:
    """Convert Windows paths to native paths (/mnt/c/...) on Linux/WSL."""
    if not path_str or _sys.platform != "linux":
        return path_str
    if len(path_str) >= 2 and path_str[1] == ":":
        drive = path_str[0].lower()
        rest = path_str[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return path_str.replace("\\", "/")

# ---- Global config (in-memory, persisted to .code-wiki/config.json) ----
_config: dict = {
    "repo_path": "",
    "wiki_path": "",  # explicit wiki output directory; if empty, defaults to {repo_path}/.code-wiki
    "languages": ["python", "typescript", "javascript"],
    "exclude_patterns": [
        "__pycache__/", ".git/", "node_modules/", ".venv/",
        "dist/", "build/", "*.pyc", ".code-wiki/",
    ],
    "llm": {
        "api_key": "",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.3,
    },
    "theme": "system",
}

# Look for config in CWD (or its parent) as a fallback when repo_path is not yet known
def _find_config_in_cwd() -> Path | None:
    """Search for .code-wiki/config.json in common locations.
    
    This is needed because _get_config_path() requires repo_path to be set,
    but repo_path is only loaded from the config file — a chicken-and-egg
    problem solved by broadly searching known locations.
    """
    candidates = [
        Path.cwd() / ".code-wiki" / "config.json",
        Path.cwd().parent / ".code-wiki" / "config.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def get_config() -> dict:
    return _config


def get_wiki_path() -> Path:
    """Return the wiki output directory.
    
    If wiki_path is explicitly configured, use it (or create .code-wiki inside it).
    If it already ends with '.code-wiki' or is the exact wiki dir, use it as-is.
    Otherwise defaults to {repo_path}/.code-wiki/.
    """
    explicit = _config.get("wiki_path", "")
    if explicit:
        native = _to_native_path(explicit)
        p = Path(native)
        # Get last path component (handles both / and \ cross-platform)
        final = explicit.rstrip("/\\").split("/")[-1].rsplit("\\")[-1]
        if final == ".code-wiki":
            return p
        # The path is a parent directory; create .code-wiki inside it
        return p / ".code-wiki"
    repo = _config.get("repo_path", "")
    if repo:
        return Path(_to_native_path(repo)) / ".code-wiki"
    return Path(".code-wiki")  # fallback to CWD


def _get_config_path() -> Path | None:
    repo = _config.get("repo_path", "")
    if repo:
        return Path(_to_native_path(repo)) / ".code-wiki" / "config.json"
    # Fallback: search CWD and parent for config.json
    cwd_config = _find_config_in_cwd()
    if cwd_config:
        return cwd_config
    return None


def load_config_from_disk():
    """Try to load config from repo's .code-wiki/config.json."""
    global _config
    path = _get_config_path()
    if path and path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            _config.update(saved)
        except (json.JSONDecodeError, IOError):
            pass


def save_config_to_disk():
    """Persist config to .code-wiki/config.json (excluding api_key)."""
    path = _get_config_path()
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    to_save = {k: v for k, v in _config.items() if k != "llm"}
    to_save["llm"] = {k: v for k, v in _config["llm"].items() if k != "api_key"}
    with open(path, "w") as f:
        json.dump(to_save, f, indent=2, ensure_ascii=False)
