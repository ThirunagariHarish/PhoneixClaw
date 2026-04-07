"""Morning Briefing API — manual trigger.

The scheduler cron at 9:00 AM ET calls gateway.create_morning_briefing_agent()
directly. This route is the same thing but exposed for the dashboard "Run Now"
button. Always spawns the first-class Claude Code agent — no Python fallback.
"""
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/agents", tags=["morning-routine"])


@router.post("/morning-briefing")
async def trigger_morning_briefing():
    """Spawn the morning-briefing Claude agent.

    Returns immediately with the spawned task key. Actual briefing output
    lands in `briefing_history` a few minutes later — the UI polls that
    table to show the latest result.
    """
    try:
        from apps.api.src.services.agent_gateway import gateway
        task_key = await gateway.create_morning_briefing_agent()
        return {
            "status": "spawned",
            "task_key": task_key,
            "detail": (
                "Morning briefing agent running. "
                "Results will appear in Briefing History in 2-3 minutes."
            ),
        }
    except Exception as exc:
        logger.exception("Morning briefing agent spawn failed")
        return {"status": "error", "error": str(exc)[:500]}
