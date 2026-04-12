"""Phoenix scheduler — embedded APScheduler running inside the API lifespan.

Jobs:
  - 09:00 ET weekdays  → morning_briefing (wake agents, pre-market research)
  - 16:30 ET weekdays  → supervisor_run (AutoResearch analyzes the day)
  - 16:45 ET weekdays  → eod_analysis (enrich trade_signals with outcomes)
  - 17:00 ET weekdays  → daily_summary (WhatsApp summary across all agents)
  - every 1 min        → live_agent_keepalive (re-spawn RUNNING/PAPER agents whose session ended)
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
    """Spawn the EOD analysis Claude agent at 16:45 ET."""
    try:
        from apps.api.src.services.agent_gateway import gateway
        logger.info("[scheduler] EOD analysis — spawning agent...")
        task_key = await gateway.create_eod_analysis_agent()
        logger.info("[scheduler] eod_analysis agent spawned: %s", task_key)
    except Exception:
        logger.exception("[scheduler] EOD analysis agent spawn failed")


async def _job_daily_summary() -> None:
    """Spawn the daily-summary Claude agent at 17:00 ET."""
    try:
        from apps.api.src.services.agent_gateway import gateway
        logger.info("[scheduler] Daily summary — spawning agent...")
        task_key = await gateway.create_daily_summary_agent()
        logger.info("[scheduler] daily_summary agent spawned: %s", task_key)
    except Exception:
        logger.exception("[scheduler] Daily summary agent spawn failed")


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
    """Spawn the trade-feedback Claude agent at 03:30 ET."""
    try:
        from apps.api.src.services.agent_gateway import gateway
        logger.info("[scheduler] Trade feedback — spawning agent...")
        task_key = await gateway.create_trade_feedback_agent()
        logger.info("[scheduler] trade_feedback agent spawned: %s", task_key)
    except Exception:
        logger.exception("[scheduler] Trade feedback agent spawn failed")


async def _job_consolidation_run() -> None:
    """Phase 3: Nightly consolidation pipeline ("Agent Sleep") at 18:15 ET.

    Checks that today is a trading day, then runs ConsolidationService for
    every agent with manifest->>'consolidation_enabled' = 'true'.
    """
    from datetime import date as _date

    from shared.config.market_holidays import is_trading_day

    if not is_trading_day(_date.today()):
        logger.info("[scheduler] consolidation_run skipped — not a trading day")
        return

    try:
        from shared.db.engine import get_session
        from apps.api.src.repositories.consolidation_repo import ConsolidationRepository
        from apps.api.src.services.consolidation_service import ConsolidationService

        async for session in get_session():
            repo = ConsolidationRepository(session)
            agent_ids = await repo.list_agents_due_for_consolidation()
            logger.info("[scheduler] consolidation_run: %d agents eligible", len(agent_ids))

            for agent_id in agent_ids:
                try:
                    run = await repo.create_run(agent_id=agent_id, run_type="nightly")
                    await session.commit()
                    svc = ConsolidationService(session)
                    completed = await svc.run_consolidation(
                        agent_id=agent_id, run_id=run.id, run_type="nightly"
                    )
                    logger.info(
                        "[scheduler] consolidation_run agent=%s status=%s patterns=%d",
                        agent_id,
                        completed.status,
                        completed.patterns_found,
                    )
                except Exception:
                    logger.exception("[scheduler] consolidation_run failed for agent=%s", agent_id)
            break
    except Exception:
        logger.exception("[scheduler] consolidation_run job failed")


# Live-agent keepalive: how many seconds after a session ends before we re-spawn.
# Default 60 s — enough to avoid a tight crash-loop, short enough to feel instant.
_KEEPALIVE_RESTART_DELAY_SECONDS = int(os.environ.get("AGENT_KEEPALIVE_DELAY_SECONDS", "60"))
# Set AGENT_KEEPALIVE_ENABLED=0 to disable entirely (e.g. overnight maintenance).
_KEEPALIVE_ENABLED = os.environ.get("AGENT_KEEPALIVE_ENABLED", "1") != "0"

_HEARTBEAT_STALE_MINUTES = int(os.environ.get("HEARTBEAT_STALE_MINUTES", "30"))


async def _job_live_agent_keepalive() -> None:
    """Keepalive: re-spawn live agents whose Claude session ended cleanly.

    Runs every minute. For each agent with status RUNNING or PAPER that has
    no active session (status in running/starting), and whose last session
    ended cleanly (status=completed) at least _KEEPALIVE_RESTART_DELAY_SECONDS
    ago, spawns a fresh Claude Code session via gateway.create_analyst().

    Skipped when:
    - AGENT_KEEPALIVE_ENABLED=0
    - Agent worker_status is ERROR/STARTING/RUNNING (redundant guard; _running_tasks
      check below is the authoritative in-flight test, but this avoids a DB roundtrip
      for agents the gateway already knows are active)
    - A task is already in-flight in _running_tasks
    - Agent has no prior analyst session (first start is always a deliberate user action)
    - The last session ended with error/interrupted (needs human review)
    - The last session ended less than _KEEPALIVE_RESTART_DELAY_SECONDS ago
    - Budget is exceeded (gateway.create_analyst returns BUDGET_EXCEEDED)
    """
    if not _KEEPALIVE_ENABLED:
        return

    try:
        from datetime import timedelta

        from sqlalchemy import select, func

        from shared.db.engine import get_session
        from shared.db.models.agent import Agent
        from shared.db.models.agent_session import AgentSession
        from apps.api.src.services.agent_gateway import gateway, _running_tasks

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=_KEEPALIVE_RESTART_DELAY_SECONDS)

        agents_to_restart: list[tuple] = []  # (agent_id, agent_name)

        async for db in get_session():
            # --- Step 1: candidates — RUNNING/PAPER agents not already active ---
            # worker_status exclusion is a fast pre-filter; the _running_tasks check
            # below is the authoritative in-flight guard (R-004: kept for efficiency,
            # not correctness — avoids extra queries for clearly-active agents).
            result = await db.execute(
                select(Agent).where(
                    Agent.status.in_(["RUNNING", "PAPER"]),
                    Agent.worker_status.notin_(["ERROR", "STARTING", "RUNNING"]),
                )
            )
            candidates = list(result.scalars().all())
            if not candidates:
                break

            candidate_ids = [a.id for a in candidates]

            # --- Step 2: batch fetch active sessions (R-002: single query) ---
            active_result = await db.execute(
                select(AgentSession.agent_id).where(
                    AgentSession.agent_id.in_(candidate_ids),
                    AgentSession.status.in_(["running", "starting"]),
                )
            )
            has_active_session: set = {row[0] for row in active_result.all()}

            # --- Step 3: batch fetch last analyst session per agent (R-002) ---
            # Subquery: max started_at per agent among analyst session types
            subq = (
                select(
                    AgentSession.agent_id,
                    func.max(AgentSession.started_at).label("max_started"),
                )
                .where(
                    AgentSession.agent_id.in_(candidate_ids),
                    AgentSession.agent_type.in_(["analyst", "live_trader"]),
                )
                .group_by(AgentSession.agent_id)
                .subquery()
            )
            last_sess_result = await db.execute(
                select(AgentSession).join(
                    subq,
                    (AgentSession.agent_id == subq.c.agent_id)
                    & (AgentSession.started_at == subq.c.max_started),
                )
            )
            last_sess_by_agent: dict = {
                sess.agent_id: sess for sess in last_sess_result.scalars().all()
            }

            # --- Step 4: evaluate each candidate ---
            for agent in candidates:
                agent_key = str(agent.id)

                # Skip if a task is already in flight (authoritative in-process check)
                if agent_key in _running_tasks and not _running_tasks[agent_key].done():
                    continue

                # Skip if DB shows an active session
                if agent.id in has_active_session:
                    continue

                last_sess = last_sess_by_agent.get(agent.id)

                # R-001: never restart agents with no prior session — first start
                # must be a deliberate user action (approve/resume), not keepalive.
                if last_sess is None:
                    continue

                # Never restart if the last session ended with an error — those need
                # human review (billing failure, OOM, etc.)
                if last_sess.status in ("error", "interrupted"):
                    continue

                # Enforce the restart delay to prevent tight crash-loops
                if last_sess.stopped_at:
                    stopped_at = last_sess.stopped_at
                    if stopped_at.tzinfo is None:
                        stopped_at = stopped_at.replace(tzinfo=timezone.utc)
                    if stopped_at > cutoff:
                        continue  # too soon

                agents_to_restart.append((agent.id, agent.name))

        for agent_id, agent_name in agents_to_restart:
            try:
                logger.info("[keepalive] Re-spawning completed session for agent %s (%s)",
                            agent_name, agent_id)
                result = await gateway.create_analyst(agent_id)
                if result and result.startswith("BUDGET_EXCEEDED"):
                    logger.warning("[keepalive] Budget exceeded for %s — skipping: %s",
                                   agent_name, result)
                elif result and result.startswith("NOT_ELIGIBLE"):
                    logger.warning("[keepalive] Agent %s not eligible — skipping: %s",
                                   agent_name, result)
                else:
                    logger.info("[keepalive] Session started for agent %s: session_row=%s",
                                agent_name, result)
            except Exception as exc:
                logger.warning("[keepalive] Failed to restart agent %s: %s", agent_name, exc)

    except Exception:
        logger.exception("[scheduler] Live agent keepalive job failed")


async def _job_heartbeat_check() -> None:
    """Mark stale agent sessions.

    Also refreshes the Discord ingestion daemon (restarts dead connectors,
    picks up newly-created connectors).
    """
    try:
        from datetime import timedelta

        from sqlalchemy import select

        from shared.db.engine import get_session
        from shared.db.models.agent_session import AgentSession

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_HEARTBEAT_STALE_MINUTES)
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
                s.error_message = f"No heartbeat for {_HEARTBEAT_STALE_MINUTES}+ minutes"
                s.stopped_at = datetime.now(timezone.utc)
            if stale:
                await session.commit()
                logger.warning("[scheduler] Marked %d stale sessions (cutoff=%dmin)",
                               len(stale), _HEARTBEAT_STALE_MINUTES)
                # Keepalive job will pick these up on its next tick and re-spawn them.

    except Exception:
        logger.exception("[scheduler] Heartbeat check failed")

    # Refresh ingestion daemon — restart dead Discord connections, add new connectors
    try:
        from apps.api.src.services.message_ingestion import refresh_ingestion
        status = await refresh_ingestion()
        dead_count = sum(1 for c in status.get("connectors", []) if not c.get("alive"))
        if dead_count:
            logger.warning("[scheduler] Ingestion refresh found %d dead connectors", dead_count)
    except Exception:
        logger.debug("[scheduler] Ingestion refresh skipped (non-fatal)")


def start_scheduler() -> "AsyncIOScheduler | None":
    """Start the APScheduler with all jobs. Idempotent."""
    global _scheduler

    if not APSCHEDULER_AVAILABLE:
        logger.warning("[scheduler] apscheduler not installed — skipping")
        return None

    if not _should_run_scheduler():
        logger.warning(
            "SCHEDULER DISABLED — not the leader. "
            "Set RUN_SCHEDULER=1 to force, or ensure WEB_CONCURRENCY=1."
        )
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

    # Every 5 min — heartbeat check (mark stale sessions)
    _scheduler.add_job(
        _job_heartbeat_check,
        trigger=IntervalTrigger(minutes=5),
        id="heartbeat_check",
        name="Heartbeat Check",
        replace_existing=True,
    )

    # Every 1 min — live agent keepalive (re-spawn completed sessions)
    _scheduler.add_job(
        _job_live_agent_keepalive,
        trigger=IntervalTrigger(minutes=1),
        id="live_agent_keepalive",
        name="Live Agent Keepalive",
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

    # 18:15 ET weekdays — nightly consolidation ("Agent Sleep")
    _scheduler.add_job(
        _job_consolidation_run,
        trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=15, timezone=_ET_TZ),
        id="consolidation_run",
        name="Nightly Consolidation (Agent Sleep)",
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
    job_names = ", ".join(j.name for j in jobs)
    logger.info(
        "SCHEDULER RUNNING: %d jobs registered — %s",
        len(jobs), job_names,
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
