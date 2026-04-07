"""Morning routine API — manual trigger and status endpoints.

Triggered by the scheduler cron at 9:00 AM ET or manually from the dashboard.

Modes:
    - agent (default): spawn the first-class morning-briefing-agent
    - python: run the legacy in-process orchestrator (debug / safety net)
"""
import logging
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/agents", tags=["morning-routine"])


@router.post("/morning-briefing")
async def trigger_morning_briefing(
    mode: str = Query("agent", pattern="^(agent|python)$"),
):
    """Trigger the morning routine.

    Modes:
      - agent (default): spawn the first-class morning_briefing agent template
        via gateway.create_morning_briefing_agent(). Returns the task key.
      - python: run the legacy Python orchestrator in-process. Returns the full
        result dict (agents_eligible / agents_woken / agents_skipped / ...).
    """
    if mode == "agent":
        try:
            from apps.api.src.services.agent_gateway import gateway
            task_key = await gateway.create_morning_briefing_agent()
            return {
                "status": "spawned",
                "mode": "agent",
                "task_key": task_key,
                "detail": "Morning briefing agent running. Watch briefing_history for output.",
            }
        except Exception as exc:
            logger.exception("Morning briefing agent spawn failed")
            return {"status": "error", "mode": "agent", "error": str(exc)[:500]}

    # python fallback — defensive import so a PYTHONPATH misconfig in prod
    # returns a clear error string instead of a stack trace
    try:
        try:
            from services.orchestrator.src.morning_routine import morning_routine
        except ImportError as imp_exc:
            # Fallback for when PYTHONPATH doesn't include the repo root
            import sys
            from pathlib import Path
            repo_root = Path(__file__).resolve().parents[4]
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
                logger.warning("[morning] injected repo_root=%s into sys.path", repo_root)
            try:
                from services.orchestrator.src.morning_routine import morning_routine
            except ImportError:
                logger.exception("[morning] import still failing after sys.path fix")
                return {
                    "status": "error", "mode": "python",
                    "error": f"import_failed: {imp_exc}",
                    "started_at": None, "agents_eligible": 0,
                    "agents_woken": 0, "agents_triggered": 0,
                    "briefing_sent": False,
                }

        result = await morning_routine.execute()
        result["mode"] = "python"
        return result
    except Exception as exc:
        logger.exception("Morning routine failed")
        return {
            "status": "error", "mode": "python", "error": str(exc)[:500],
            "started_at": None, "agents_eligible": 0,
            "agents_woken": 0, "agents_triggered": 0, "briefing_sent": False,
        }
