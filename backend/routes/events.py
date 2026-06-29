"""SSE event stream — pushes analysis progress and file changes to frontend."""

import asyncio
import json
import logging
import threading
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from routes.status import _analysis_state

logger = logging.getLogger("code-wiki.sse")

router = APIRouter()

# Queue for broadcasting events to all connected SSE clients
_listeners: list[asyncio.Queue] = []
_listeners_lock = threading.Lock()


def broadcast(event_type: str, data: dict):
    """Push an event to all connected SSE clients."""
    message = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    dead: list[asyncio.Queue] = []
    with _listeners_lock:
        for q in list(_listeners):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(f"SSE queue full, removing listener (listeners={len(_listeners)})")
                dead.append(q)
        # Clean up dead queues safely (inside lock)
        for q in dead:
            try:
                _listeners.remove(q)
            except ValueError:
                pass
    if _listeners:
        logger.debug(f"Broadcast '{event_type}' to {len(_listeners)} listener(s)")
    else:
        logger.warning(f"Broadcast '{event_type}' but no SSE listeners connected")


@router.get("/events")
async def event_stream():
    """SSE endpoint: clients connect here for real-time updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _listeners_lock:
        _listeners.append(queue)
    logger.info(f"SSE client connected (total listeners: {len(_listeners)})")

    async def generate():
        # Send current status immediately
        current = {
            "status": _analysis_state.get("status", "idle"),
            "progress": _analysis_state.get("progress", 0),
            "current_step": _analysis_state.get("current_step", ""),
        }
        yield f"event: progress\ndata: {json.dumps(current)}\n\n"

        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                    yield message
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            with _listeners_lock:
                try:
                    _listeners.remove(queue)
                except ValueError:
                    pass  # Already removed by broadcast cleanup
            logger.info(f"SSE client disconnected (remaining listeners: {len(_listeners)})")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
