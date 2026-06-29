"""File watcher management endpoint — start/stop watching for changes."""

import os
from fastapi import APIRouter
from pydantic import BaseModel

from config import _config
from services.watcher import FileWatcher
from routes.events import broadcast

router = APIRouter()

# Global watcher instance
_watcher: FileWatcher | None = None


class WatcherStatus(BaseModel):
    running: bool
    watched_path: str = ""
    files_tracked: int = 0


@router.get("/watcher/status")
async def get_watcher_status() -> WatcherStatus:
    """Get current watcher status."""
    global _watcher
    if _watcher and _watcher._running:
        return WatcherStatus(
            running=True,
            watched_path=_watcher.repo_path,
            files_tracked=len(_watcher._hashes),
        )
    return WatcherStatus(running=False)


@router.post("/watcher/start")
async def start_watcher():
    """Start file watcher for the configured repo."""
    global _watcher
    repo_path = _config.get("repo_path", "")
    if not repo_path or not os.path.isdir(repo_path):
        return {"error": "Invalid repo path"}

    excludes = _config.get("exclude_patterns", [])

    # Stop existing watcher
    if _watcher:
        _watcher.stop()

    _watcher = FileWatcher(
        repo_path=repo_path,
        exclude_patterns=excludes + [".code-wiki/"],
        poll_interval=1.0,
        debounce_ms=500,
    )

    async def handle_change(changed_files: list[str]):
        """When files change, broadcast SSE and trigger incremental analysis."""
        # Broadcast SSE event
        broadcast("file-change", {
            "files": changed_files,
            "action": "changed",
        })

        # Trigger incremental pipeline
        from routes.scan import _run_scan
        await _run_scan(repo_path, "incremental", changed_files)

    _watcher.on_change(handle_change)
    _watcher.start()

    return {"status": "started", "path": repo_path}


@router.post("/watcher/stop")
async def stop_watcher():
    """Stop file watcher."""
    global _watcher
    if _watcher:
        _watcher.stop()
        _watcher = None
        return {"status": "stopped"}
    return {"status": "not_running"}
