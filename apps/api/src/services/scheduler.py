"""Phoenix scheduler — embedded APScheduler running inside the API lifespan.

Jobs:
  - 09:00 ET weekdays  → morning_briefing (wake agents, pre-market research)
  - 16:30 ET weekdays  → supervisor_run (AutoResearch analyzes the day)
  - 16:45 ET weekdays  → eod_analysis (enrich trade_signals with outcomes)
  - 17:00 ET weekdays  → daily_summary (WhatsApp summary across all agents)
  - every 5 min        → heartbeat_check (mark stale sessions)

Single-worker guard: only the worker with RUN_SCHEDULER=1 (or the first
worker that acquires the advisory lock) owns the scheduler.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    AsyncIOScheduler = None
    CronTrigger = None
    IntervalTrigger = None

logger = logging.getLogger(__name__)

_scheduler: "AsyncIOScheduler | None" = None
_ET_TZ = "America/New_York"


def _should_run_scheduler() -> bool:
    """Single-worker guard.

    Only start the scheduler if:
    - RUN_SCHEDULER env var is "1" (explicit opt-in)
    - OR we're not in a multi-worker deployment (default for uvicorn 1-worker)

    In multi-worker deployments you MUST set RUN_SCHEDULER=1 on exactly one
    worker (typically via a separate process or a leader-elect pattern).
    """
    explicit = os.environ.get("RUN_SCHEDULER", "").strip()
    if explicit == "1":
        return True
    if explicit == "0":
        return False
    # Default: run if uvicorn is configured with workers=1 (no WEB_CONCURRENCY set or =1)
    concurrency = os.environ.get("WEB_CONCURRENCY", "1")
    return concurrency == "1"


async def _job_morning_briefing() -> None:
    """Trigger the morning routine orchestrator."""
    try:
        from services.orchestrator.src.morning_routine import morning_routine
        logger.info("[scheduler] Morning briefing starting...")
        result = await morning_routine.execute()
        logger.info("[scheduler] Morning briefing done: %s agents woken, %s triggered, briefing_sent=%s",
                    result.get("agents_woken"), result.get("agents_triggered"),
                    result.get("briefing_sent"))
    except Exception:
        logger.exception("[scheduler] Morning briefing failed")


async def _job_supervisor_run() -> None:
    """Trigger the AutoResearch supervisor agent."""
    try:
        from apps.api.src.services.agent_gateway import gateway
        logger.info("[scheduler] Supervisor run starting...")
        session_id = await gateway.create_supervisor_agent()
        logger.info("[scheduler] Supervisor spawned: %s", session_id)
    except Exception:
        logger.exception("[scheduler] Supervisor run failed")


async def _job_eod_analysis() -> None:
    """Run EOD analysis: enrich trade_signals, compute missed-trade metrics."""
    try:
        from apps.api.src.routes.eod_analysis import run_eod_analysis
        logger.info("[scheduler] EOD analysis starting...")
        result = await run_eod_analysis()
        logger.info("[scheduler] EOD analysis done: %s", result)
    except Exception:
        logger.exception("[scheduler] EOD analysis failed")


async def _job_daily_summary() -> None:
    """Compile a daily WhatsApp summary across all agents."""
    try:
        from shared.db.engine import get_session
        from shared.db.models.agent import Agent
        from shared.db.models.agent_trade import AgentTrade
        from sqlalchemy import select, func, and_

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        async for session in get_session():
            # Count today's trades per agent
            result = await session.execute(
                select(
                    AgentTrade.agent_id,
                    func.count(AgentTrade.id).label("count"),
                    func.sum(AgentTrade.pnl_dollar).label("pnl"),
                )
                .where(AgentTrade.created_at >= today_start)
                .group_by(AgentTrade.agent_id)
            )
            rows = result.all()

            if not rows:
                logger.info("[scheduler] Daily summary: no trades today")
                return

            # Get agent names
            agent_ids = [r.agent_id for r in rows]
            agents_result = await session.execute(
                select(Agent).where(Agent.id.in_(agent_ids))
            )
            agents_by_id = {a.id: a for a in agents_result.scalars().all()}

            # Build summary
            lines = [f"Daily Summary — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}", ""]
            total_pnl = 0.0
            total_trades = 0
            for r in rows:
                agent = agents_by_id.get(r.agent_id)
                name = agent.name if agent else str(r.agent_id)[:8]
                pnl = float(r.pnl or 0)
                total_pnl += pnl
                total_trades += r.count
                lines.append(f"• {name}: {r.count} trades, ${pnl:+.2f}")
            lines.append("")
            lines.append(f"Total: {total_trades} trades, ${total_pnl:+.2f}")

            body = "\n".join(lines)

            # Dispatch notification
            try:
                from apps.api.src.services.notification_dispatcher import notification_dispatcher
                await notification_dispatcher.dispatch(
                    event_type="info",
                    agent_id=None,
                    title="Phoenix Daily Summary",
                    body=body,
                    channels=["whatsapp", "ws", "db"],
                )
                logger.info("[scheduler] Daily summary dispatched")
            except Exception:
                logger.exception("[scheduler] Failed to dispatch daily summary")
    except Exception:
        logger.exception("[scheduler] Daily summary failed")


async def _job_heartbeat_check() -> None:
    """Mark stale agent sessions (last_heartbeat > 15 min) as error."""
    try:
        from datetime import timedelta
        from shared.db.engine import get_session
        from shared.db.models.agent_session import AgentSession
        from sqlalchemy import select, update

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        async for session in get_session():
            result = await session.execute(
                select(AgentSession).where(
                    AgentSession.status == "running",
                    AgentSession.last_heartbeat.isnot(None),
                    AgentSession.last_heartbeat < cutoff,
                )
            )
            stale = list(result.scalars().all())
            for s in stale:
                s.status = "stale"
                s.error_message = "No heartbeat for 15+ minutes"
                s.stopped_at = datetime.now(timezone.utc)
            if stale:
                await session.commit()
                logger.warning("[scheduler] Marked %d stale sessions", len(stale))
    except Exception:
        logger.exception("[scheduler] Heartbeat check failed")


def start_scheduler() -> "AsyncIOScheduler | None":
    """Start the APScheduler with all jobs. Idempotent."""
    global _scheduler

    if not APSCHEDULER_AVAILABLE:
        logger.warning("[scheduler] apscheduler not installed — skipping")
        return None

    if not _should_run_scheduler():
        logger.info("[scheduler] Not starting (RUN_SCHEDULER != '1' and WEB_CONCURRENCY > 1)")
        return None

    if _scheduler is not None and _scheduler.running:
        logger.info("[scheduler] Already running")
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone=_ET_TZ)

    # 9:00 AM ET weekdays — morning briefing (30 min before market open)
    _scheduler.add_job(
        _job_morning_briefing,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=_ET_TZ),
        id="morning_briefing",
        name="Morning Briefing",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 16:30 ET weekdays — supervisor (market close)
    _scheduler.add_job(
        _job_supervisor_run,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=_ET_TZ),
        id="supervisor_run",
        name="AutoResearch Supervisor",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 16:45 ET weekdays — EOD analysis (enrich trade_signals)
    _scheduler.add_job(
        _job_eod_analysis,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=45, timezone=_ET_TZ),
        id="eod_analysis",
        name="EOD Analysis",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 17:00 ET weekdays — daily summary
    _scheduler.add_job(
        _job_daily_summary,
        trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=0, timezone=_ET_TZ),
        id="daily_summary",
        name="Daily Summary",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Every 5 min — heartbeat check
    _scheduler.add_job(
        _job_heartbeat_check,
        trigger=IntervalTrigger(minutes=5),
        id="heartbeat_check",
        name="Heartbeat Check",
        replace_existing=True,
    )

    _scheduler.start()

    jobs = _scheduler.get_jobs()
    logger.info(
        "[scheduler] Started with %d jobs: %s",
        len(jobs),
        ", ".join(f"{j.id}@{j.next_run_time}" for j in jobs),
    )
    return _scheduler


async def stop_scheduler() -> None:
    """Stop the scheduler on app shutdown."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] Stopped")
    _scheduler = None


def get_scheduler_status() -> dict:
    """Return scheduler status for health checks / dashboard."""
    if _scheduler is None:
        return {"running": False, "reason": "not_started"}
    if not _scheduler.running:
        return {"running": False, "reason": "stopped"}
    jobs = _scheduler.get_jobs()
    return {
        "running": True,
        "jobs": [
            {
                "id": j.id,
                "name": j.name,
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
            }
            for j in jobs
        ],
    }
