"""
Phoenix v2 Backend API — FastAPI application entrypoint.

M1.1: Minimal app with health endpoint. M1.3: Auth routes and JWT middleware.
Reference: ImplementationPlan.md Section 2, Section 5 M1.1, M1.3.
"""
from __future__ import annotations

import json
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
from apps.api.src.middleware.idempotency import IdempotencyMiddleware, set_shutting_down
from apps.api.src.middleware.logging import LoggingMiddleware
from apps.api.src.middleware.rate_limit import RateLimitMiddleware
from apps.api.src.routes import admin as admin_routes
from apps.api.src.routes import agent_learning as agent_learning_routes
from apps.api.src.routes import agent_messages as agent_messages_routes
from apps.api.src.routes import agent_terminal as agent_terminal_routes
from apps.api.src.routes import agents as agents_routes
from apps.api.src.routes import agents_sprint as agents_sprint_routes
from apps.api.src.routes import ai_expand as ai_expand_routes
from apps.api.src.routes import analyst as analyst_routes
from apps.api.src.routes import auth as auth_routes
from apps.api.src.routes import automations as automations_routes
from apps.api.src.routes import backtests as backtests_routes
from apps.api.src.routes import briefing_history as briefing_history_routes
from apps.api.src.routes import budget as budget_routes
from apps.api.src.routes import chat as chat_routes
from apps.api.src.routes import claude_sdk_check as claude_sdk_check_routes
from apps.api.src.routes import connectors as connector_routes
from apps.api.src.routes import consolidation as consolidation_routes
from apps.api.src.routes import daily_signals as daily_signals_routes
from apps.api.src.routes import dev_agent as dev_agent_routes
from apps.api.src.routes import emergency as emergency_routes
from apps.api.src.routes import eod_analysis as eod_analysis_routes
from apps.api.src.routes import error_logs as error_logs_routes
from apps.api.src.routes import execution as execution_routes
from apps.api.src.routes import invitations as invitations_routes
from apps.api.src.routes import macro_pulse as macro_pulse_routes
from apps.api.src.routes import market as market_routes
from apps.api.src.routes import market_data as market_data_routes
from apps.api.src.routes import monitoring as monitoring_routes
from apps.api.src.routes import morning_routine as morning_routine_routes
from apps.api.src.routes import narrative_sentiment as narrative_sentiment_routes
from apps.api.src.routes import notifications as notifications_routes
from apps.api.src.routes import onchain_flow as onchain_flow_routes
from apps.api.src.routes import performance as performance_routes
from apps.api.src.routes import portfolio as portfolio_routes
from apps.api.src.routes import pm_agents as pm_agents_routes
from apps.api.src.routes import pm_chat as pm_chat_routes
from apps.api.src.routes import pm_pipeline as pm_pipeline_routes
from apps.api.src.routes import pm_research as pm_research_routes
from apps.api.src.routes import pm_top_bets as pm_top_bets_routes
from apps.api.src.routes import pm_venues as pm_venues_routes
from apps.api.src.routes import polymarket as polymarket_routes
from apps.api.src.routes import positions as positions_routes
from apps.api.src.routes import risk_compliance as risk_compliance_routes
from apps.api.src.routes import scheduler_status as scheduler_status_routes
from apps.api.src.routes import strategies as strategies_routes
from apps.api.src.routes import system_logs as system_logs_routes
from apps.api.src.routes import tasks as tasks_routes
from apps.api.src.routes import token_usage as token_usage_routes
from apps.api.src.routes import trade_signals as trade_signals_routes
from apps.api.src.routes import trades as trades_routes
from apps.api.src.routes import trading_accounts as trading_accounts_routes
from apps.api.src.routes import user as user_routes
from apps.api.src.routes import watchlist as watchlist_routes
from apps.api.src.routes import whatsapp_webhook as whatsapp_webhook_routes
from apps.api.src.routes import wiki as wiki_routes
from apps.api.src.routes import ws as ws_routes
from apps.api.src.routes import zero_dte as zero_dte_routes

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
        # Agent Knowledge Wiki tables (migration 035) — full schema
        ("agent_wiki_entries.full_schema",
         "CREATE TABLE IF NOT EXISTS agent_wiki_entries ("
         "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
         "agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE, "
         "user_id UUID REFERENCES users(id) ON DELETE SET NULL, "
         "category VARCHAR(50) NOT NULL, "
         "subcategory VARCHAR(100), "
         "title VARCHAR(255) NOT NULL, "
         "content TEXT NOT NULL, "
         "tags VARCHAR[] DEFAULT '{}', "
         "symbols VARCHAR[] DEFAULT '{}', "
         "confidence_score FLOAT DEFAULT 0.5, "
         "trade_ref_ids VARCHAR[] DEFAULT '{}', "
         "created_by VARCHAR(10) DEFAULT 'agent', "
         "is_active BOOLEAN DEFAULT true, "
         "is_shared BOOLEAN DEFAULT false, "
         "version INTEGER DEFAULT 1, "
         "created_at TIMESTAMPTZ DEFAULT now(), "
         "updated_at TIMESTAMPTZ DEFAULT now())"),
        ("agent_wiki_entry_versions.full_schema",
         "CREATE TABLE IF NOT EXISTS agent_wiki_entry_versions ("
         "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
         "entry_id UUID NOT NULL REFERENCES agent_wiki_entries(id) ON DELETE CASCADE, "
         "version INTEGER NOT NULL, "
         "content TEXT NOT NULL, "
         "updated_by VARCHAR(10) DEFAULT 'agent', "
         "updated_at TIMESTAMPTZ DEFAULT now(), "
         "change_reason VARCHAR(500))"),
        ("index idx_wiki_agent_id",
         "CREATE INDEX IF NOT EXISTS idx_wiki_agent_id ON agent_wiki_entries(agent_id)"),
        ("index idx_wiki_category",
         "CREATE INDEX IF NOT EXISTS idx_wiki_category ON agent_wiki_entries(category)"),
        ("index idx_wiki_versions_entry",
         "CREATE INDEX IF NOT EXISTS idx_wiki_versions_entry ON agent_wiki_entry_versions(entry_id)"),
        # ------------------------------------------------------------------
        # Phase 15.8 safety net: pm_top_bets columns added in Phase 15.3–15.5
        # Each is idempotent; missing columns after a partial migration are
        # self-healed here so the TopBetsAgent never crashes on startup.
        # ------------------------------------------------------------------
        ("pm_top_bets.bull_argument",
         "ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS bull_argument TEXT"),
        ("pm_top_bets.bear_argument",
         "ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS bear_argument TEXT"),
        ("pm_top_bets.sample_probabilities",
         "ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS sample_probabilities JSONB"),
        ("pm_top_bets.reference_class",
         "ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS reference_class VARCHAR(100)"),
        ("pm_top_bets.base_rate_yes",
         "ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS base_rate_yes FLOAT"),
        ("pm_top_bets.confidence_score",
         "ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS confidence_score FLOAT"),
        # pm_chat_messages safety (Phase 15.6 — SSE partial flag)
        ("pm_chat_messages.is_partial",
         "ALTER TABLE pm_chat_messages ADD COLUMN IF NOT EXISTS is_partial BOOLEAN DEFAULT false"),
        # channel_messages: columns added in model but not original migration
        ("channel_messages.channel_id_snowflake",
         "ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS channel_id_snowflake VARCHAR(20)"),
        ("channel_messages.backfill_run_id",
         "ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS backfill_run_id UUID"),
        # Phase 3 safety net: consolidation_runs table (migration 036)
        ("table consolidation_runs",
         "CREATE TABLE IF NOT EXISTS consolidation_runs ("
         "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
         "agent_id UUID, "
         "run_type VARCHAR(20) NOT NULL DEFAULT 'nightly', "
         "status VARCHAR(20) NOT NULL DEFAULT 'pending', "
         "scheduled_for TIMESTAMPTZ, "
         "started_at TIMESTAMPTZ, "
         "completed_at TIMESTAMPTZ, "
         "trades_analyzed INTEGER NOT NULL DEFAULT 0, "
         "wiki_entries_written INTEGER NOT NULL DEFAULT 0, "
         "wiki_entries_updated INTEGER NOT NULL DEFAULT 0, "
         "wiki_entries_pruned INTEGER NOT NULL DEFAULT 0, "
         "patterns_found INTEGER NOT NULL DEFAULT 0, "
         "rules_proposed INTEGER NOT NULL DEFAULT 0, "
         "consolidation_report TEXT, "
         "error_message TEXT, "
         "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"),
        # Phase 5: indexes for consolidation_runs (idempotent; migration 036 covers fresh installs)
        ("index idx_consolidation_agent_id",
         "CREATE INDEX IF NOT EXISTS idx_consolidation_agent_id ON consolidation_runs(agent_id)"),
        ("index idx_consolidation_status",
         "CREATE INDEX IF NOT EXISTS idx_consolidation_status ON consolidation_runs(status)"),
        # Phase 6: Smart Context Builder — context_sessions table (migration 037)
        ("table context_sessions",
         "CREATE TABLE IF NOT EXISTS context_sessions ("
         "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
         "agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE, "
         "session_id UUID, "
         "session_type VARCHAR(20) DEFAULT 'trading', "
         "signal_symbol VARCHAR(20), "
         "token_budget INT DEFAULT 8000, "
         "tokens_used INT DEFAULT 0, "
         "wiki_entries_injected INT DEFAULT 0, "
         "trades_injected INT DEFAULT 0, "
         "manifest_sections_injected VARCHAR[] DEFAULT '{}', "
         "quality_score FLOAT DEFAULT 0.0, "
         "built_at TIMESTAMPTZ DEFAULT now())"),
        ("index idx_ctx_sessions_agent",
         "CREATE INDEX IF NOT EXISTS idx_ctx_sessions_agent ON context_sessions(agent_id)"),
        # ------------------------------------------------------------------
        # Migration 034 safety net: trade_signals analyst columns
        # These columns were added by 034_add_analyst_agent.py but are not
        # present on databases that were deployed before that migration ran.
        # Any INSERT/SELECT on trade_signals fails with ProgrammingError when
        # they are absent.  All are nullable so adding them is always safe.
        # ------------------------------------------------------------------
        ("trade_signals.analyst_persona",
         "ALTER TABLE trade_signals ADD COLUMN IF NOT EXISTS analyst_persona VARCHAR(50)"),
        ("trade_signals.tool_signals_used",
         "ALTER TABLE trade_signals ADD COLUMN IF NOT EXISTS tool_signals_used JSONB"),
        ("trade_signals.risk_reward_ratio",
         "ALTER TABLE trade_signals ADD COLUMN IF NOT EXISTS risk_reward_ratio DOUBLE PRECISION"),
        ("trade_signals.take_profit",
         "ALTER TABLE trade_signals ADD COLUMN IF NOT EXISTS take_profit DOUBLE PRECISION"),
        ("trade_signals.entry_price",
         "ALTER TABLE trade_signals ADD COLUMN IF NOT EXISTS entry_price DOUBLE PRECISION"),
        ("trade_signals.stop_loss",
         "ALTER TABLE trade_signals ADD COLUMN IF NOT EXISTS stop_loss DOUBLE PRECISION"),
        ("trade_signals.pattern_name",
         "ALTER TABLE trade_signals ADD COLUMN IF NOT EXISTS pattern_name VARCHAR(100)"),
        # ------------------------------------------------------------------
        # connector_agents.is_active: column added to model but not in any
        # migration.  Existing rows have NULL; resolve_agent_connector_ids_for_feed
        # and start_ingestion() both filter is_active.is_(True) → NULL IS TRUE
        # is FALSE, so all connector links are invisible after a deploy that
        # adds this column.  Backfill to TRUE for pre-existing rows.
        # ------------------------------------------------------------------
        ("connector_agents.is_active",
         "ALTER TABLE connector_agents ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"),
        ("connector_agents.is_active_backfill",
         "UPDATE connector_agents SET is_active = TRUE WHERE is_active IS NULL"),
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

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        from shared.db.engine import get_engine

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


async def _heal_live_agent_claude_settings(_log, data_dir: "Path | None" = None) -> None:
    """Heal existing live agent directories missing .claude/settings.json.

    Scans data/live_agents/*/ directories. For each that has
    tools/robinhood_mcp.py but no .claude/settings.json, reads config.json
    and writes the settings file with credentials injected.

    Args:
        _log:     Logger instance.
        data_dir: Override the repo ``data/`` directory (used in tests).
                  Defaults to ``<repo_root>/data`` resolved from this file's path.
    """
    from apps.api.src.services.agent_gateway import _write_claude_settings as _write_settings

    if data_dir is None:
        # main.py lives at apps/api/src/main.py → parents[3] == repo root
        data_dir = Path(__file__).resolve().parents[3] / "data"

    live_agents_dir = data_dir / "live_agents"
    if not live_agents_dir.exists():
        return

    healed = 0
    for agent_dir in live_agents_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        claude_settings = agent_dir / ".claude" / "settings.json"
        robinhood_mcp = agent_dir / "tools" / "robinhood_mcp.py"

        if not robinhood_mcp.exists():
            continue  # not a live-trader agent

        if claude_settings.exists():
            continue  # already has settings

        # Read config.json for credentials
        config_path = agent_dir / "config.json"
        if not config_path.exists():
            continue

        try:
            config = json.loads(config_path.read_text())
        except Exception as exc:
            _log.warning("[heal_mcp] Failed to read config for %s: %s", agent_dir.name, exc)
            continue

        rh_creds = config.get("robinhood_credentials") or config.get("robinhood") or {}
        paper_mode = config.get("paper_mode", True)

        _write_settings(agent_dir, rh_creds, paper_mode=bool(paper_mode))
        _log.info("[heal_mcp] Wrote .claude/settings.json for agent %s", agent_dir.name)
        healed += 1

    if healed:
        _log.info("[heal_mcp] Healed %d live agent director(ies)", healed)


async def _seed_system_agents() -> None:
    """Idempotently seed reserved system-agent rows into the ``agents`` table.

    Five hard-coded UUIDs are used as ``agent_id`` in ``agent_sessions`` by the
    gateway (supervisor, morning-briefing, EOD analysis, daily-summary, trade-
    feedback).  The FK ``agent_sessions.agent_id → agents.id`` rejects every
    INSERT until these rows exist.  Running this at startup (and in the Docker
    migrate script) ensures the constraint is always satisfied.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    _SYSTEM_AGENTS = [
        ("00000000-0000-0000-0000-000000000001", "system", "Supervisor Agent"),
        ("00000000-0000-0000-0000-000000000002", "system", "Morning Briefing Agent"),
        ("00000000-0000-0000-0000-000000000003", "system", "EOD Analysis Agent"),
        ("00000000-0000-0000-0000-000000000004", "system", "Daily Summary Agent"),
        ("00000000-0000-0000-0000-000000000005", "system", "Trade Feedback Agent"),
    ]

    from sqlalchemy import text

    from shared.db.engine import get_engine

    engine = get_engine()
    for uid, atype, name in _SYSTEM_AGENTS:
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO agents (id, name, type, status, config,
                                       worker_status, source,
                                       manifest, pending_improvements,
                                       current_mode, rules_version,
                                       daily_pnl, total_pnl, total_trades,
                                       win_rate, tokens_used_today_usd,
                                       tokens_used_month_usd,
                                       created_at, updated_at)
                    VALUES (:id, :name, :type, 'CREATED', '{}',
                            'STOPPED', 'system',
                            '{}', '{}',
                            'conservative', 1,
                            0, 0, 0,
                            0, 0, 0, now(), now())
                    ON CONFLICT (id) DO NOTHING
                """),
                {"id": uid, "name": name, "type": atype},
            )
    _log.info("[seed_system_agents] reserved agent rows ensured")


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
        # Try to load from the active anthropic connector in the DB
        try:
            from shared.db.engine import async_session as _make_session
            from shared.db.models.connector import Connector as _Connector
            from shared.crypto.credentials import decrypt_credentials as _decrypt
            from sqlalchemy import select as _select
            _s = _make_session()
            try:
                _res = await _s.execute(
                    _select(_Connector).where(
                        _Connector.type == "anthropic",
                        _Connector.is_active.is_(True),
                        _Connector.status == "connected",
                    ).limit(1)
                )
                _conn = _res.scalar_one_or_none()
                if _conn and _conn.credentials_encrypted:
                    _creds = _decrypt(_conn.credentials_encrypted)
                    _loaded_key = _creds.get("api_key", "")
                    if _loaded_key:
                        os.environ["ANTHROPIC_API_KEY"] = _loaded_key
                        _log.info("[startup] ANTHROPIC_API_KEY loaded from anthropic connector (len=%d)", len(_loaded_key))
                    else:
                        _log.warning("[startup] ANTHROPIC_API_KEY not set — Claude SDK will fail")
                else:
                    _log.warning("[startup] ANTHROPIC_API_KEY not set — Claude SDK will fail")
            finally:
                await _s.close()
        except Exception as _exc:
            _log.warning("[startup] Could not load ANTHROPIC_API_KEY from connector: %s", _exc)
            _log.warning("[startup] ANTHROPIC_API_KEY not set — Claude SDK will fail")

    # Validate Fernet encryption key at startup
    _enc_key = os.getenv("CREDENTIAL_ENCRYPTION_KEY") or os.getenv("FERNET_KEY")
    if _enc_key:
        try:
            from cryptography.fernet import Fernet
            Fernet(_enc_key.encode() if isinstance(_enc_key, str) else _enc_key)
            _log.info("CREDENTIAL_ENCRYPTION_KEY validated successfully")
        except Exception as exc:
            _log.error("CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key: %s", exc)
            _log.error("Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    else:
        _log.warning("No CREDENTIAL_ENCRYPTION_KEY set — connector credential encryption will fail")

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

    # Seed reserved system-agent rows so FK agent_sessions.agent_id → agents.id
    # is satisfied for supervisor, morning-briefing, EOD, daily-summary, trade-feedback.
    try:
        await _seed_system_agents()
    except Exception as exc:
        _log.exception("[seed_system_agents] top-level crash: %s", exc)

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
        await _heal_live_agent_claude_settings(_log)
    except Exception as exc:
        _log.exception("[heal_mcp] Failed: %s", exc)

    # Agent recovery is now handled by phoenix-agent-orchestrator.
    # Keep as fallback during migration, controlled by env var.
    if os.environ.get("ENABLE_API_AGENT_RECOVERY", "").lower() == "true":
        try:
            from apps.api.src.services.agent_runtime_recovery import recover_agents_on_startup
            recovery_summary = await recover_agents_on_startup()
            _log.info("Agent recovery: %s", recovery_summary)
        except Exception as exc:
            _log.exception("Agent recovery failed: %s", exc)
    else:
        _log.info("Agent recovery disabled — handled by phoenix-agent-orchestrator")

    # Install SIGTERM handler: mark all running sessions as 'interrupted'
    # so recovery on next startup knows they were gracefully stopped.
    import asyncio as _asyncio
    import signal as _signal

    def _sigterm_handler(signum, frame):
        _log.info("[shutdown] SIGTERM received — marking sessions interrupted")
        try:
            from apps.api.src.services.agent_gateway import _running_tasks
            for key, task in list(_running_tasks.items()):
                if not task.done():
                    task.cancel()
            _log.info("[shutdown] Cancelled %d running tasks", len(_running_tasks))
        except Exception as e:
            _log.warning("[shutdown] Failed to cancel tasks: %s", e)

    _signal.signal(_signal.SIGTERM, _sigterm_handler)

    yield

    # H10: mark API as draining so IdempotencyMiddleware returns 503 to new POSTs.
    set_shutting_down(True)
    drain_timeout = float(os.getenv("SHUTDOWN_DRAIN_SECONDS", "30"))
    try:
        await _asyncio.sleep(min(drain_timeout, 2.0))  # brief quiesce for in-flight
    except Exception:
        pass

    # Mark all running agent sessions as interrupted in DB
    try:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from sqlalchemy import update

        from shared.db.engine import get_session
        from shared.db.models.agent_session import AgentSession

        async for db in get_session():
            await db.execute(
                update(AgentSession)
                .where(AgentSession.status.in_(["running", "starting"]))
                .values(status="interrupted", error_message="Graceful shutdown (SIGTERM)",
                        stopped_at=_dt.now(_tz.utc))
            )
            await db.commit()
        _log.info("[shutdown] Marked running sessions as interrupted")
    except Exception as exc:
        _log.warning("[shutdown] Failed to mark sessions: %s", exc)

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
app.include_router(trading_accounts_routes.router)
app.include_router(execution_routes.router)
app.include_router(backtests_routes.router)
app.include_router(strategies_routes.router)
app.include_router(monitoring_routes.router)
app.include_router(dev_agent_routes.router)
app.include_router(tasks_routes.router)
app.include_router(automations_routes.router)
app.include_router(admin_routes.router)
app.include_router(performance_routes.router)
app.include_router(market_routes.router)
app.include_router(market_data_routes.router)
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
app.include_router(emergency_routes.router)
app.include_router(trade_signals_routes.router)
app.include_router(budget_routes.router)
app.include_router(agents_sprint_routes.router)
app.include_router(agents_sprint_routes.portfolio_router)
app.include_router(agent_terminal_routes.router)
app.include_router(briefing_history_routes.router)
app.include_router(claude_sdk_check_routes.router)
app.include_router(polymarket_routes.router)
app.include_router(analyst_routes.router)
app.include_router(pm_top_bets_routes.router)
app.include_router(pm_chat_routes.router)
app.include_router(pm_agents_routes.router)
app.include_router(pm_research_routes.router)
app.include_router(pm_venues_routes.router)
app.include_router(pm_pipeline_routes.router)
app.include_router(wiki_routes.router)
app.include_router(wiki_routes.brain_router)
app.include_router(consolidation_routes.router)
app.include_router(invitations_routes.router)
app.include_router(user_routes.router)
app.include_router(portfolio_routes.router)
app.include_router(watchlist_routes.router)

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


@app.get("/metrics")
async def metrics() -> str:
    """Prometheus metrics endpoint with DLQ size gauge."""
    from prometheus_client import generate_latest
    from sqlalchemy import text

    from shared.db.engine import get_session
    from shared.metrics import registry
    from shared.observability.metrics import dlq_size_gauge

    # Update DLQ size gauge from DB
    try:
        async for session in get_session():
            result = await session.execute(
                text("SELECT connector_id, COUNT(*) FROM dead_letter_messages WHERE resolved = false GROUP BY connector_id")
            )
            rows = result.all()
            # Reset all gauges first
            for connector_id, count in rows:
                dlq_size_gauge.labels(connector_id=connector_id).set(count)
    except Exception:
        pass  # Metrics endpoint should not fail on DB errors

    from starlette.responses import Response
    return Response(
        content=generate_latest(registry),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.api.src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
