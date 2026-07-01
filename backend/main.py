"""
Code Wiki — FastAPI Backend
Code analysis, Wiki generation, LLM orchestration, RAG chat
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ---- Logging + encoding setup (early, before any imports that might print) ----
if sys.platform == "win32":
    # Force UTF-8 on Windows to avoid GBK encoding errors with Unicode characters
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("code-wiki")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# Fix for Windows: ProactorEventLoop crashes with OSError [WinError 64] on client disconnect.
# Use SelectorEventLoop instead, which handles socket cleanup gracefully.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logger.info("Windows detected: switched to SelectorEventLoop to avoid WinError 64")

from config import _config, get_config, load_config_from_disk, save_config_to_disk, get_wiki_path


# ---- Lifespan handler (replaces deprecated on_event) ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup logic: ensure .code-wiki directories exist + register WinError 64 handler."""
    # ---- Register WinError-64 suppression on the running loop ----
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_win32_exception_handler)
    logger.info("WinError-64 exception handler registered on event loop")

    # Reload config from disk (catches any changes made since module init)
    load_config_from_disk()
    repo_path = get_config().get("repo_path", "")
    if repo_path and os.path.isdir(repo_path):
        wiki_dir = get_wiki_path()
        wiki_dir.mkdir(parents=True, exist_ok=True)
        (wiki_dir / "faiss_index").mkdir(exist_ok=True)
    yield  # App runs here


# ---- Suppress WinError 64 noise on Windows (safety net) ----
def _win32_exception_handler(loop, context):
    """Suppress noisy 'Task exception was never retrieved' for WinError 64 on Windows.
    This is a cosmetic handler: the ProactorEventLoop sometimes raises OSError(64)
    when a client disconnects before accept() completes.  The connection is dropped
    anyway; logging a full traceback is misleading."""
    exc = context.get("exception")
    if exc is not None:
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 64:
            return  # Suppress — client just disconnected
        # Also catch the higher-level wrapper from proactor_events
        if isinstance(exc, OSError) and "WinError 64" in str(exc):
            return
    # For anything else, use the default handler
    loop.default_exception_handler(context)


# ---- App Factory ----
def create_app() -> FastAPI:
    app = FastAPI(
        title="Code Wiki API",
        version="0.1.0",
        docs_url="/api/docs",
        lifespan=lifespan,
    )

    # CORS — allow Tauri dev server (localhost:1420)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "tauri://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # GZip — compress JSON responses (file tree, wiki, etc.)
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # ---- Register routes ----
    from routes.scan import router as scan_router
    from routes.wiki import router as wiki_router
    from routes.chat import router as chat_router
    from routes.status import router as status_router
    from routes.diagrams import router as diagrams_router
    from routes.files import router as files_router
    from routes.events import router as events_router
    from routes.watcher import router as watcher_router
    from routes.config import router as config_router
    from routes.health import router as health_router
    from routes.llm_test import router as llm_test_router
    from routes.graph import router as graph_router

    app.include_router(scan_router, prefix="/api")
    app.include_router(wiki_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(status_router, prefix="/api")
    app.include_router(diagrams_router, prefix="/api")
    app.include_router(files_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(events_router, prefix="/api")
    app.include_router(watcher_router, prefix="/api")
    app.include_router(health_router, prefix="/api")
    app.include_router(llm_test_router, prefix="/api")
    app.include_router(graph_router, prefix="/api")

    logger.info("All routes registered")
    return app


# Create the app instance
logger.info("Starting Code Wiki backend...")
app = create_app()
logger.info("App created successfully")


# ---- CLI entry point ----
if __name__ == "__main__":
    import uvicorn
    logger.info("Launching uvicorn on 127.0.0.1:8788 with reload=True")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
