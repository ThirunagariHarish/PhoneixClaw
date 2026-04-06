"""Morning routine API — manual trigger and status endpoints.

Triggered by Claude Code cron at 9:00 AM ET (configurable) or manually
from the dashboard.
"""
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/agents", tags=["morning-routine"])


@router.post("/morning-briefing")
async def trigger_morning_briefing():
    """Trigger the morning routine across all running agents.

    This is the endpoint Claude Code cron calls. Also callable manually
    from the dashboard for testing.
    """
    try:
        from services.orchestrator.src.morning_routine import morning_routine
        result = await morning_routine.execute()
        return result
    except Exception as exc:
        logger.exception("Morning routine failed")
        return {"status": "error", "error": str(exc)[:500]}
