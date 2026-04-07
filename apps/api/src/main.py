"""
Phoenix v2 Backend API — FastAPI application entrypoint.

M1.1: Minimal app with health endpoint. M1.3: Auth routes and JWT middleware.
Reference: ImplementationPlan.md Section 2, Section 5 M1.1, M1.3.
"""

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

# Load .env early so os.environ is populated for all SDK checks (e.g. ANTHROPIC_API_KEY).
# This runs before any service module is imported, ensuring _can_use_claude_sdk() sees the key.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
except ImportError:
    pass

# Belt-and-braces PYTHONPATH fix: make sure the repo root is importable so
# `from services.orchestrator...` works even if gunicorn was launched without
# PYTHONPATH=/app. Without this, the API returns "No module named 'services'"
# at runtime when routes try to import sibling packages.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.src.config import settings
from apps.api.src.middleware.auth import JWTAuthMiddleware
from apps.api.src.middleware.error_handler import ErrorHandlerMiddleware
from apps.api.src.middleware.rate_limit import RateLimitMiddleware
from apps.api.src.middleware.logging import LoggingMiddleware
from apps.api.src.middleware.idempotency import IdempotencyMiddleware, set_shutting_down
from apps.api.src.routes import auth as auth_routes
from apps.api.src.routes import connectors as connector_routes
from apps.api.src.routes import trades as trades_routes
from apps.api.src.routes import positions as positions_routes
from apps.api.src.routes import agents as agents_routes
from apps.api.src.routes import execution as execution_routes
from apps.api.src.routes import skills as skills_routes
from apps.api.src.routes import backtests as backtests_routes
from apps.api.src.routes import strategies as strategies_routes
from apps.api.src.routes import monitoring as monitoring_routes
from apps.api.src.routes import dev_agent as dev_agent_routes
from apps.api.src.routes import tasks as tasks_routes
from apps.api.src.routes import automations as automations_routes
from apps.api.src.routes import admin as admin_routes
from apps.api.src.routes import performance as performance_routes
from apps.api.src.routes import market as market_routes
from apps.api.src.routes import ws as ws_routes
from apps.api.src.routes import agent_learning as agent_learning_routes
from apps.api.src.routes import daily_signals as daily_signals_routes
from apps.api.src.routes import onchain_flow as onchain_flow_routes
from apps.api.src.routes import macro_pulse as macro_pulse_routes
from apps.api.src.routes import zero_dte as zero_dte_routes
from apps.api.src.routes import narrative_sentiment as narrative_sentiment_routes
from apps.api.src.routes import risk_compliance as risk_compliance_routes
from apps.api.src.routes import agent_messages as agent_messages_routes
from apps.api.src.routes import chat as chat_routes
from apps.api.src.routes import notifications as notifications_routes
from apps.api.src.routes import error_logs as error_logs_routes
from apps.api.src.routes import ai_expand as ai_expand_routes
from apps.api.src.routes import token_usage as token_usage_routes
from apps.api.src.routes import system_logs as system_logs_routes
from apps.api.src.routes import morning_routine as morning_routine_routes
from apps.api.src.routes import whatsapp_webhook as whatsapp_webhook_routes
from apps.api.src.routes import scheduler_status as scheduler_status_routes
from apps.api.src.routes import eod_analysis as eod_analysis_routes
from apps.api.src.routes import trade_signals as trade_signals_routes
from apps.api.src.routes import budget as budget_routes
from apps.api.src.routes import agents_sprint as agents_sprint_routes
from apps.api.src.routes import agent_terminal as agent_terminal_routes
from apps.api.src.routes import briefing_history as briefing_history_routes
from apps.api.src.routes import claude_sdk_check as claude_sdk_check_routes
from apps.api.src.routes import polymarket as polymarket_routes

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")


async def _ensure_prod_schema() -> None:
    """Self-heal schema drift at API startup.

    Every statement is idempotent and runs in its OWN short transaction so a
    partial failure doesn't roll back the others. Logs every step loudly so
    production deploys can see what happened.

    This is the belt-and-braces safety net for cases where alembic and
    init_db.py both failed to apply migrations in production.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    try:
        from sqlalchemy import text
        from shared.db.engine import get_engine
    except Exception as exc:
        _log.warning("[schema_heal] import failed: %s", exc)
        return

    # Each statement gets its own transaction so individual failures don't cascade.
    statements = [
        ("agents.last_activity_at",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "last_activity_at" TIMESTAMPTZ'),
        ("agents.runtime_status",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "runtime_status" VARCHAR(16)'),
        ("agents.daily_token_budget_usd",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "daily_token_budget_usd" DOUBLE PRECISION'),
        ("agents.monthly_token_budget_usd",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "monthly_token_budget_usd" DOUBLE PRECISION'),
        ("agents.tokens_used_today_usd",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "tokens_used_today_usd" DOUBLE PRECISION DEFAULT 0'),
        ("agents.tokens_used_month_usd",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "tokens_used_month_usd" DOUBLE PRECISION DEFAULT 0'),
        ("agents.budget_reset_at",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "budget_reset_at" TIMESTAMPTZ'),
        ("agents.auto_paused_reason",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "auto_paused_reason" VARCHAR(100)'),
        # Columns added in migrations 014-09b0dd (not covered by earlier _ensure stmts)
        ("agents.source",
         "ALTER TABLE \"agents\" ADD COLUMN IF NOT EXISTS \"source\" VARCHAR(50) NOT NULL DEFAULT 'manual'"),
        ("agents.channel_name",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "channel_name" VARCHAR(100)'),
        ("agents.analyst_name",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "analyst_name" VARCHAR(100)'),
        ("agents.model_type",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "model_type" VARCHAR(50)'),
        ("agents.model_accuracy",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "model_accuracy" DOUBLE PRECISION'),
        ("agents.daily_pnl",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "daily_pnl" DOUBLE PRECISION NOT NULL DEFAULT 0'),
        ("agents.total_pnl",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "total_pnl" DOUBLE PRECISION NOT NULL DEFAULT 0'),
        ("agents.total_trades",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "total_trades" INTEGER NOT NULL DEFAULT 0'),
        ("agents.win_rate",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "win_rate" DOUBLE PRECISION NOT NULL DEFAULT 0'),
        ("agents.last_signal_at",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "last_signal_at" TIMESTAMPTZ'),
        ("agents.last_trade_at",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "last_trade_at" TIMESTAMPTZ'),
        ("agents.manifest",
         "ALTER TABLE \"agents\" ADD COLUMN IF NOT EXISTS \"manifest\" JSONB NOT NULL DEFAULT '{}'"),
        ("agents.current_mode",
         "ALTER TABLE \"agents\" ADD COLUMN IF NOT EXISTS \"current_mode\" VARCHAR(30) NOT NULL DEFAULT 'conservative'"),
        ("agents.rules_version",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "rules_version" INTEGER NOT NULL DEFAULT 1'),
        ("agents.error_message",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "error_message" TEXT'),
        ("agents.pending_improvements",
         "ALTER TABLE \"agents\" ADD COLUMN IF NOT EXISTS \"pending_improvements\" JSONB NOT NULL DEFAULT '{}'"),
        ("agents.last_research_at",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "last_research_at" TIMESTAMPTZ'),
        ("agents.phoenix_api_key",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "phoenix_api_key" VARCHAR(200)'),
        ("agents.worker_container_id",
         'ALTER TABLE "agents" ADD COLUMN IF NOT EXISTS "worker_container_id" VARCHAR(100)'),
        ("agents.worker_status",
         "ALTER TABLE \"agents\" ADD COLUMN IF NOT EXISTS \"worker_status\" VARCHAR(30) NOT NULL DEFAULT 'STOPPED'"),
        ("table agent_logs", """
            CREATE TABLE IF NOT EXISTS agent_logs (
                id BIGSERIAL PRIMARY KEY,
                agent_id VARCHAR(64) NOT NULL,
                level VARCHAR(16) NOT NULL DEFAULT 'info',
                source VARCHAR(64),
                message TEXT NOT NULL,
                context JSON,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """),
        ("index ix_agent_logs_agent_time",
         "CREATE INDEX IF NOT EXISTS ix_agent_logs_agent_time ON agent_logs (agent_id, created_at)"),
        ("table agent_crons", """
            CREATE TABLE IF NOT EXISTS agent_crons (
                id VARCHAR(64) PRIMARY KEY,
                agent_id VARCHAR(64) NOT NULL,
                name VARCHAR(128) NOT NULL,
                cron_expression VARCHAR(64) NOT NULL,
                action_type VARCHAR(64) NOT NULL DEFAULT 'prompt',
                action_payload JSON,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                last_run_at TIMESTAMPTZ,
                next_run_at TIMESTAMPTZ,
                run_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """),
        ("table briefing_history", """
            CREATE TABLE IF NOT EXISTS briefing_history (
                id BIGSERIAL PRIMARY KEY,
                kind VARCHAR(32) NOT NULL DEFAULT 'morning',
                agent_session_id UUID,
                title VARCHAR(200) NOT NULL,
                body TEXT NOT NULL,
                data JSONB,
                agents_woken INTEGER NOT NULL DEFAULT 0,
                dispatched_to TEXT[],
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """),
        ("index ix_briefing_history_kind_time",
         "CREATE INDEX IF NOT EXISTS ix_briefing_history_kind_time ON briefing_history (kind, created_at)"),
        ("table order_attempts", """
            CREATE TABLE IF NOT EXISTS order_attempts (
                id BIGSERIAL PRIMARY KEY,
                agent_id VARCHAR(64),
                intent_id VARCHAR(64),
                symbol VARCHAR(16),
                side VARCHAR(8),
                rung INTEGER NOT NULL,
                limit_price DOUBLE PRECISION,
                status VARCHAR(32) NOT NULL,
                reason VARCHAR(64),
                fill_price DOUBLE PRECISION,
                attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """),
        ("table trade_outcomes_feedback", """
            CREATE TABLE IF NOT EXISTS trade_outcomes_feedback (
                id BIGSERIAL PRIMARY KEY,
                agent_id VARCHAR(64) NOT NULL,
                trade_id VARCHAR(64),
                symbol VARCHAR(16),
                predicted_sl_mult DOUBLE PRECISION,
                actual_mae_atr DOUBLE PRECISION,
                predicted_tp_mult DOUBLE PRECISION,
                actual_mfe_atr DOUBLE PRECISION,
                predicted_slip_bps DOUBLE PRECISION,
                actual_slip_bps DOUBLE PRECISION,
                closed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """),
    ]

    engine = get_engine()
    ok = 0
    errs = 0
    for label, sql in statements:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
            _log.info("[schema_heal] OK %s", label)
            ok += 1
        except Exception as exc:
            _log.warning("[schema_heal] FAILED %s: %s", label, str(exc)[:200])
            errs += 1
    _log.info("[schema_heal] done — %d ok, %d errors", ok, errs)


async def _heal_stuck_backtests(log=None) -> None:
    """Reset backtests/agents that are stuck in RUNNING/BACKTESTING.

    On API restart the in-memory _running_tasks dict is empty, but the DB may
    still record backtests as RUNNING from the previous process.  After the
    gateway timeout window (1800 s by default) + a 60 s grace period any
    RUNNING backtest is guaranteed dead — mark it ERROR and flip the parent
    agent status back to CREATED so the user can retry.
    """
    import logging as _logging
    _log = log or _logging.getLogger(__name__)

    try:
        from datetime import timedelta
        from sqlalchemy import text, update
        from shared.db.engine import get_engine
        from shared.db.models.agent import Agent, AgentBacktest
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        timeout_seconds = int(os.getenv("BACKTEST_QUERY_TIMEOUT_SECONDS", "1800")) + 60
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)

        engine = get_engine()
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as db:
            # Find stuck backtests
            result = await db.execute(
                text("""
                    SELECT id, agent_id, created_at
                    FROM agent_backtests
                    WHERE status = 'RUNNING'
                      AND created_at < :cutoff
                """),
                {"cutoff": cutoff},
            )
            stuck = result.fetchall()
            if not stuck:
                _log.info("[backtest_heal] no stuck backtests found")
                return

            _log.warning("[backtest_heal] found %d stuck backtest(s) — resetting", len(stuck))
            stuck_agent_ids = set()
            for row in stuck:
                bt_id, agent_id_str, created_at = row
                await db.execute(
                    text("""
                        UPDATE agent_backtests
                        SET status = 'ERROR',
                            current_step = 'timeout',
                            completed_at = NOW()
                        WHERE id = :bt_id
                    """),
                    {"bt_id": bt_id},
                )
                stuck_agent_ids.add(str(agent_id_str))
                _log.warning(
                    "[backtest_heal] reset backtest %s (agent %s, created %s)",
                    bt_id, agent_id_str, created_at,
                )

            # Flip parent agents back to CREATED so the user can retry
            for agent_id_str in stuck_agent_ids:
                await db.execute(
                    text("""
                        UPDATE agents
                        SET status = 'CREATED',
                            error_message = 'Backtest timed out — please retry'
                        WHERE id::text = :agent_id
                          AND status = 'BACKTESTING'
                    """),
                    {"agent_id": agent_id_str},
                )

            await db.commit()
            _log.info("[backtest_heal] done — reset %d stuck backtest(s)", len(stuck))
    except Exception as exc:
        _log.warning("[backtest_heal] non-fatal error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    import logging as _logging
    _log = _logging.getLogger(__name__)

    # Environment sanity check — log Claude SDK preconditions on every boot
    _key = os.environ.get("ANTHROPIC_API_KEY", "")
    if _key:
        _log.info("[startup] ANTHROPIC_API_KEY set (len=%d)", len(_key))
    else:
        _log.warning("[startup] ANTHROPIC_API_KEY not set — Claude SDK will fail")

    # Security guard: refuse to start with the default JWT secret
    _jwt_secret = os.environ.get("JWT_SECRET_KEY", "")
    _unsafe_defaults = {"change-me-in-production", "changeme", "secret", ""}
    if _jwt_secret.lower() in _unsafe_defaults:
        _log.critical(
            "[startup] UNSAFE JWT_SECRET_KEY detected ('%s'). "
            "Set a strong random secret in .env before running in production.",
            _jwt_secret[:20] or "(empty)",
        )
    else:
        _log.info("[startup] JWT_SECRET_KEY configured (len=%d)", len(_jwt_secret))

    _log.info("[startup] HOME=%s", os.environ.get("HOME", "(unset)"))
    import shutil as _shutil
    _claude_bin = _shutil.which("claude")
    _log.info("[startup] claude CLI: %s", _claude_bin or "(NOT FOUND)")

    # CRITICAL: self-heal any schema drift from failed migrations BEFORE
    # scheduler/ingestion start (they both query tables that may be missing).
    try:
        await _ensure_prod_schema()
    except Exception as exc:
        _log.exception("[schema_heal] top-level crash: %s", exc)

    # Heal agents/backtests stuck in RUNNING/BACKTESTING state from a previous
    # API crash or container restart.  Any backtest still RUNNING after the
    # gateway timeout window (default 1800 s + 60 s grace) is dead — mark it
    # ERROR so the UI shows a meaningful status instead of spinning forever.
    try:
        await _heal_stuck_backtests(_log)
    except Exception as exc:
        _log.exception("[backtest_heal] failed: %s", exc)

    # Start scheduler (morning briefing, supervisor, EOD analysis, heartbeat)
    stop_scheduler_fn = None
    try:
        from apps.api.src.services.scheduler import start_scheduler, stop_scheduler
        start_scheduler()
        stop_scheduler_fn = stop_scheduler
    except Exception as exc:
        _log.exception("Failed to start scheduler: %s", exc)

    # Start message ingestion daemon (Discord listener → channel_messages + Redis)
    stop_ingestion_fn = None
    try:
        from apps.api.src.services.message_ingestion import start_ingestion, stop_ingestion
        await start_ingestion()
        stop_ingestion_fn = stop_ingestion
    except Exception as exc:
        _log.exception("Failed to start message ingestion: %s", exc)

    # Phase H3: Recover orphaned agent sessions from previous container lifecycle
    try:
        from apps.api.src.services.agent_runtime_recovery import recover_agents_on_startup
        recovery_summary = await recover_agents_on_startup()
        _log.info("Agent recovery: %s", recovery_summary)
    except Exception as exc:
        _log.exception("Agent recovery failed: %s", exc)

    yield

    # H10: mark API as draining so IdempotencyMiddleware returns 503 to new POSTs.
    set_shutting_down(True)
    import asyncio as _asyncio
    drain_timeout = float(os.getenv("SHUTDOWN_DRAIN_SECONDS", "30"))
    try:
        await _asyncio.sleep(min(drain_timeout, 2.0))  # brief quiesce for in-flight
    except Exception:
        pass

    # Shutdown in reverse order
    if stop_ingestion_fn is not None:
        try:
            await stop_ingestion_fn()
        except Exception:
            _log.exception("Failed to stop ingestion")

    if stop_scheduler_fn is not None:
        try:
            await stop_scheduler_fn()
        except Exception:
            _log.exception("Failed to stop scheduler")


app = FastAPI(
    title="Phoenix v2 API",
    description="Backend API for Phoenix multi-agent trading platform",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(JWTAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(connector_routes.router)
app.include_router(trades_routes.router)
app.include_router(positions_routes.router)
app.include_router(agents_routes.router)
app.include_router(execution_routes.router)
app.include_router(skills_routes.router)
app.include_router(backtests_routes.router)
app.include_router(strategies_routes.router)
app.include_router(monitoring_routes.router)
app.include_router(dev_agent_routes.router)
app.include_router(tasks_routes.router)
app.include_router(automations_routes.router)
app.include_router(admin_routes.router)
app.include_router(performance_routes.router)
app.include_router(market_routes.router)
app.include_router(ws_routes.router)
app.include_router(daily_signals_routes.router)
app.include_router(agent_learning_routes.router)
app.include_router(onchain_flow_routes.router)
app.include_router(macro_pulse_routes.router)
app.include_router(zero_dte_routes.router)
app.include_router(narrative_sentiment_routes.router)
app.include_router(risk_compliance_routes.router)
app.include_router(agent_messages_routes.router)
app.include_router(chat_routes.router)
app.include_router(notifications_routes.router)
app.include_router(error_logs_routes.router)
app.include_router(ai_expand_routes.router)
app.include_router(token_usage_routes.router)
app.include_router(system_logs_routes.router)
app.include_router(morning_routine_routes.router)
app.include_router(whatsapp_webhook_routes.router)
app.include_router(scheduler_status_routes.router)
app.include_router(eod_analysis_routes.router)
app.include_router(trade_signals_routes.router)
app.include_router(budget_routes.router)
app.include_router(agents_sprint_routes.router)
app.include_router(agents_sprint_routes.portfolio_router)
app.include_router(agent_terminal_routes.router)
app.include_router(briefing_history_routes.router)
app.include_router(claude_sdk_check_routes.router)
app.include_router(polymarket_routes.router)

# Phase H2: wire Prometheus /metrics endpoint
try:
    from shared.metrics import create_metrics_route
    create_metrics_route(app)
except Exception as _exc:
    import logging as _logging
    _logging.getLogger(__name__).warning("Failed to mount /metrics: %s", _exc)


@app.get("/health")
async def health():
    """Aggregate health check — verifies DB, Redis, scheduler, ingestion, disk.

    Returns 200 with details if all subsystems are healthy.
    Returns 503 with details if any critical subsystem is degraded.
    """
    from fastapi.responses import JSONResponse
    try:
        from apps.api.src.services.db_health import aggregate_health
        report = await aggregate_health()
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "service": "phoenix-api", "error": str(exc)[:200]},
        )

    report["service"] = "phoenix-api"
    status_code = 200 if report.get("status") == "ready" else 503
    return JSONResponse(status_code=status_code, content=report)


@app.get("/health/lite")
async def health_lite() -> dict:
    """Minimal health check for load balancers — does NOT touch DB.

    Use this for k8s liveness probes; use /health for readiness probes.
    """
    return {"status": "ready", "service": "phoenix-api"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.api.src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
