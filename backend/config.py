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


# ---- Bootstrap config path (always in the backend's own directory) ----
_BACKEND_DIR = Path(__file__).resolve().parent
_BOOTSTRAP_CONFIG = _BACKEND_DIR / ".code-wiki" / "config.json"


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


def _find_config_in_cwd() -> Path | None:
    """Search for .code-wiki/config.json in common locations.
    
    Searches: CWD, CWD parent, and the backend module directory.
    The bootstrap config in the backend directory breaks the chicken-and-egg
    problem: repo_path is saved there so it can survive a restart.
    """
    candidates = [
        Path.cwd() / ".code-wiki" / "config.json",
        Path.cwd().parent / ".code-wiki" / "config.json",
        _BACKEND_DIR / ".code-wiki" / "config.json",
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
    """Return the primary config path for the current repo, or fallback to bootstrap."""
    repo = _config.get("repo_path", "")
    if repo:
        return Path(_to_native_path(repo)) / ".code-wiki" / "config.json"
    # Fallback: search CWD, parent, and backend dir for any config.json
    cwd_config = _find_config_in_cwd()
    if cwd_config:
        return cwd_config
    # If nothing exists yet, default to bootstrap location so we can at least save
    return _BOOTSTRAP_CONFIG


def load_config_from_disk():
    """Try to load config from repo's .code-wiki/config.json.
    
    Load order:
      1. Bootstrap config in backend/ dir (always checked first to recover repo_path)
      2. If repo_path is now known, also load from {repo_path}/.code-wiki/config.json
         (the repo-specific config may have more recent settings)
    """
    global _config
    # Step 1: always try bootstrap config to recover repo_path
    if _BOOTSTRAP_CONFIG.exists():
        try:
            with open(_BOOTSTRAP_CONFIG, "r", encoding="utf-8") as f:
                saved = json.load(f)
            _config.update(saved)
        except (json.JSONDecodeError, IOError):
            pass
    # Step 2: if repo_path is now set, also load from repo's own config
    repo = _config.get("repo_path", "")
    if repo:
        repo_config = Path(_to_native_path(repo)) / ".code-wiki" / "config.json"
        if repo_config.exists() and repo_config != _BOOTSTRAP_CONFIG:
            try:
                with open(repo_config, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                _config.update(saved)
            except (json.JSONDecodeError, IOError):
                pass


def save_config_to_disk():
    """Persist config to both the bootstrap location and the repo-specific location.
    
    The bootstrap copy (backend/.code-wiki/config.json) ensures repo_path survives
    a restart. The repo copy ({repo_path}/.code-wiki/config.json) is for portability.
    Both copies exclude api_key for security.
    """
    to_save = {k: v for k, v in _config.items() if k != "llm"}
    to_save["llm"] = {k: v for k, v in _config["llm"].items() if k != "api_key"}

    # Always write to bootstrap location
    _BOOTSTRAP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(_BOOTSTRAP_CONFIG, "w", encoding="utf-8") as f:
        json.dump(to_save, f, indent=2, ensure_ascii=False)

    # Also write to repo-specific location if repo_path is set
    repo = _config.get("repo_path", "")
    if repo:
        repo_config = Path(_to_native_path(repo)) / ".code-wiki" / "config.json"
        if repo_config != _BOOTSTRAP_CONFIG:
            repo_config.parent.mkdir(parents=True, exist_ok=True)
            with open(repo_config, "w", encoding="utf-8") as f:
                json.dump(to_save, f, indent=2, ensure_ascii=False)
