"""Scheduler + concurrency status endpoint — for dashboard health check."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v2/scheduler", tags=["scheduler"])


@router.get("/status")
async def scheduler_status():
    """Return current scheduler state and upcoming jobs + agent concurrency."""
    out = {}
    try:
        from apps.api.src.services.scheduler import get_scheduler_status
        out["scheduler"] = get_scheduler_status()
    except Exception as exc:
        out["scheduler"] = {"running": False, "error": str(exc)[:200]}

    try:
        from apps.api.src.services.agent_gateway import get_concurrency_status
        out["concurrency"] = get_concurrency_status()
    except Exception as exc:
        out["concurrency"] = {"error": str(exc)[:200]}

    try:
        from apps.api.src.services.message_ingestion import get_ingestion_status
        out["ingestion"] = get_ingestion_status()
    except Exception as exc:
        out["ingestion"] = {"error": str(exc)[:200]}

    if isinstance(out["scheduler"], dict):
        out["running"] = out["scheduler"].get("running", False)
        if "jobs" in out["scheduler"]:
            out["jobs"] = out["scheduler"]["jobs"]
    return out


@router.post("/ingestion/refresh")
async def refresh_ingestion_endpoint():
    """Restart dead ingestion tasks and pick up newly-created connectors."""
    try:
        from apps.api.src.services.message_ingestion import refresh_ingestion
        result = await refresh_ingestion()
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}
