"""File tree and file content endpoints."""

from fastapi import APIRouter, HTTPException, Query
from config import _config
import asyncio
import os
import fnmatch
import time

router = APIRouter()

# ── File-tree cache ──────────────────────────────────────────────
_tree_cache: dict = {"data": None, "ts": 0.0, "repo": ""}
_TREE_CACHE_TTL: float = 5.0  # seconds

KNOWN_EXTS = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml",
    ".md", ".mdx", ".toml", ".rs", ".sh", ".bash", ".css", ".html",
    ".xml", ".sql", ".go", ".java", ".kt", ".swift", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp", ".vue", ".svelte", ".txt", ".cfg",
    ".ini", ".env", ".gitignore", ".dockerignore",
)


def _is_excluded(rel_path: str, patterns: list[str]) -> bool:
    for p in patterns:
        if fnmatch.fnmatch(rel_path, p):
            return True
        if p.endswith("/") and (rel_path == p[:-1] or rel_path.startswith(p)):
            return True
    return False


def _get_repo_path() -> str:
    repo = _config.get("repo_path", "")
    if not repo or not os.path.isdir(repo):
        raise HTTPException(status_code=400, detail="仓库路径未配置或不存在")
    return repo


def _build_tree_sync(repo_path: str, excludes: list[str]) -> list[dict]:
    """Synchronous recursive tree builder using os.scandir (fast)."""
    def _walk(base: str) -> list[dict]:
        items: list[dict] = []
        try:
            with os.scandir(base) as it:
                entries = sorted(it, key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return items

        for entry in entries:
            rel = os.path.relpath(entry.path, repo_path).replace("\\", "/")

            if _is_excluded(rel + ("/" if entry.is_dir() else ""), excludes):
                continue

            if entry.is_dir():
                children = _walk(entry.path)
                items.append({
                    "name": entry.name,
                    "path": rel,
                    "type": "directory",
                    "status": "pending",
                    "excluded": False,
                    "children": children,
                })
            elif entry.name.endswith(KNOWN_EXTS):
                items.append({
                    "name": entry.name,
                    "path": rel,
                    "type": "file",
                    "status": "pending",
                    "excluded": False,
                })

        return items

    return _walk(repo_path)


@router.get("/files")
async def get_file_tree():
    """Scan repo and return file tree with analysis status (cached, non-blocking)."""
    repo_path = _config.get("repo_path", "")
    if not repo_path or not os.path.isdir(repo_path):
        return []

    # ── Cache check ──
    now = time.monotonic()
    if (_tree_cache["data"] is not None and
        _tree_cache["repo"] == repo_path and
        (now - _tree_cache["ts"]) < _TREE_CACHE_TTL):
        return _tree_cache["data"]

    excludes = _config.get("exclude_patterns", [])

    # Run blocking I/O in a thread pool to keep the event loop free
    loop = asyncio.get_running_loop()
    tree = await loop.run_in_executor(None, _build_tree_sync, repo_path, excludes)

    # ── Populate cache ──
    _tree_cache["data"] = tree
    _tree_cache["ts"] = now
    _tree_cache["repo"] = repo_path

    return tree


@router.get("/files/content")
async def get_file_content(path: str = Query(..., description="文件的相对路径")):
    """Read and return the content of a file from the repo."""
    repo_path = _get_repo_path()
    full_path = os.path.normpath(os.path.join(repo_path, path))

    # Prevent path traversal — resolve symlinks/junctions
    try:
        full_path = os.path.realpath(full_path)
        norm_repo = os.path.realpath(repo_path)
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid path")

    if os.name == "nt":
        if not full_path.lower().startswith(norm_repo.lower()):
            raise HTTPException(status_code=403, detail="路径越权")
    elif not full_path.startswith(norm_repo):
        raise HTTPException(status_code=403, detail="路径越权")

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {str(e)}")
