"""Analysis status endpoint."""

from fastapi import APIRouter

router = APIRouter()

# Global analysis state (updated by pipeline)
_analysis_state = {
    "status": "idle",
    "progress": 0,
    "current_step": "",
    "started_at": None,
    "finished_at": None,
    "total_modules": 0,
    "processed_modules": 0,
}


@router.get("/status")
async def get_status():
    """Get current analysis status."""
    return _analysis_state


def update_status(**kwargs):
    """Update the global analysis state (called by pipeline)."""
    _analysis_state.update(kwargs)
