"""Wiki content retrieval."""

import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pathlib import Path
from config import _config, get_wiki_path
import time

router = APIRouter()


def _wiki_to_source_path(wiki_path: str) -> str:
    """Convert a wiki .md path back to the source file path.
    e.g. services/user.md → services/user.py
         components/Button.md → components/Button.tsx
    Tries known source extensions; falls back to .py for backward compat.
    """
    if not wiki_path.endswith(".md"):
        return wiki_path
    base = wiki_path[:-3]
    for ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
        candidate = base + ext
        # Check if a source file with this extension exists (cheap stat)
        repo_path = _config.get("repo_path", "")
        if repo_path and Path(repo_path, candidate).exists():
            return candidate
    return base + ".py"

# Simple in-memory cache with TTL
_cache: dict = {}
_CACHE_TTL = 30  # seconds


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    if entry:
        del _cache[key]
    return None


def _cache_set(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


def clear_cache():
    """Clear the wiki cache (called after scan generates new wiki files)."""
    _cache.clear()


def _build_wiki_tree(wiki_dir: Path) -> list:
    """Build a hierarchical tree from .md files in wiki_dir.

    Returns a list of nodes, each with:
      - name, path, type ("directory" | "file")
      - file nodes also have sourcePath
      - directory nodes have children
    """
    root: dict = {}

    chroma_dir = wiki_dir / "chroma"
    for item in sorted(wiki_dir.rglob("*.md")):
        rel = item.relative_to(wiki_dir)
        # Skip files under the chroma directory
        try:
            if chroma_dir in item.parents or item.parent == chroma_dir:
                continue
        except (ValueError, OSError):
            continue
        parts = list(rel.parts)
        current = root
        # Walk/create directory chain
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        # Place the file
        file_name = parts[-1]
        current[file_name] = {
            "_type": "file",
            "_path": str(rel).replace("\\", "/"),
            "_name": file_name,
            "_sourcePath": _wiki_to_source_path(str(rel)),
        }

    def _to_nodes(d: dict, parent_path: str = "") -> list:
        nodes = []
        # First: subdirectories (keys that are dicts, not file entries)
        dir_keys = sorted(
            k for k in d
            if not k.startswith("_")
            and isinstance(d[k], dict)
            and d[k].get("_type") != "file"
        )
        for key in dir_keys:
            full_dir_path = f"{parent_path}/{key}" if parent_path else key
            children = _to_nodes(d[key], full_dir_path)
            nodes.append({
                "name": key,
                "path": full_dir_path,
                "type": "directory",
                "children": children,
            })
        # Then: file entries (dicts with _type == "file")
        file_keys = sorted(
            k for k in d
            if isinstance(d[k], dict) and d[k].get("_type") == "file"
        )
        for key in file_keys:
            v = d[key]
            nodes.append({
                "name": v["_name"],
                "path": v["_path"],
                "sourcePath": v["_sourcePath"],
                "type": "file",
            })
        return nodes

    return _to_nodes(root)


@router.get("/wiki/tree")
async def get_wiki_tree():
    """Return the Wiki file tree from .code-wiki/, as a hierarchical tree."""
    cached = _cache_get("tree")
    if cached is not None:
        return cached

    repo_path = _config.get("repo_path", "")
    if not repo_path:
        return []

    wiki_dir = get_wiki_path()
    if not wiki_dir.exists():
        return []

    # Run in executor to avoid blocking the event loop with rglob
    loop = asyncio.get_running_loop()
    tree = await loop.run_in_executor(None, _build_wiki_tree, wiki_dir)
    _cache_set("tree", tree)
    return tree


@router.get("/wiki/{path:path}")
async def get_wiki_page(path: str):
    """Get a Wiki page's Markdown content."""
    cache_key = f"page:{path}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return Response(
            content=cached,
            media_type="text/markdown; charset=utf-8"
        )

    repo_path = _config.get("repo_path", "")
    if not repo_path:
        raise HTTPException(status_code=404, detail="No repo configured")

    wiki_dir = get_wiki_path()
    file_path = wiki_dir / path

    # Path traversal protection
    try:
        file_path = file_path.resolve()
        wiki_dir = wiki_dir.resolve()
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not str(file_path).startswith(str(wiki_dir)):
        raise HTTPException(status_code=403, detail="路径越权")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Wiki page not found")

    content = file_path.read_text(encoding="utf-8")
    _cache_set(cache_key, content)
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8"
    )
