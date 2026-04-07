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

# Phase H9: Postgres advisory lock ID. Any number works as long as it's the
# same across all workers in the cluster. We use a stable hash of the string
# 'phoenix:scheduler:leader' converted to a 64-bit int.
SCHEDULER_LOCK_KEY = 0x70686F656E697835  # "phoenix5" in hex — arbitrary stable
_lock_engine = None  # Engine that holds the advisory lock connection alive
_lock_connection = None


def _should_run_scheduler() -> bool:
    """Single-worker guard.

    Phase H9: Use a Postgres advisory lock for true leader election in
    multi-worker deployments. Whichever worker successfully acquires the
    advisory lock becomes the scheduler leader; all others skip.

    Falls back to env var heuristic if the DB is not yet ready.
    """
    explicit = os.environ.get("RUN_SCHEDULER", "").strip()
    if explicit == "0":
        return False
    if explicit == "1":
        return True
    # Default: try to acquire the advisory lock
    return _try_acquire_scheduler_lock()


def _try_acquire_scheduler_lock() -> bool:
    """Try to acquire a session-scoped Postgres advisory lock.

    Returns True if this worker is now the scheduler leader.
    The lock is held until _release_scheduler_lock() is called or the
    connection dies (advisory locks are session-scoped).
    """
    global _lock_engine, _lock_connection
    try:
        from sqlalchemy import create_engine, text
        from shared.db.engine import get_database_url

        # Use a SYNC engine for the lock connection — we want long-lived,
        # not pooled (advisory locks are session-scoped, so we hold one
        # connection forever)
        url = get_database_url().replace("postgresql+asyncpg://", "postgresql://")
        _lock_engine = create_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=True)
        _lock_connection = _lock_engine.connect()

        result = _lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": SCHEDULER_LOCK_KEY},
        ).scalar()

        if result:
            logger.info("[scheduler] Acquired advisory lock — this worker is the leader")
            return True

        logger.info("[scheduler] Another worker holds the advisory lock — skipping")
        try:
            _lock_connection.close()
        except Exception:
            pass
        _lock_connection = None
        try:
            _lock_engine.dispose()
        except Exception:
            pass
        _lock_engine = None
        return False
    except Exception as exc:
        logger.warning("[scheduler] Could not acquire advisory lock (%s) — "
                       "falling back to env var", exc)
        # Fallback to single-worker heuristic
        concurrency = os.environ.get("WEB_CONCURRENCY", "1")
        return concurrency == "1"


def _release_scheduler_lock() -> None:
    """Release the advisory lock on shutdown."""
    global _lock_engine, _lock_connection
    if _lock_connection is not None:
        try:
            from sqlalchemy import text
            _lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": SCHEDULER_LOCK_KEY},
            )
            _lock_connection.commit()
            _lock_connection.close()
            logger.info("[scheduler] Released advisory lock")
        except Exception as exc:
            logger.warning("[scheduler] Failed to release lock cleanly: %s", exc)
        _lock_connection = None
    if _lock_engine is not None:
        try:
            _lock_engine.dispose()
        except Exception:
            pass
        _lock_engine = None


async def _job_morning_briefing() -> None:
    """Spawn the morning-briefing agent at 9:00 ET.

    First-class Claude Code agent only. No Python fallback — if the spawn
    fails, the failure is loud and the user gets notified via the dashboard.
    """
    try:
        from apps.api.src.services.agent_gateway import gateway
        logger.info("[scheduler] Morning briefing — spawning agent...")
        task_key = await gateway.create_morning_briefing_agent()
        logger.info("[scheduler] morning_briefing_agent spawned: %s", task_key)
    except Exception:
        logger.exception("[scheduler] Morning briefing agent spawn failed")


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


async def _job_nightly_retention() -> None:
    """Phase H4: Delete old log/notification rows + clean data/ directory.

    Runs at 3:00 AM ET. Keeps the system from growing forever.
    """
    try:
        from datetime import timedelta
        from shared.db.engine import get_session
        from sqlalchemy import text

        results = {}
        retention_rules = [
            ("system_logs", 30),
            ("agent_logs", 30),
            ("agent_messages", 60),
            ("notifications", 90),
            ("trade_signals", 180),
        ]

        async for session in get_session():
            for table, days in retention_rules:
                try:
                    # Use raw SQL for speed; idempotent DELETE
                    sql = f"""
                        DELETE FROM {table}
                        WHERE created_at < NOW() - INTERVAL ':days days'
                    """.replace(":days", str(days))
                    # Special case: only delete READ notifications
                    if table == "notifications":
                        sql = f"""
                            DELETE FROM {table}
                            WHERE created_at < NOW() - INTERVAL '{days} days'
                              AND read = TRUE
                        """
                    result = await session.execute(text(sql))
                    deleted = getattr(result, "rowcount", 0) or 0
                    results[table] = deleted
                except Exception as exc:
                    logger.warning("[scheduler] retention %s failed: %s", table, exc)
                    results[table] = f"error: {str(exc)[:100]}"
            await session.commit()

        logger.info("[scheduler] Nightly retention DB rows deleted: %s", results)

        # Clean data/ directory
        try:
            from scripts.cleanup_data_dir import run_cleanup
            data_dir = os.environ.get("PHOENIX_DATA_DIR", "/app/data")
            cleanup_summary = await run_cleanup(data_dir, dry_run=False)
            logger.info("[scheduler] Data dir cleanup: %s MB freed",
                        cleanup_summary.get("bytes_freed_mb", 0))
        except Exception as exc:
            logger.exception("[scheduler] Data dir cleanup failed: %s", exc)

    except Exception:
        logger.exception("[scheduler] Nightly retention failed")


async def _job_agent_cron_fire(cron_id: str, agent_id: str, action_type: str,
                                action_payload: dict) -> None:
    """P11: fires a single per-agent cron row — publishes to the trigger bus."""
    try:
        from shared.triggers import get_bus, Trigger, TriggerType
        import uuid as _uuid

        await get_bus().publish(Trigger(
            agent_id=agent_id,
            type=TriggerType.CRON_FIRE,
            payload={"cron_id": cron_id, "action_type": action_type,
                     "action_payload": action_payload or {}},
        ))

        # Bump run metadata in DB
        try:
            from sqlalchemy import text
            from shared.db.engine import get_session
            async for sess in get_session():
                await sess.execute(
                    text("UPDATE agent_crons SET last_run_at = NOW(), "
                         "run_count = run_count + 1 WHERE id = :id"),
                    {"id": cron_id},
                )
                await sess.commit()
                break
        except Exception:
            pass
    except Exception:
        logger.exception("[scheduler] agent cron fire failed: %s", cron_id)


def register_agent_cron(cron_id: str, agent_id: str, cron_expression: str,
                         action_type: str = "prompt",
                         action_payload: dict | None = None) -> None:
    """Add or replace a per-agent cron in the live APScheduler."""
    if _scheduler is None or not APSCHEDULER_AVAILABLE:
        return
    try:
        _scheduler.add_job(
            _job_agent_cron_fire,
            trigger=CronTrigger.from_crontab(cron_expression, timezone=_ET_TZ),
            id=f"agent_cron_{cron_id}",
            name=f"Agent Cron {cron_id[:8]}",
            replace_existing=True,
            args=[cron_id, agent_id, action_type, action_payload or {}],
            misfire_grace_time=300,
        )
        logger.info("[scheduler] registered agent cron %s (%s) -> %s",
                    cron_id, agent_id, cron_expression)
    except Exception as exc:
        logger.warning("[scheduler] cron register failed %s: %s", cron_id, exc)


def unregister_agent_cron(cron_id: str) -> None:
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(f"agent_cron_{cron_id}")
    except Exception:
        pass


async def _load_agent_crons() -> None:
    """Load all enabled agent_crons rows and register them."""
    try:
        from sqlalchemy import text
        from shared.db.engine import get_session
        async for sess in get_session():
            res = await sess.execute(
                text("SELECT id, agent_id, cron_expression, action_type, "
                     "action_payload FROM agent_crons WHERE enabled = TRUE")
            )
            rows = res.all()
            for r in rows:
                register_agent_cron(
                    cron_id=r[0], agent_id=str(r[1]), cron_expression=r[2],
                    action_type=r[3] or "prompt", action_payload=r[4] or {},
                )
            logger.info("[scheduler] loaded %d agent crons", len(rows))
            break
    except Exception as exc:
        logger.debug("[scheduler] agent_crons load skipped: %s", exc)


async def _job_trade_feedback() -> None:
    """T11: Nightly bias-correction feedback loop."""
    try:
        from apps.api.src.services.trade_outcome_feedback import run_feedback_job
        logger.info("[scheduler] Trade outcome feedback starting...")
        result = await run_feedback_job()
        logger.info("[scheduler] Trade feedback done: %s", result)
    except Exception:
        logger.exception("[scheduler] Trade feedback failed")


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

    # 3:00 AM ET daily — retention cleanup (logs + data dir)
    _scheduler.add_job(
        _job_nightly_retention,
        trigger=CronTrigger(hour=3, minute=0, timezone=_ET_TZ),
        id="nightly_retention",
        name="Nightly Retention Cleanup",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 3:30 AM ET daily — T11 trade-outcome bias correction
    _scheduler.add_job(
        _job_trade_feedback,
        trigger=CronTrigger(hour=3, minute=30, timezone=_ET_TZ),
        id="trade_feedback",
        name="Trade Outcome Feedback (T11)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()

    # P11: load per-agent crons from DB
    try:
        import asyncio as _asyncio
        _asyncio.get_event_loop().create_task(_load_agent_crons())
    except Exception as exc:
        logger.debug("[scheduler] agent_crons scheduling skipped: %s", exc)

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
    _release_scheduler_lock()


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
