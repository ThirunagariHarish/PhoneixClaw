"""Scheduler status endpoint — for dashboard health check."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v2/scheduler", tags=["scheduler"])


@router.get("/status")
async def scheduler_status():
    """Return current scheduler state and upcoming jobs."""
    try:
        from apps.api.src.services.scheduler import get_scheduler_status
        return get_scheduler_status()
    except Exception as exc:
        return {"running": False, "error": str(exc)[:200]}
