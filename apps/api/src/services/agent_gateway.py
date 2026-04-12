"""Agent Gateway — central hub for managing Claude Code agent lifecycle.

Unified gateway that:
  - Tracks all active Claude Code sessions in the DB (agent_sessions table)
  - Creates backtesting and analyst agent sessions from templates
  - Manages lifecycle: start, stop, pause, resume, health-check
  - Orchestrates the backtest → auto-create-analyst flow
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pwd
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from shared.context.builder import ENABLE_SMART_CONTEXT, ContextBuilderService
from shared.db.engine import get_session as _get_session
from shared.db.models.agent import Agent, AgentBacktest, AgentLog
from shared.db.models.agent_session import AgentSession
from shared.db.models.system_log import SystemLog

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKTESTING_DIR = REPO_ROOT / "agents" / "backtesting"
BACKTESTING_TOOLS = BACKTESTING_DIR / "tools"
LIVE_TEMPLATE = REPO_ROOT / "agents" / "templates" / "live-trader-v1"
POSITION_MONITOR_TEMPLATE = REPO_ROOT / "agents" / "templates" / "position-monitor-agent"
SUPERVISOR_TEMPLATE = REPO_ROOT / "agents" / "templates" / "supervisor-agent"
UW_TEMPLATE = REPO_ROOT / "agents" / "templates" / "unusual-whales-agent"
SOCIAL_TEMPLATE = REPO_ROOT / "agents" / "templates" / "social-sentiment-agent"
STRATEGY_TEMPLATE = REPO_ROOT / "agents" / "templates" / "strategy-agent"
MORNING_BRIEFING_TEMPLATE = REPO_ROOT / "agents" / "templates" / "morning-briefing-agent"
DAILY_SUMMARY_TEMPLATE = REPO_ROOT / "agents" / "templates" / "daily-summary-agent"
EOD_ANALYSIS_TEMPLATE = REPO_ROOT / "agents" / "templates" / "eod-analysis-agent"
TRADE_FEEDBACK_TEMPLATE = REPO_ROOT / "agents" / "templates" / "trade-feedback-agent"
ANALYST_TEMPLATE = "analyst-agent"
DATA_DIR = REPO_ROOT / "data"

# Reserved system-agent UUIDs — must match the seed list in apps/api/src/main.py and
# scripts/docker_migrate.py.  Defined once here so a typo anywhere causes a NameError
# rather than a silent FK violation.
_SUPERVISOR_AGENT_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_MORNING_BRIEFING_AGENT_UUID = uuid.UUID("00000000-0000-0000-0000-000000000002")
_EOD_ANALYSIS_AGENT_UUID = uuid.UUID("00000000-0000-0000-0000-000000000003")
_DAILY_SUMMARY_AGENT_UUID = uuid.UUID("00000000-0000-0000-0000-000000000004")
_TRADE_FEEDBACK_AGENT_UUID = uuid.UUID("00000000-0000-0000-0000-000000000005")

# Canonical names — must match the seed list in main.py and scripts/docker_migrate.py.
_SYSTEM_AGENT_NAMES: dict[str, str] = {
    "eod_analysis": "EOD Analysis Agent",
    "daily_summary": "Daily Summary Agent",
    "trade_feedback": "Trade Feedback Agent",
}

_running_tasks: dict[str, asyncio.Task] = {}

# Track live PositionMicroAgent instances for sell signal routing
_micro_agents: dict[str, Any] = {}  # key = "{agent_id}:{position_id}" -> PositionMicroAgent


def _analyst_profile_to_dict(prof: Any) -> dict:
    """Convert an AnalystProfile ORM instance to a plain dict for JSON serialization."""
    return {
        "analyst_name": prof.analyst_name,
        "win_rate_10": prof.win_rate_10,
        "win_rate_20": prof.win_rate_20,
        "avg_hold_hours": prof.avg_hold_hours,
        "median_exit_pnl": prof.median_exit_pnl,
        "exit_pnl_p25": prof.exit_pnl_p25,
        "exit_pnl_p75": prof.exit_pnl_p75,
        "avg_exit_hour": prof.avg_exit_hour,
        "preferred_exit_dow": prof.preferred_exit_dow,
        "drawdown_tolerance": prof.drawdown_tolerance,
        "post_earnings_sell_rate": prof.post_earnings_sell_rate,
        "conviction_score": prof.conviction_score,
        "profile_data": prof.profile_data or {},
    }


def _get_api_url() -> str:
    """Return the Phoenix API base URL for intra-cluster curl calls.

    Priority:
      1. PHOENIX_API_URL env var (explicit override)
      2. PUBLIC_API_URL env var (legacy alias)
      3. http://localhost:8011 (safe local default — never the production domain)
    """
    return os.getenv("PHOENIX_API_URL", os.getenv("PUBLIC_API_URL", "http://localhost:8011"))
_session_ids: dict[str, str] = {}
_chat_session_ids: dict[str, str] = {}

CHAT_REPLY_TIMEOUT = int(os.environ.get("CHAT_REPLY_TIMEOUT_SECONDS", "120"))

_ROBINHOOD_MCP_SOURCE = (
    REPO_ROOT / "agents" / "templates" / "live-trader-v1" / "tools" / "robinhood_mcp.py"
)

_ROBINHOOD_CHAT_TOOLS: list[str] = [
    "mcp__robinhood__robinhood_login",
    "mcp__robinhood__get_positions",
    "mcp__robinhood__get_option_positions",
    "mcp__robinhood__get_all_positions",
    "mcp__robinhood__get_account",
    "mcp__robinhood__get_account_snapshot",
    "mcp__robinhood__get_quote",
    "mcp__robinhood__get_nbbo",
    "mcp__robinhood__get_option_chain",
    "mcp__robinhood__get_option_greeks",
    "mcp__robinhood__get_order_status",
    "mcp__robinhood__get_order_history",
    "mcp__robinhood__get_watchlist",
    "mcp__robinhood__close_position",
    "mcp__robinhood__close_option_position",
    "mcp__robinhood__place_stock_order",
    "mcp__robinhood__place_option_order",
    "mcp__robinhood__smart_limit_order",
    "mcp__robinhood__add_to_watchlist",
    "mcp__robinhood__remove_from_watchlist",
    "mcp__robinhood__place_order_with_stop_loss",
    "mcp__robinhood__cancel_and_close",
    "mcp__robinhood__modify_stop_loss",
    "mcp__robinhood__place_order_with_buffer",
]


# Hard billing failures — account has no credits / payment issue
_BILLING_ERROR_PATTERNS = (
    "credit balance is too low",
    "insufficient credit",
    "payment required",
    "spending limit",
)

# Temporary throttles — not a billing issue, will resolve on its own
_RATE_LIMIT_PATTERNS = (
    "rate_limit_error",
    "over_quota",
    "too many requests",
    "overloaded",
)

# Catch-all that includes both (kept for the broad _is_credit_error check)
_CREDIT_ERROR_PATTERNS = _BILLING_ERROR_PATTERNS + _RATE_LIMIT_PATTERNS + ("billing",)


def _is_credit_error(text: str) -> bool:
    """Return True if the error text looks like an Anthropic billing or rate-limit issue."""
    lower = text.lower()
    return any(p in lower for p in _CREDIT_ERROR_PATTERNS)


def _is_rate_limit_error(text: str) -> bool:
    """Return True if this is a temporary rate-limit/overload (not a hard billing failure)."""
    lower = text.lower()
    return any(p in lower for p in _RATE_LIMIT_PATTERNS)


def _extract_rate_limit_info(raw: str) -> str:
    """Parse Anthropic rate-limit fields from an error string and return a compact summary.

    Anthropic embeds header values in error messages, e.g.:
      'rate_limit_error: ... retry-after: 30 ... x-ratelimit-limit-requests: 60
       x-ratelimit-remaining-requests: 0 x-ratelimit-limit-tokens: 80000
       x-ratelimit-remaining-tokens: 0'

    Returns a string like:
      '[limit: 60 req/min | remaining: 0 req | limit: 80000 tok/min | remaining: 0 tok | retry-after: 30s]'
    or empty string if nothing can be parsed.
    """
    import re
    parts: list[str] = []

    def _find(pattern: str) -> str | None:
        m = re.search(pattern, raw, re.IGNORECASE)
        return m.group(1).strip() if m else None

    req_limit     = _find(r"x-ratelimit-limit-requests[:\s]+(\d+)")
    req_remaining = _find(r"x-ratelimit-remaining-requests[:\s]+(\d+)")
    tok_limit     = _find(r"x-ratelimit-limit-tokens[:\s]+(\d+)")
    tok_remaining = _find(r"x-ratelimit-remaining-tokens[:\s]+(\d+)")
    retry_after   = _find(r"retry-after[:\s]+(\d+(?:\.\d+)?)")

    if req_limit:
        parts.append(f"req limit: {req_limit}/min")
    if req_remaining is not None:
        parts.append(f"req remaining: {req_remaining}")
    if tok_limit:
        parts.append(f"tok limit: {tok_limit}/min")
    if tok_remaining is not None:
        parts.append(f"tok remaining: {tok_remaining}")
    if retry_after:
        parts.append(f"retry-after: {retry_after}s")

    return f"[{' | '.join(parts)}]" if parts else ""


def _format_credit_error(raw: str) -> str:
    """Return a user-facing error string that always includes the raw Anthropic message.

    Distinguishes rate-limit throttles (temporary) from hard billing failures so
    operators can see the real cause in the logs and dashboard.
    Appends parsed rate-limit info (limits, remaining, retry-after) when available.
    """
    raw_snippet = raw[:300]
    limit_info = _extract_rate_limit_info(raw)
    limit_suffix = f" {limit_info}" if limit_info else ""
    if _is_rate_limit_error(raw):
        return (
            f"RATE LIMIT ERROR (temporary): {raw_snippet}.{limit_suffix} "
            "Anthropic is throttling requests — this is NOT a billing problem. "
            "Phoenix will retry automatically. If this persists, reduce concurrent "
            "agents or upgrade your Anthropic API tier."
        )
    return (
        f"BILLING ERROR: {raw_snippet}.{limit_suffix} "
        "This error comes from the Anthropic API / Claude Code CLI billing system, "
        "NOT from Phoenix. To fix: (1) Check your Claude Code spending limit via "
        "`claude config get`; (2) Add credits at console.anthropic.com; "
        "(3) If using Claude Max plan, verify your subscription is active."
    )


async def _persist_agent_log(agent_id: uuid.UUID, level: str, message: str, context: dict | None = None) -> None:
    """Fire-and-forget: write one row to agent_logs without blocking the caller."""
    try:
        async for db in _get_session():
            db.add(AgentLog(
                id=uuid.uuid4(),
                agent_id=agent_id,
                level=level,
                message=message[:2000],
                context=context or {},
            ))
            await db.commit()
    except Exception as _exc:
        logger.debug("[agent_log] write failed (non-fatal): %s", _exc)


def _write_claude_settings(work_dir: Path, rh_creds: dict, paper_mode: bool = True) -> None:
    """Write .claude/settings.json with Robinhood MCP server wired in.

    Always registers the robinhood MCP entry so that both paper and live agents
    can call Robinhood tools. In paper mode (PAPER_MODE=true) the MCP server
    simulates all orders without touching the real Robinhood API.

    Args:
        work_dir:   Agent working directory (e.g. data/live_agents/<id>/).
        rh_creds:   Dict with keys ``username``, ``password``, ``totp_secret``.
                    Pass an empty dict for paper-only agents.
        paper_mode: When True sets PAPER_MODE=true in the MCP server env.
    """
    claude_dir = work_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)

    mcp_env: dict[str, str] = {
        "ROBINHOOD_CONFIG": "config.json",
        "PAPER_MODE": "true" if paper_mode else "false",
    }
    if rh_creds:
        mcp_env["RH_USERNAME"] = rh_creds.get("username", "")
        mcp_env["RH_PASSWORD"] = rh_creds.get("password", "")
        mcp_env["RH_TOTP_SECRET"] = rh_creds.get("totp_secret", "")

    settings: dict = {
        "permissions": {
            "allow": [
                "Bash(python *)", "Bash(python3 *)", "Bash(pip *)",
                "Bash(pip3 *)", "Bash(curl *)", "Read", "Write", "Edit", "Grep", "Glob",
                "mcp__robinhood__*",
            ],
            "deny": [
                "Bash(rm -rf /)", "Bash(rm -rf ~)", "Bash(git push --force *)",
                "Bash(shutdown *)", "Bash(reboot *)"
            ]
        },
        "mcpServers": {
            "robinhood": {
                "command": sys.executable,
                "args": ["tools/robinhood_mcp.py"],
                "env": mcp_env,
            }
        },
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "python3 tools/report_to_phoenix.py --event session_start 2>/dev/null || true"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "python3 tools/report_to_phoenix.py --event session_stop 2>/dev/null || true"}]}]
        }
    }

    settings_path = claude_dir / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2))
    settings_path.chmod(0o600)  # owner-only: file contains plaintext credentials


# Phase H5: Concurrency limits to prevent OOM from too many subprocesses
MAX_CONCURRENT_BACKTESTS = int(os.environ.get("MAX_CONCURRENT_BACKTESTS", "4"))
MAX_CONCURRENT_LIVE_AGENTS = int(os.environ.get("MAX_CONCURRENT_LIVE_AGENTS", "20"))
MAX_CONCURRENT_POSITION_AGENTS = int(os.environ.get("MAX_CONCURRENT_POSITION_AGENTS", "50"))

_backtest_sem = asyncio.Semaphore(MAX_CONCURRENT_BACKTESTS)
_live_agent_sem = asyncio.Semaphore(MAX_CONCURRENT_LIVE_AGENTS)
_position_agent_sem = asyncio.Semaphore(MAX_CONCURRENT_POSITION_AGENTS)


def get_concurrency_status() -> dict:
    """Return current semaphore utilization for /scheduler/status dashboard."""
    return {
        "backtests": {
            "max": MAX_CONCURRENT_BACKTESTS,
            "available": _backtest_sem._value,
            "in_use": MAX_CONCURRENT_BACKTESTS - _backtest_sem._value,
        },
        "live_agents": {
            "max": MAX_CONCURRENT_LIVE_AGENTS,
            "available": _live_agent_sem._value,
            "in_use": MAX_CONCURRENT_LIVE_AGENTS - _live_agent_sem._value,
        },
        "position_agents": {
            "max": MAX_CONCURRENT_POSITION_AGENTS,
            "available": _position_agent_sem._value,
            "in_use": MAX_CONCURRENT_POSITION_AGENTS - _position_agent_sem._value,
        },
    }


async def _ensure_system_agent(db, agent_id: uuid.UUID, name: str) -> None:
    """Get-or-create a system agent row so the FK agent_sessions.agent_id → agents.id is satisfied.

    Called directly before every AgentSession INSERT that uses a reserved system UUID.
    This makes session creation self-healing even when the startup seed failed
    (e.g. DB not ready at boot, schema drift, or the agents table was wiped).

    Uses INSERT … ON CONFLICT DO NOTHING so it is safe to call on every invocation
    (idempotent, no SELECT round-trip needed, concurrent-safe).
    """
    await db.execute(
        text("""
            INSERT INTO agents (id, name, type, status, config,
                               worker_status, source,
                               manifest, pending_improvements,
                               current_mode, rules_version,
                               daily_pnl, total_pnl, total_trades,
                               win_rate, tokens_used_today_usd,
                               tokens_used_month_usd,
                               created_at, updated_at)
            VALUES (:id, :name, 'system', 'CREATED', '{}',
                    'STOPPED', 'system',
                    '{}', '{}',
                    'conservative', 1,
                    0, 0, 0,
                    0, 0, 0,
                    NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
        """),
        {"id": str(agent_id), "name": name},
    )


class AgentGateway:
    """Singleton gateway for all Claude Code agent operations."""

    # ------------------------------------------------------------------
    # Backtesting agent
    # ------------------------------------------------------------------

    async def create_backtester(
        self, agent_id: uuid.UUID, backtest_id: uuid.UUID, config: dict
    ) -> str:
        """Spawn a Claude Code backtesting session. Returns session row id.

        Singleton enforcement: only one backtest runs per agent at a time.
        If one is already RUNNING in DB or in _running_tasks, returns existing key.
        Each re-run writes to a versioned subdirectory output/v{N}/ so prior
        artifacts are preserved for comparison.

        Phase H7: Refuses to spawn if the agent is over its token budget.
        """
        # Phase H7 budget check
        try:
            from apps.api.src.services.budget_enforcer import check_budget
            budget = await check_budget(agent_id)
            if not budget.get("ok"):
                logger.warning("Backtest spawn rejected for %s: %s",
                               agent_id, budget.get("reason"))
                return f"BUDGET_EXCEEDED:{budget.get('reason')}"
        except Exception as exc:
            logger.warning("Budget check failed for %s, allowing: %s", agent_id, exc)

        task_key = str(agent_id)

        # Check in-memory task first
        if task_key in _running_tasks and not _running_tasks[task_key].done():
            logger.warning("Backtest already running for agent %s (in-memory)", agent_id)
            return task_key

        # Check DB for a RUNNING backtest (covers restarts where task dict was lost)
        # Compute the next version number from the highest existing backtest version
        version = 1
        async for db in _get_session():
            existing_bt = (await db.execute(
                select(AgentBacktest).where(
                    AgentBacktest.agent_id == agent_id,
                    AgentBacktest.status == "RUNNING",
                    AgentBacktest.id != backtest_id,
                )
            )).scalar_one_or_none()
            if existing_bt:
                logger.warning(
                    "Backtest already running for agent %s (DB: %s)", agent_id, existing_bt.id
                )
                return str(existing_bt.id)

            # Determine next version: max(existing) + 1
            from sqlalchemy import func as _func
            max_v = (await db.execute(
                select(_func.max(AgentBacktest.backtesting_version))
                .where(AgentBacktest.agent_id == agent_id)
            )).scalar()
            version = (max_v or 0) + 1

            # Stamp this backtest with the version
            current_bt = (await db.execute(
                select(AgentBacktest).where(AgentBacktest.id == backtest_id)
            )).scalar_one_or_none()
            if current_bt:
                current_bt.backtesting_version = version
                await db.commit()

        # Use versioned subdirectory: data/backtest_{agent_id}/output/v{N}/
        work_dir = DATA_DIR / f"backtest_{agent_id}"
        work_dir.mkdir(parents=True, exist_ok=True)
        version_dir = work_dir / "output" / f"v{version}"
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "models").mkdir(exist_ok=True)
        (version_dir / "preprocessed").mkdir(exist_ok=True)

        # Write a "latest.json" pointer file at the agent root for easy lookup
        latest_pointer = work_dir / "latest.json"
        latest_pointer.write_text(json.dumps({
            "version": version,
            "backtest_id": str(backtest_id),
            "output_dir": str(version_dir),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2))

        # Maintain a backward-compatible "output/" symlink to the latest version
        # so existing tools that look at output/ keep working.
        compat_output = work_dir / "output_current"
        try:
            if compat_output.is_symlink() or compat_output.exists():
                compat_output.unlink()
            compat_output.symlink_to(version_dir)
        except (OSError, NotImplementedError):
            # Symlinks may not work on all filesystems; ignore
            pass

        # Write config inside the version dir so each version is self-contained
        config_path = version_dir / "config.json"
        config["_backtest_version"] = version
        config["_version_dir"] = str(version_dir)
        config_path.write_text(json.dumps(config, indent=2, default=str))

        # Also keep a top-level config.json for compat with tools that look there
        (work_dir / "config.json").write_text(json.dumps(config, indent=2, default=str))

        session_row_id = uuid.uuid4()
        async for db in _get_session():
            db.add(AgentSession(
                id=session_row_id,
                agent_id=agent_id,
                agent_type="backtester",
                status="starting",
                working_dir=str(version_dir),
                config=config,
            ))
            await db.commit()

        task = asyncio.create_task(
            self._run_backtester(agent_id, backtest_id, config, version_dir, session_row_id)
        )
        _running_tasks[task_key] = task
        return str(session_row_id)

    async def _run_backtester(
        self,
        agent_id: uuid.UUID,
        backtest_id: uuid.UUID,
        config: dict,
        work_dir: Path,
        session_row_id: uuid.UUID,
    ) -> None:
        """Run backtesting via Claude Code agent with retries. No subprocess fallback.

        Phase H5: bounded by `_backtest_sem` (default 4 concurrent). Excess
        callers wait in the semaphore queue until a slot frees.
        """
        async with _backtest_sem:
            await self._run_backtester_inner(
                agent_id, backtest_id, config, work_dir, session_row_id
            )

    async def _run_backtester_inner(
        self,
        agent_id: uuid.UUID,
        backtest_id: uuid.UUID,
        config: dict,
        work_dir: Path,
        session_row_id: uuid.UUID,
    ) -> None:
        """Backtester body — uses Tier 1 orchestrator or falls back to Claude SDK."""
        _chown_to_phoenix(work_dir)

        # Transition backtest from PENDING → RUNNING now that we're actually executing
        async for db in _get_session():
            bt = (await db.execute(
                select(AgentBacktest).where(AgentBacktest.id == backtest_id)
            )).scalar_one_or_none()
            if bt and bt.status == "PENDING":
                bt.status = "RUNNING"
                await db.commit()

        # Three-tier: use BacktestOrchestrator (Tier 1) instead of Claude SDK
        use_orchestrator = os.getenv("BACKTEST_TIER", "orchestrator") != "sdk"
        if use_orchestrator:
            try:
                from apps.api.src.services.backtest_orchestrator import BacktestOrchestrator

                enabled_algos = config.get("enabled_algorithms")
                orch = BacktestOrchestrator(
                    agent_id=agent_id,
                    session_id=session_row_id,
                    work_dir=work_dir,
                    config=config,
                    enabled_algorithms=enabled_algos,
                )
                result = await orch.run()

                status = result.get("status", "failed")
                async for db in _get_session():
                    if status == "completed":
                        await _mark_backtest_completed(db, agent_id, backtest_id)
                        await self._auto_create_analyst(agent_id, config, work_dir)
                    else:
                        await _mark_backtest_failed(
                            db, agent_id, backtest_id, "backtest-orchestrator",
                            f"Failed at step {result.get('failed_step')}"
                        )
                _running_tasks.pop(str(agent_id), None)
                return
            except Exception as e:
                logger.warning("BacktestOrchestrator failed, falling back to Claude SDK: %s", e)

        use_claude = _can_use_claude_sdk()

        if not use_claude:
            reason = _sdk_unavailable_reason()
            logger.error("Claude SDK unavailable for agent %s: %s", agent_id, reason)
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error=f"Claude SDK unavailable: {reason}")
                await _syslog(db, agent_id, backtest_id, "sdk_unavailable", 0,
                              f"Backtesting requires Claude Code SDK — {reason}")
                await _mark_backtest_failed(db, agent_id, backtest_id, "agent-gateway",
                                           f"Claude SDK unavailable: {reason}")
            return

        async for db in _get_session():
            await self._update_session(db, session_row_id, status="running")
            await _syslog(db, agent_id, backtest_id, "claude_agent_start", 2,
                          "Starting Claude Code agent for backtesting")

        # F2: pre-flight checks — fail fast if the CLI is broken or the key is missing
        preflight_err = _claude_sdk_preflight()
        if preflight_err:
            logger.error("[backtester] preflight failed for agent %s: %s", agent_id, preflight_err)
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error=f"preflight_failed: {preflight_err[:200]}")
                await _syslog(db, agent_id, backtest_id, "sdk_preflight_fail", 3,
                              f"Claude SDK preflight failed: {preflight_err[:300]}")
                await _mark_backtest_failed(db, agent_id, backtest_id,
                                             "claude_agent", f"preflight: {preflight_err[:300]}")
            return

        max_attempts = 3
        last_error = ""

        # F1: hard timeout on the full query() generator
        BACKTEST_QUERY_TIMEOUT = int(os.environ.get("BACKTEST_QUERY_TIMEOUT_SECONDS", "1800"))

        for attempt in range(1, max_attempts + 1):
            try:
                from claude_agent_sdk import ClaudeAgentOptions, query

                prompt = _build_backtest_prompt(agent_id, config, work_dir)
                options = ClaudeAgentOptions(
                    cwd=str(work_dir),
                    permission_mode="dontAsk",
                    allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
                )

                # F1: announce BEFORE entering the loop so we can tell "never
                # called" from "called but hanging"
                async for db in _get_session():
                    await _syslog(db, agent_id, backtest_id, "sdk_query_begin", 2,
                                  f"Calling claude_agent_sdk.query() "
                                  f"(attempt {attempt}/{max_attempts}, "
                                  f"timeout={BACKTEST_QUERY_TIMEOUT}s)")

                last_text = ""
                hit_error_message = False
                first_message_seen = False
                _total_input_tokens = 0
                _total_output_tokens = 0

                async def _consume_query() -> bool:
                    """Inner coroutine so we can wrap the whole generator in wait_for."""
                    nonlocal last_text, hit_error_message, first_message_seen
                    nonlocal _total_input_tokens, _total_output_tokens
                    async for message in query(prompt=prompt, options=options):
                        if not first_message_seen:
                            first_message_seen = True
                            async for db in _get_session():
                                await _syslog(db, agent_id, backtest_id,
                                              "sdk_first_message", 1,
                                              f"First SDK message received: {type(message).__name__}")
                        if hasattr(message, "content") and isinstance(message.content, list):
                            for block in message.content:
                                if hasattr(block, "text"):
                                    last_text = block.text[-500:]
                        if hasattr(message, "session_id"):
                            sid = message.session_id
                            _session_ids[str(agent_id)] = sid
                            async for db in _get_session():
                                await self._update_session(db, session_row_id, session_id=sid)
                        # Accumulate token usage from any message that carries it
                        _usage = getattr(message, "usage", None)
                        if _usage is not None:
                            if hasattr(_usage, "input_tokens"):
                                _total_input_tokens += int(_usage.input_tokens or 0)
                                _total_output_tokens += int(_usage.output_tokens or 0)
                            elif isinstance(_usage, dict):
                                _total_input_tokens += int(_usage.get("input_tokens", 0))
                                _total_output_tokens += int(_usage.get("output_tokens", 0))
                        if hasattr(message, "is_error") and getattr(message, "is_error", False):
                            hit_error_message = True
                            err_msg = f"Claude agent error: {last_text[:500]}"
                            if _is_credit_error(last_text):
                                logger.error("[backtest] Anthropic raw error for %s: %s %s", agent_id, last_text[:400], _extract_rate_limit_info(last_text))
                                err_msg = _format_credit_error(last_text)
                            async for db in _get_session():
                                await self._update_session(db, session_row_id, status="error",
                                                           error=err_msg)
                                await _mark_backtest_failed(db, agent_id, backtest_id, "claude_agent", err_msg[:500])
                            break
                    return hit_error_message

                try:
                    hit_error_message = await asyncio.wait_for(
                        _consume_query(), timeout=BACKTEST_QUERY_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    logger.error("[backtester] SDK query hung past %ds for agent %s",
                                 BACKTEST_QUERY_TIMEOUT, agent_id)
                    async for db in _get_session():
                        await self._update_session(db, session_row_id, status="error",
                                                   error=f"sdk_timeout_after_{BACKTEST_QUERY_TIMEOUT}s")
                        await _syslog(db, agent_id, backtest_id, "sdk_timeout", 3,
                                      f"Claude SDK query hung >{BACKTEST_QUERY_TIMEOUT}s without completing "
                                      f"(first_message_seen={first_message_seen}). "
                                      f"Check /api/v2/admin/claude-sdk-check for diagnostics.")
                        await _mark_backtest_failed(db, agent_id, backtest_id, "claude_agent",
                                                     f"sdk_timeout_{BACKTEST_QUERY_TIMEOUT}s")
                    return

                if hit_error_message:
                    return

                # Record token usage from this SDK run (best-effort, non-fatal)
                if _total_input_tokens > 0 or _total_output_tokens > 0:
                    try:
                        from apps.api.src.services.token_tracker import record_usage
                        await record_usage(
                            instance_id=None,
                            agent_id=agent_id,
                            model="claude-sonnet",
                            input_tokens=_total_input_tokens,
                            output_tokens=_total_output_tokens,
                        )
                        logger.info("[backtester] recorded %d input + %d output tokens for agent %s",
                                    _total_input_tokens, _total_output_tokens, agent_id)
                    except Exception as _te:
                        logger.debug("[backtester] token usage record failed (non-fatal): %s", _te)

                async for db in _get_session():
                    bt = (await db.execute(
                        select(AgentBacktest).where(AgentBacktest.id == backtest_id)
                    )).scalar_one_or_none()
                    if bt and bt.status not in ("COMPLETED", "FAILED"):
                        await _mark_backtest_completed(db, agent_id, backtest_id)
                    await self._update_session(db, session_row_id, status="completed")

                await self._auto_create_analyst(agent_id, config, work_dir)
                return

            except Exception as exc:
                last_error = str(exc)[:500]
                # Fail-fast on cgroup OOM-kill (SIGKILL = exit code -9). Retrying
                # is guaranteed to fail with the same OOM. Bump phoenix-api memory.
                if "exit code -9" in last_error or "exit code: -9" in last_error:
                    logger.error("Claude SDK OOM-killed (exit -9) for agent %s — not retrying. "
                                 "Bump phoenix-api memory limit in docker-compose.coolify.yml.", agent_id)
                    async for db in _get_session():
                        await self._update_session(db, session_row_id, status="error",
                                                   error="Claude CLI OOM-killed by cgroup (exit -9). Bump phoenix-api memory.")
                        await _syslog(db, agent_id, backtest_id, "sdk_oom", 3,
                                      "Claude CLI OOM-killed (SIGKILL/exit -9). Not retrying. Bump phoenix-api memory limit.")
                        await _mark_backtest_failed(db, agent_id, backtest_id, "claude_agent",
                                                   "Claude CLI OOM-killed (exit -9). Bump phoenix-api memory limit.")
                    break
                # Fail-fast on billing/credit errors — retrying won't help
                if _is_credit_error(last_error):
                    credit_msg = _format_credit_error(last_error)
                    event_key = "rate_limit_error" if _is_rate_limit_error(last_error) else "billing_error"
                    logger.error("[backtest] Anthropic raw error for %s (not retrying): %s %s", agent_id, last_error[:400], _extract_rate_limit_info(last_error))
                    async for db in _get_session():
                        await self._update_session(db, session_row_id, status="error", error=credit_msg[:500])
                        await _syslog(db, agent_id, backtest_id, event_key, 3, credit_msg[:500])
                        await _mark_backtest_failed(db, agent_id, backtest_id, "claude_agent", credit_msg[:500])
                    break
                if attempt < max_attempts:
                    delay = 10 * (2 ** (attempt - 1))
                    logger.warning("Claude SDK attempt %d/%d failed for agent %s: %s — retrying in %ds",
                                   attempt, max_attempts, agent_id, last_error[:200], delay)
                    async for db in _get_session():
                        await _syslog(db, agent_id, backtest_id, "sdk_retry", 3,
                                      f"Claude SDK error (attempt {attempt}/{max_attempts}), retrying in {delay}s: {last_error[:200]}")
                    await asyncio.sleep(delay)
            else:
                    logger.error("Claude SDK failed after %d attempts for agent %s: %s",
                                 max_attempts, agent_id, last_error)

                    # If the Python pipeline completed (models trained), mark as
                    # completed-with-warning rather than failed — models are usable.
                    pipeline_done = any(
                        (work_dir / name).exists()
                        for name in ("evaluation_report.json", "best_model.json", "models")
                    )
                    is_api_transient = any(k in last_error for k in ("424", "429", "529", "overloaded", "Could not serve"))

                    if pipeline_done and is_api_transient:
                        logger.warning(
                            "[backtester] SDK unavailable (API %s) but pipeline complete — "
                            "marking backtest as completed for agent %s",
                            last_error[:80], agent_id,
                        )
                        async for db in _get_session():
                            await self._update_session(db, session_row_id, status="completed",
                                                       error=f"SDK unavailable but pipeline complete: {last_error[:200]}")
                            await _syslog(db, agent_id, backtest_id, "sdk_unavailable_pipeline_ok", 2,
                                          f"Claude SDK returned API error after {max_attempts} attempts, "
                                          f"but all Python pipeline steps completed. Models are usable. "
                                          f"Error: {last_error[:200]}")
                            await _mark_backtest_completed(db, agent_id, backtest_id)
                        await self._auto_create_analyst(agent_id, config, work_dir)
                    else:
                        async for db in _get_session():
                            await self._update_session(db, session_row_id, status="error",
                                                       error=f"SDK failed after {max_attempts} attempts: {last_error[:200]}")
                            await _syslog(db, agent_id, backtest_id, "sdk_failed", 3,
                                          f"Claude SDK failed after {max_attempts} attempts: {last_error[:200]}")
                            await _mark_backtest_failed(db, agent_id, backtest_id, "claude_agent",
                                                       f"SDK failed after {max_attempts} attempts: {last_error[:300]}")

        _running_tasks.pop(str(agent_id), None)

    async def _auto_create_analyst(
        self, agent_id: uuid.UUID, config: dict, backtest_work_dir: Path
    ) -> None:
        """After successful backtest, populate the Agent.manifest from backtest artifacts.

        This does NOT start the live agent — that happens after user approval via
        POST /agents/{id}/approve which calls create_analyst().
        """
        async for db in _get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if not agent or agent.status != "BACKTEST_COMPLETE":
                return

            # Look for the live_agent manifest produced by create_live_agent.py (step 12)
            # backtest_work_dir is the versioned subdir (e.g. .../v3/)
            manifest_paths = [
                backtest_work_dir / "live_agent" / "manifest.json",
                backtest_work_dir / "manifest.json",
            ]
            manifest = None
            for mp in manifest_paths:
                if mp.exists():
                    try:
                        manifest = json.loads(mp.read_text())
                        break
                    except Exception as e:
                        logger.warning("Failed to load manifest %s: %s", mp, e)

            if manifest:
                # Default consolidation_enabled=true so wiki pipeline activates
                manifest.setdefault("consolidation_enabled", True)
                agent.manifest = manifest
                identity = manifest.get("identity", {})
                if identity.get("character"):
                    agent.current_mode = "conservative"  # Safe default; user picks at approval
                models_info = manifest.get("models", {})
                if models_info.get("primary"):
                    agent.model_type = models_info["primary"]
                if models_info.get("accuracy") is not None:
                    agent.model_accuracy = float(models_info["accuracy"])
                agent.updated_at = datetime.now(timezone.utc)
                logger.info("Loaded manifest for agent %s with %d rules", agent_id,
                            len(manifest.get("rules", [])))
            else:
                logger.warning("No manifest found for agent %s in %s — agent.manifest unchanged",
                               agent_id, backtest_work_dir)

            await _syslog(db, agent_id, None, "auto_create_analyst", 95,
                          f"Backtest complete — manifest {'loaded' if manifest else 'not found'}")
            await db.commit()

        logger.info("Backtest manifest loaded for agent %s, awaiting user approval", agent_id)

    # ------------------------------------------------------------------
    # Analyst (live trading) agent
    # ------------------------------------------------------------------

    async def create_analyst(
        self, agent_id: uuid.UUID, config: dict | None = None
    ) -> str:
        """Start a live trading Claude Code agent session."""
        # Phase H7 budget check
        try:
            from apps.api.src.services.budget_enforcer import check_budget
            budget = await check_budget(agent_id)
            if not budget.get("ok"):
                logger.warning("Analyst spawn rejected for %s: %s",
                               agent_id, budget.get("reason"))
                return f"BUDGET_EXCEEDED:{budget.get('reason')}"
        except Exception as exc:
            logger.warning("Budget check failed for %s, allowing: %s", agent_id, exc)

        agent_key = str(agent_id)
        if agent_key in _running_tasks and not _running_tasks[agent_key].done():
            return agent_key

        async for db in _get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if not agent:
                logger.warning("[gateway] create_analyst: agent %s not found", agent_id)
                return ""
            if agent.status not in ("BACKTEST_COMPLETE", "APPROVED", "PAPER", "RUNNING", "PAUSED"):
                logger.warning(
                    "[gateway] create_analyst rejected %s (name=%s): status=%s not eligible",
                    agent_id, agent.name, agent.status,
                )
                return f"NOT_ELIGIBLE:{agent.status}"

            work_dir = await self._prepare_analyst_directory(agent, db)
            session_row_id = uuid.uuid4()
            db.add(AgentSession(
                id=session_row_id,
                agent_id=agent_id,
                agent_type="analyst",
                status="starting",
                working_dir=str(work_dir),
                config=config or {},
                trading_mode="paper" if agent.status == "PAPER" else "live",
            ))
            if agent.status != "PAPER":
                agent.status = "RUNNING"
            # PAPER agents: status stays "PAPER"; only worker_status changes
            agent.worker_status = "STARTING"
            agent.updated_at = datetime.now(timezone.utc)
            await db.commit()

        task = asyncio.create_task(
            self._run_analyst(agent_id, work_dir, session_row_id)
        )
        _running_tasks[agent_key] = task
        return str(session_row_id)

    async def _run_analyst(
        self,
        agent_id: uuid.UUID,
        work_dir: Path,
        session_row_id: uuid.UUID,
        resume: bool = False,
    ) -> None:
        """Run the live trading agent as a Claude Code session.

        Phase H5: bounded by `_live_agent_sem` (default 20 concurrent).
        """
        async with _live_agent_sem:
            await self._run_analyst_inner(agent_id, work_dir, session_row_id, resume)

    async def _run_analyst_inner(
        self,
        agent_id: uuid.UUID,
        work_dir: Path,
        session_row_id: uuid.UUID,
        resume: bool = False,
    ) -> None:
        """Original analyst body."""
        agent_key = str(agent_id)

        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            logger.error("claude-agent-sdk not installed — cannot start live agent")
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error="claude-agent-sdk not installed")
                agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                if agent:
                    agent.worker_status = "ERROR"
                    agent.updated_at = datetime.now(timezone.utc)
                await db.commit()
            return

        async for db in _get_session():
            await self._update_session(db, session_row_id, status="running")
            agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if agent:
                agent.worker_status = "RUNNING"
                agent.updated_at = datetime.now(timezone.utc)
            db.add(SystemLog(
                id=uuid.uuid4(), source="agent", level="INFO", service="agent-gateway",
                agent_id=agent_key,
                message=f"Live agent {'resumed' if resume else 'started'} in {work_dir}",
            ))
            await db.commit()

        # Prefix with `export HOME=<work_dir>` so robin_stocks writes its session
        # pickle into the persistent .tokens/ dir, surviving container restarts.
        home_export = f"First, run: `export HOME={work_dir}` so any Robinhood session gets cached in the agent's working directory (.tokens/ subdir). "

        # -------------------------------------------------------------------
        # Smart Context injection (opt-in via ENABLE_SMART_CONTEXT=true)
        # Falls back gracefully — never blocks the analyst from starting.
        # -------------------------------------------------------------------
        smart_context_prefix = ""
        if ENABLE_SMART_CONTEXT:
            try:
                async for db in _get_session():
                    builder = ContextBuilderService(db)
                    ctx_payload = await builder.build(
                        agent_id=agent_id,
                        session_type="trading",
                        signal=None,
                    )
                    ctx_str = ctx_payload.to_context_string()
                    if ctx_str:
                        smart_context_prefix = (
                            f"## Smart Context (dynamic knowledge injection):\n{ctx_str}\n\n"
                        )
                    asyncio.create_task(builder.save_audit(ctx_payload))
                    break
            except Exception as _ctx_exc:
                logger.warning("[agent_gateway] smart context failed for %s: %s", agent_id, _ctx_exc)

        prompt = (
            home_export +
            smart_context_prefix +
            "You are now live. Read CLAUDE.md for your full instructions. "
            "FIRST: run `bash startup.sh` to start the signal consumer (live_pipeline.py). "
            "This is mandatory — without it you will not receive any Discord signals. "
            "Then run pre-market analysis and report your status to Phoenix.\n\n"
            "After startup, enter a MONITORING LOOP — you must stay alive indefinitely:\n"
            "1. Every 5 minutes, check `cat pipeline_status.json` and `tail -10 live_pipeline.log` to verify the pipeline is healthy.\n"
            "2. Report a heartbeat to Phoenix via `python3 tools/report_to_phoenix.py --config config.json --action heartbeat`.\n"
            "3. Check for any new signals in `trades.log` and report them.\n"
            "4. If pipeline PID is dead, restart it with `bash startup.sh`.\n"
            "5. Sleep 300 seconds (`sleep 300`) and repeat from step 1.\n\n"
            "NEVER exit this loop. You must stay alive to handle trade signals and user messages. "
            "If you have nothing to do, sleep and check again. Do NOT finish your session."
        )
        if resume:
            prompt = (
                home_export +
                smart_context_prefix +
                "Resume your live trading session. Check your current positions in positions.json. "
                "FIRST: run `bash startup.sh` to restart the signal consumer if not already running. "
                "Then continue monitoring. Report your resumed status to Phoenix.\n\n"
                "Enter the MONITORING LOOP — you must stay alive indefinitely:\n"
                "1. Every 5 minutes, check `cat pipeline_status.json` and `tail -10 live_pipeline.log`.\n"
                "2. Report a heartbeat to Phoenix.\n"
                "3. If pipeline PID is dead, restart it with `bash startup.sh`.\n"
                "4. Sleep 300 seconds and repeat.\n\n"
                "NEVER exit this loop. Stay alive to handle trade signals and user messages."
            )

        # Smart Context Builder (feature-flagged)
        if os.environ.get("ENABLE_SMART_CONTEXT", "false").lower() == "true":
            try:
                async for db in _get_session():
                    builder = ContextBuilderService(db)
                    ctx = await builder.build(
                        agent_id=agent_id,
                        session_type="trading",
                    )
                    context_str = ctx.to_context_string()
                    if context_str:
                        prompt = context_str + "\n\n" + prompt
                    logger.info(
                        "[context_builder] Built context: %d tokens, %d wiki entries",
                        ctx.total_tokens_estimated,
                        ctx.wiki_entries_injected,
                    )
                    # Best-effort audit save
                    await builder.save_audit(ctx)
            except Exception as _ce:
                logger.debug("[context_builder] non-fatal: %s", _ce)

        options = ClaudeAgentOptions(
            cwd=str(work_dir),
            permission_mode="dontAsk",
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        session_id = _session_ids.get(agent_key)
        if session_id and resume:
            options.resume = session_id

        try:
            last_text = ""
            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "content") and isinstance(message.content, list):
                    for block in message.content:
                        if hasattr(block, "text") and block.text:
                            last_text = block.text[-500:]
                            asyncio.create_task(_persist_agent_log(
                                agent_id, "INFO", block.text[:2000],
                                {"msg_type": "assistant_text"},
                            ))
                        elif hasattr(block, "name") and hasattr(block, "input"):
                            # Tool use block (e.g. Bash, Read)
                            tool_name = getattr(block, "name", "tool")
                            tool_input = getattr(block, "input", {})
                            cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else str(tool_input)
                            asyncio.create_task(_persist_agent_log(
                                agent_id, "INFO",
                                f"[{tool_name}] {cmd[:300]}",
                                {"msg_type": "tool_use", "tool": tool_name},
                            ))
                if hasattr(message, "session_id"):
                    _session_ids[agent_key] = message.session_id
                    async for db in _get_session():
                        await self._update_session(db, session_row_id,
                                                   session_id=message.session_id)
                if hasattr(message, "is_error") and getattr(message, "is_error", False):
                    err_msg = f"Agent error: {last_text[:500]}"
                    is_rate_limit = _is_rate_limit_error(last_text)
                    if _is_credit_error(last_text):
                        logger.error("[analyst] Anthropic raw error for %s: %s %s", agent_id, last_text[:400], _extract_rate_limit_info(last_text))
                        err_msg = _format_credit_error(last_text)
                    asyncio.create_task(_persist_agent_log(
                        agent_id, "ERROR", err_msg, {"msg_type": "sdk_error"}
                    ))
                    async for db in _get_session():
                        await self._update_session(db, session_row_id, status="error",
                                                   error=err_msg)
                        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                        if agent:
                            # Rate limits are temporary — set STOPPED so keepalive re-spawns automatically.
                            # Hard billing failures require human action, so set ERROR.
                            agent.worker_status = "STOPPED" if is_rate_limit else "ERROR"
                            agent.updated_at = datetime.now(timezone.utc)
                        await db.commit()
                    return

            async for db in _get_session():
                await self._update_session(db, session_row_id, status="completed")
                agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                if agent:
                    agent.worker_status = "STOPPED"
                    agent.updated_at = datetime.now(timezone.utc)
                await db.commit()

        except asyncio.CancelledError:
            logger.info("Live agent %s cancelled (pause/stop)", agent_id)
            raise
        except Exception as exc:
            exc_str = str(exc)[:500]
            err_msg = exc_str
            if _is_credit_error(exc_str):
                logger.error("[analyst] Anthropic raw exception for %s: %s %s", agent_id, exc_str[:400], _extract_rate_limit_info(exc_str))
                err_msg = _format_credit_error(exc_str)
            logger.exception("Live agent %s crashed: %s", agent_id, err_msg[:200])
            asyncio.create_task(_persist_agent_log(
                agent_id, "ERROR", f"Agent crashed: {err_msg}", {"msg_type": "crash"}
            ))
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error=err_msg[:500])
                agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                if agent:
                    agent.worker_status = "ERROR"
                    agent.updated_at = datetime.now(timezone.utc)
                await db.commit()
        finally:
            _running_tasks.pop(agent_key, None)

    @staticmethod
    def _is_pipeline_alive(work_dir: Path) -> bool:
        """Check if the agent's live_pipeline process is still running."""
        pid_file = work_dir / "pipeline.pid"
        if not pid_file.exists():
            return False
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # signal 0 = existence check
            return True
        except (ValueError, OSError):
            return False

    async def _prepare_analyst_directory(self, agent: Agent, session) -> Path:
        """Build the analyst agent's working directory with all artifacts."""
        work_dir = DATA_DIR / "live_agents" / str(agent.id)
        work_dir.mkdir(parents=True, exist_ok=True)

        pipeline_alive = self._is_pipeline_alive(work_dir)

        for subdir in ("tools", "skills"):
            src = LIVE_TEMPLATE / subdir
            dst = work_dir / subdir
            if src.exists():
                if pipeline_alive and subdir == "tools":
                    # Pipeline is running — selectively copy tools, skip files
                    # that the pipeline is actively using to avoid disruption.
                    _PIPELINE_FILES = {"live_pipeline.py", "discord_redis_consumer.py"}
                    dst.mkdir(exist_ok=True)
                    for item in src.iterdir():
                        if item.name in _PIPELINE_FILES:
                            logger.debug(
                                "[prepare_dir] Skipping %s (pipeline alive)", item.name
                            )
                            continue
                        target = dst / item.name
                        if item.is_dir():
                            if target.exists():
                                shutil.rmtree(target)
                            shutil.copytree(item, target)
                        else:
                            shutil.copy2(item, target)
                else:
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)

        # .claude/commands/ is copied verbatim; settings.json is written dynamically
        # (with credentials injected) further down after config.json is built.
        commands_src = LIVE_TEMPLATE / ".claude" / "commands"
        if commands_src.exists():
            commands_dst = work_dir / ".claude" / "commands"
            commands_dst.parent.mkdir(exist_ok=True)
            if commands_dst.exists():
                shutil.rmtree(commands_dst)
            shutil.copytree(commands_src, commands_dst)

        # Find latest backtest version directory
        bt_work_dir = DATA_DIR / f"backtest_{agent.id}"
        models_src = None
        latest_pointer = bt_work_dir / "latest.json"
        if latest_pointer.exists():
            try:
                latest = json.loads(latest_pointer.read_text())
                version_dir = Path(latest.get("output_dir", ""))
                if (version_dir / "models").exists():
                    models_src = version_dir / "models"
            except Exception:
                pass
        # Fall back to legacy paths if no latest pointer
        if models_src is None or not models_src.exists():
            for candidate in [bt_work_dir / "output" / "models",
                              bt_work_dir / "output_current" / "models"]:
                if candidate.exists():
                    models_src = candidate
                    break

        if models_src and models_src.exists():
            models_dst = work_dir / "models"
            if models_dst.exists():
                shutil.rmtree(models_dst)
            shutil.copytree(models_src, models_dst)

        manifest = agent.manifest or {}
        config_data = agent.config or {}
        api_url = _get_api_url()

        agent_config = {
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "channel_name": agent.channel_name or "",
            "analyst_name": agent.analyst_name or "",
            "current_mode": agent.current_mode or "conservative",
            "phoenix_api_url": api_url,
            "phoenix_api_key": agent.phoenix_api_key or "",
            "discord_token": config_data.get("discord_token", ""),
            "channel_id": config_data.get("channel_id",
                                          config_data.get("selected_channel", {}).get("channel_id", "")),
            "server_id": config_data.get("server_id", ""),
            "risk": manifest.get("risk", config_data.get("risk_params", {})),
            "risk_params": manifest.get("risk", config_data.get("risk_params", {})),
            "modes": manifest.get("modes", {}),
            "rules": manifest.get("rules", []),
            "models": manifest.get("models", {}),
            "knowledge": manifest.get("knowledge", {}),
        }

        # Resolve primary connector_id for Redis stream key alignment (Story 2.1)
        connector_ids = (agent.config.get("connector_ids") or []) if agent.config else []
        primary_connector_id = str(connector_ids[0]) if connector_ids else ""
        agent_config["connector_id"] = primary_connector_id

        agent_config["redis_url"] = os.environ.get("REDIS_URL", "redis://localhost:6379")

        # Paper mode flag — paper agents never receive broker credentials
        agent_config["paper_mode"] = agent.status == "PAPER"

        # Inject Robinhood credentials under BOTH keys for compatibility:
        # - `robinhood_credentials`: Phoenix spawn format (what robinhood_mcp.py reads)
        # - `robinhood`: local dev / alternate format
        # Paper agents must NOT receive broker credentials (AC2.5.1 safety guard)
        rh_creds = config_data.get("robinhood_credentials") or {}
        if rh_creds and not agent_config["paper_mode"]:
            agent_config["robinhood_credentials"] = rh_creds
            agent_config["robinhood"] = rh_creds

        # Force paper mode if credentials missing for a live agent
        # (safety: prevents the agent from failing hard at trade time)
        current_mode = agent_config.get("current_mode") or "conservative"
        if current_mode not in ("paper",) and not (rh_creds.get("username") and rh_creds.get("password")):
            logger.warning(
                "Agent %s spawning without Robinhood credentials — forcing PAPER mode",
                agent.id,
            )
            agent_config["current_mode"] = "paper"
            agent_config["forced_paper_reason"] = "missing_robinhood_credentials"

        # Persistent .tokens/ dir for robin_stocks session pickle
        # Setting HOME=work_dir makes robin_stocks write ~/.tokens/robinhood.pickle here,
        # so the session survives container restarts (only first login needs TOTP).
        (work_dir / ".tokens").mkdir(exist_ok=True)
        agent_config["_agent_home"] = str(work_dir)

        (work_dir / "config.json").write_text(json.dumps(agent_config, indent=2, default=str))
        # Write .claude/settings.json with credentials injected (belt-and-suspenders
        # over config.json; MCP server reads env vars first, then config.json fallback).
        _write_claude_settings(work_dir, rh_creds, paper_mode=agent_config.get("paper_mode", True))
        self._render_claude_md(agent, manifest, work_dir)

        # Copy startup.sh for auto-starting the signal consumer
        startup_src = LIVE_TEMPLATE / "startup.sh"
        if startup_src.exists():
            startup_dst = work_dir / "startup.sh"
            shutil.copy2(startup_src, startup_dst)
            startup_dst.chmod(0o755)

        return work_dir

    def _render_claude_md(self, agent: Agent, manifest: dict, work_dir: Path) -> None:
        """Render CLAUDE.md from the Jinja2 template (live or paper mode)."""
        is_paper = agent.status == "PAPER"
        template_name = "CLAUDE.md.paper.jinja2" if is_paper else "CLAUDE.md.jinja2"
        template_path = LIVE_TEMPLATE / template_name

        _paper_safety_banner = (
            "# Live Trading Agent: {name}\n\n"
            "## ⚠️ PAPER TRADING MODE — DO NOT EXECUTE REAL TRADES\n\n"
            "Monitor Discord and log paper trades only."
        )
        _live_fallback = "# Live Trading Agent: {name}\n\nMonitor Discord and trade."

        if not template_path.exists():
            if is_paper:
                (work_dir / "CLAUDE.md").write_text(_paper_safety_banner.format(name=agent.name))
            else:
                (work_dir / "CLAUDE.md").write_text(_live_fallback.format(name=agent.name))
            return

        try:
            from jinja2 import Environment, FileSystemLoader

            env = Environment(
                loader=FileSystemLoader(str(LIVE_TEMPLATE)),
                undefined=__import__("jinja2").Undefined,
            )
            template = env.get_template(template_name)

            characters = {
                "balanced-intraday": "You are a balanced intraday trader. You take calculated risks based on model confidence and pattern matches. You cut losses quickly and let winners run with trailing stops.",
                "aggressive-scalper": "You are an aggressive scalper. You act fast on high-confidence signals and aim for quick profits. You take more trades but use tighter stops.",
                "conservative-swing": "You are a conservative swing trader. You wait for high-conviction setups and hold positions for days. You prioritize capital preservation over aggressive returns.",
            }

            identity = manifest.get("identity", {})
            character_key = identity.get("character", "balanced-intraday")

            rendered = template.render(
                identity={
                    "name": agent.name,
                    "channel": agent.channel_name or "",
                    "analyst": agent.analyst_name or "",
                },
                character_description=characters.get(character_key, characters["balanced-intraday"]),
                modes=manifest.get("modes", {}),
                rules=manifest.get("rules", []),
                risk=manifest.get("risk", {}),
                knowledge=manifest.get("knowledge", {}),
                models=manifest.get("models", {}),
            )
            (work_dir / "CLAUDE.md").write_text(rendered)
        except Exception as exc:
            logger.warning("Failed to render CLAUDE.md for agent %s (template=%s): %s", agent.id, template_name, exc)
            if is_paper:
                (work_dir / "CLAUDE.md").write_text(_paper_safety_banner.format(name=agent.name))
            else:
                (work_dir / "CLAUDE.md").write_text(_live_fallback.format(name=agent.name))

    # ------------------------------------------------------------------
    # Lifecycle: stop, pause, resume, status
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Analyst persona agent (Phase 1 — signal generator)
    # ------------------------------------------------------------------

    async def create_analyst_agent(
        self,
        agent_id: uuid.UUID,
        config: dict,
        mode: str = "signal_intake",
    ) -> str:
        """Spawn a persona-driven analyst agent session.

        Creates an AgentSession row and spawns the analyst_agent.py script.
        Returns session_row_id as string.

        Args:
            agent_id: UUID of the analyst agent row.
            config: Agent config dict (must include 'persona_id').
            mode: Workflow mode ('signal_intake' or 'pre_market').

        Returns:
            session_row_id as string.
        """
        try:
            from apps.api.src.services.budget_enforcer import check_budget
            budget = await check_budget(agent_id)
            if not budget.get("ok"):
                logger.warning("Analyst agent spawn rejected for %s: %s",
                               agent_id, budget.get("reason"))
                return f"BUDGET_EXCEEDED:{budget.get('reason')}"
        except Exception as exc:
            logger.warning("Budget check failed for %s, allowing: %s", agent_id, exc)

        persona_id = config.get("persona", config.get("persona_id", "aggressive_momentum"))
        work_dir = DATA_DIR / f"analyst_{agent_id}"
        work_dir.mkdir(parents=True, exist_ok=True)

        config_path = work_dir / "config.json"
        config_path.write_text(json.dumps(config, indent=2, default=str))

        session_row_id = uuid.uuid4()
        async for db in _get_session():
            db.add(AgentSession(
                id=session_row_id,
                agent_id=agent_id,
                agent_type="analyst",
                status="starting",
                working_dir=str(work_dir),
                config=config,
            ))
            await db.commit()

        task = asyncio.create_task(
            self._run_analyst_agent(agent_id, persona_id, config, work_dir, session_row_id, mode)
        )
        _running_tasks[str(agent_id)] = task
        return str(session_row_id)

    async def _run_analyst_agent(
        self,
        agent_id: uuid.UUID,
        persona_id: str,
        config: dict,
        work_dir: Path,
        session_row_id: uuid.UUID,
        mode: str = "signal_intake",
    ) -> None:
        """Run the analyst agent script via Claude Code."""
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            logger.error("claude-agent-sdk not installed — cannot start analyst persona agent")
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error="claude-agent-sdk not installed")
            return

        async for db in _get_session():
            await self._update_session(db, session_row_id, status="running")

        config_str = json.dumps(config, default=str).replace('"', '\\"')
        agent_script = str(REPO_ROOT / "agents" / "analyst" / "analyst_agent.py")

        prompt = (
            f"Run the analyst agent script: "
            f"python {agent_script} "
            f"--agent_id {agent_id} "
            f"--persona_id {persona_id} "
            f"--mode {mode} "
            f"--config '{config_str}'"
        )

        options = ClaudeAgentOptions(
            cwd=str(work_dir),
            permission_mode="dontAsk",
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        try:
            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "session_id"):
                    _session_ids[str(agent_id)] = message.session_id
                    async for db in _get_session():
                        await self._update_session(db, session_row_id,
                                                   session_id=message.session_id)
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="completed")
        except Exception as exc:
            logger.error("Analyst persona agent failed for %s: %s", agent_id, exc)
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error=str(exc)[:500])

    # ------------------------------------------------------------------
    # Position sub-agent (Phase 1.3)
    # ------------------------------------------------------------------

    async def create_position_agent(
        self, parent_agent_id: uuid.UUID, position_data: dict
    ) -> str:
        """Spawn a position monitor sub-agent for a specific open position.

        Each position gets its own Claude Code session that monitors exit
        conditions and self-terminates when the position is closed.
        """
        ticker = position_data.get("ticker", "UNKNOWN")
        side = position_data.get("side", "buy")
        position_id = position_data.get("position_id") or str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Working directory: data/live_agents/{parent}/positions/{ticker}_{ts}/
        parent_dir = DATA_DIR / "live_agents" / str(parent_agent_id)
        work_dir = parent_dir / "positions" / f"{ticker}_{timestamp}"
        work_dir.mkdir(parents=True, exist_ok=True)

        # Copy position-monitor template files
        for subdir in ("tools", "skills"):
            src = POSITION_MONITOR_TEMPLATE / subdir
            dst = work_dir / subdir
            if dst.exists():
                shutil.rmtree(dst)
            if src.exists():
                shutil.copytree(src, dst)

        # Copy CLAUDE.md
        claude_src = POSITION_MONITOR_TEMPLATE / "CLAUDE.md"
        if claude_src.exists():
            shutil.copy2(claude_src, work_dir / "CLAUDE.md")

        # Inherit parent's robinhood_mcp.py and report_to_phoenix.py for execution
        live_tools = LIVE_TEMPLATE / "tools"
        for inherited in ("robinhood_mcp.py", "report_to_phoenix.py"):
            src = live_tools / inherited
            if src.exists():
                shutil.copy2(src, work_dir / "tools" / inherited)

        position_data.setdefault("position_id", position_id)
        position_data.setdefault("status", "open")
        position_data.setdefault("opened_at", datetime.now(timezone.utc).isoformat())

        # Build config from parent agent; persist analyst_exit_profile in position.json for tools
        async for db in _get_session():
            parent = (await db.execute(
                select(Agent).where(Agent.id == parent_agent_id)
            )).scalar_one_or_none()
            if not parent:
                logger.error("Parent agent %s not found", parent_agent_id)
                return ""

            analyst_exit_profile: dict = {}
            try:
                from shared.db.models.analyst_profile import AnalystProfile as _AnalystProfile
                aname = position_data.get("analyst")
                trail = position_data.get("decision_trail")
                if not aname and isinstance(trail, dict):
                    aname = trail.get("analyst") or trail.get("author")
                elif not aname and isinstance(trail, str):
                    try:
                        tr = json.loads(trail or "{}")
                        aname = tr.get("analyst") or tr.get("author")
                    except (json.JSONDecodeError, TypeError):
                        aname = None
                if aname:
                    prof = (await db.execute(
                        select(_AnalystProfile).where(_AnalystProfile.analyst_name == str(aname).strip())
                    )).scalar_one_or_none()
                    if prof:
                        analyst_exit_profile = _analyst_profile_to_dict(prof)
            except Exception as e:
                logger.debug("analyst_exit_profile load skipped: %s", e)

            position_data["analyst_exit_profile"] = analyst_exit_profile
            (work_dir / "position.json").write_text(json.dumps(position_data, indent=2, default=str))

            api_url = _get_api_url()
            position_config = {
                "agent_id": str(parent_agent_id),
                "parent_agent_id": str(parent_agent_id),
                "position_id": position_id,
                "phoenix_api_url": api_url,
                "phoenix_api_key": parent.phoenix_api_key or "",
                "channel_id": (parent.config or {}).get("channel_id", ""),
                "discord_token": (parent.config or {}).get("discord_token", ""),
                "robinhood_credentials": (parent.config or {}).get("robinhood_credentials", {}),
                "risk": (parent.manifest or {}).get("risk", {}),
            }
            (work_dir / "config.json").write_text(json.dumps(position_config, indent=2, default=str))
            rh_creds = position_config.get("robinhood_credentials", {})
            paper_mode = position_config.get("paper_mode", True)
            _write_claude_settings(work_dir, rh_creds, paper_mode=paper_mode)

            # Find the parent's active live session to link sub-agent
            parent_session = (await db.execute(
                select(AgentSession)
                .where(AgentSession.agent_id == parent_agent_id,
                       AgentSession.agent_type == "analyst",
                       AgentSession.status.in_(["running", "starting"]))
                .order_by(AgentSession.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()

            session_row_id = uuid.uuid4()
            db.add(AgentSession(
                id=session_row_id,
                agent_id=parent_agent_id,
                agent_type="position_monitor",
                session_role="position_monitor",
                parent_agent_id=parent_session.id if parent_session else None,
                status="starting",
                working_dir=str(work_dir),
                config=position_config,
                position_ticker=ticker,
                position_side=side,
            ))
            await db.commit()

        # Spawn the Claude Code session as an async task
        task_key = f"{parent_agent_id}:{position_id}"
        task = asyncio.create_task(
            self._run_position_agent(parent_agent_id, position_id, work_dir, session_row_id)
        )
        _running_tasks[task_key] = task

        logger.info("Spawned position monitor sub-agent for %s %s in %s",
                    ticker, side, work_dir)
        return str(session_row_id)

    async def _run_position_agent(self, *args, **kwargs) -> None:
        """Phase H5: bounded by `_position_agent_sem` (default 50 concurrent)."""
        async with _position_agent_sem:
            await self._run_position_agent_inner(*args, **kwargs)

    async def _run_position_agent_inner(
        self,
        parent_agent_id: uuid.UUID,
        position_id: str,
        work_dir: Path,
        session_row_id: uuid.UUID,
    ) -> None:
        """Run the position monitor as a Tier 2 micro-agent (or Claude SDK fallback)."""
        task_key = f"{parent_agent_id}:{position_id}"

        # Three-tier: use PositionMicroAgent (Tier 1+2) instead of Claude SDK
        use_micro = os.getenv("POSITION_MONITOR_TIER", "micro") != "sdk"
        if use_micro:
            try:
                from apps.api.src.services.position_micro_agent import PositionMicroAgent

                position_file = work_dir / "position.json"
                position = json.loads(position_file.read_text()) if position_file.exists() else {}
                config_file = work_dir / "config.json"
                config = json.loads(config_file.read_text()) if config_file.exists() else {}

                # Prefer analyst_exit_profile written at spawn; else load from DB
                analyst_patterns = dict(position.get("analyst_exit_profile") or {})
                if not analyst_patterns:
                    try:
                        analyst_name = position.get("analyst") or config.get("analyst_name", "")
                        if not analyst_name:
                            trail = position.get("decision_trail", {})
                            if isinstance(trail, str):
                                trail = json.loads(trail) if trail else {}
                            analyst_name = trail.get("analyst", trail.get("author", ""))
                        if analyst_name:
                            from shared.db.models.analyst_profile import AnalystProfile
                            async for db in _get_session():
                                from sqlalchemy import select as _sel
                                prof = (await db.execute(
                                    _sel(AnalystProfile).where(AnalystProfile.analyst_name == analyst_name)
                                )).scalar_one_or_none()
                                if prof:
                                    analyst_patterns = _analyst_profile_to_dict(prof)
                    except Exception as e:
                        logger.debug("Could not load analyst profile: %s", e)

                agent = PositionMicroAgent(
                    agent_id=parent_agent_id,
                    session_id=session_row_id,
                    position=position,
                    config=config,
                    work_dir=work_dir,
                    analyst_patterns=analyst_patterns,
                )
                _micro_agents[task_key] = agent
                try:
                    result = await agent.run()
                    logger.info("PositionMicroAgent %s finished: %s", session_row_id, result.get("status"))
                finally:
                    _micro_agents.pop(task_key, None)
                    _running_tasks.pop(task_key, None)
                return
            except Exception as e:
                logger.warning("PositionMicroAgent failed, falling back to Claude SDK: %s", e)

        # Fallback: Claude SDK (Tier 3)
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            logger.error("claude-agent-sdk not installed — cannot start position agent")
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error="claude-agent-sdk not installed")
            _running_tasks.pop(task_key, None)
            return

        async for db in _get_session():
            await self._update_session(db, session_row_id, status="running")

        prompt = (
            f"You are a position monitor sub-agent. Read CLAUDE.md and position.json. "
            f"Start the exit monitoring loop by running: "
            f"`python tools/exit_monitor.py --position-id {position_id}`. "
            f"This loop will run continuously until the position is closed, then "
            f"self-terminate. Report all exits to Phoenix as you go."
        )

        options = ClaudeAgentOptions(
            cwd=str(work_dir),
            permission_mode="dontAsk",
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        try:
            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "session_id"):
                    async for db in _get_session():
                        await self._update_session(db, session_row_id,
                                                   session_id=message.session_id)
                if hasattr(message, "is_error") and getattr(message, "is_error", False):
                    async for db in _get_session():
                        await self._update_session(db, session_row_id, status="error",
                                                   error="Position agent error")
                    return

            async for db in _get_session():
                await self._update_session(db, session_row_id, status="completed")

        except asyncio.CancelledError:
            logger.info("Position agent %s cancelled", task_key)
            raise
        except Exception as exc:
            logger.exception("Position agent %s crashed", task_key)
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error=str(exc)[:500])
        finally:
            _running_tasks.pop(task_key, None)

    async def terminate_position_agent(self, session_row_id: uuid.UUID, reason: str) -> dict:
        """Self-termination endpoint for position agents."""
        async for db in _get_session():
            sess = (await db.execute(
                select(AgentSession).where(AgentSession.id == session_row_id)
            )).scalar_one_or_none()
            if not sess:
                return {"status": "not_found"}

            # Cancel the running task
            task_key = f"{sess.agent_id}:{sess.config.get('position_id', '')}"
            task = _running_tasks.get(task_key)
            if task and not task.done():
                task.cancel()
            _running_tasks.pop(task_key, None)
            _micro_agents.pop(task_key, None)

            sess.status = "stopped"
            sess.stopped_at = datetime.now(timezone.utc)
            sess.error_message = f"Self-terminated: {reason}"
            await db.commit()

        return {"status": "terminated", "session_id": str(session_row_id), "reason": reason}

    async def list_position_agents(self, parent_agent_id: uuid.UUID) -> list[dict]:
        """List active position monitor sub-agents for a parent analyst."""
        result = []
        async for db in _get_session():
            rows = (await db.execute(
                select(AgentSession)
                .where(
                    AgentSession.agent_id == parent_agent_id,
                    AgentSession.session_role == "position_monitor",
                    AgentSession.status.in_(["running", "starting"]),
                )
                .order_by(AgentSession.started_at.desc())
            )).scalars().all()
            for s in rows:
                result.append({
                    "session_row_id": str(s.id),
                    "ticker": s.position_ticker,
                    "side": s.position_side,
                    "status": s.status,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "config": s.config,
                })
        return result

    async def route_sell_signal_to_monitors(
        self, agent_id: uuid.UUID, ticker: str, signal: dict
    ) -> dict:
        """Route an analyst sell signal to all active position monitors for a ticker.

        Fixes the routing gap where receive_sell_signal() was never called.
        """
        routed_to: list[str] = []
        missed: list[str] = []

        for key, micro in list(_micro_agents.items()):
            if not key.startswith(str(agent_id)):
                continue
            if getattr(micro, "ticker", "").upper() == ticker.upper():
                try:
                    micro.receive_sell_signal(signal)
                    routed_to.append(key)
                    logger.info("Sell signal routed to monitor %s for %s", key, ticker)
                except Exception as e:
                    logger.warning("Failed to route sell signal to %s: %s", key, e)
                    missed.append(key)

        if not routed_to and not missed:
            logger.info("No active position monitors for %s/%s — sell signal unroutable", agent_id, ticker)

        return {
            "ticker": ticker,
            "routed_to": routed_to,
            "missed": missed,
            "total_monitors": len(_micro_agents),
        }

    # ------------------------------------------------------------------
    # Supervisor agent (Phase 4)
    # ------------------------------------------------------------------

    async def create_supervisor_agent(self, config: dict | None = None) -> str:
        """Spawn the AutoResearch supervisor agent (singleton, one per server).

        Triggered by Claude Code cron at 4:30 PM ET after market close.
        Runs daily analysis and stages improvements for user approval.
        """
        config = config or {}
        work_dir = DATA_DIR / "supervisor" / datetime.now(timezone.utc).strftime("%Y%m%d")
        work_dir.mkdir(parents=True, exist_ok=True)

        # Copy supervisor template
        for subdir in ("tools", "skills"):
            src = SUPERVISOR_TEMPLATE / subdir
            dst = work_dir / subdir
            if dst.exists():
                shutil.rmtree(dst)
            if src.exists():
                shutil.copytree(src, dst)
        claude_src = SUPERVISOR_TEMPLATE / "CLAUDE.md"
        if claude_src.exists():
            shutil.copy2(claude_src, work_dir / "CLAUDE.md")

        # Write config
        api_url = _get_api_url()
        sup_config = {
            "agent_type": "supervisor",
            "phoenix_api_url": api_url,
            "phoenix_api_key": config.get("phoenix_api_key", ""),
            "lookback_days": config.get("lookback_days", 30),
            **config,
        }
        (work_dir / "config.json").write_text(json.dumps(sup_config, indent=2, default=str))

        # Create AgentSession entry (no parent agent — supervisor is system-level)
        session_row_id = uuid.uuid4()
        sup_agent_uuid = _SUPERVISOR_AGENT_UUID
        async for db in _get_session():
            # Ensure the parent agents row exists before the FK-constrained INSERT.
            # Guards against the startup seed failing silently (DB not ready, schema
            # drift, or the agents table being wiped in dev).
            await _ensure_system_agent(db, sup_agent_uuid, "Supervisor Agent")
            db.add(AgentSession(
                id=session_row_id,
                agent_id=sup_agent_uuid,
                agent_type="supervisor",
                session_role="supervisor",
                status="starting",
                working_dir=str(work_dir),
                config=sup_config,
            ))
            # belt-and-suspenders: get_session() also auto-commits on exit
            await db.commit()

        # Spawn the Claude session
        task_key = f"supervisor:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        task = asyncio.create_task(
            self._run_supervisor(work_dir, session_row_id, task_key)
        )
        _running_tasks[task_key] = task
        logger.info("Spawned supervisor agent in %s", work_dir)
        return str(session_row_id)

    async def _run_supervisor(self, work_dir: Path, session_row_id: uuid.UUID, task_key: str) -> None:
        """Run the supervisor as Tier 1+2 scheduled runner (or Claude SDK fallback)."""
        use_runner = os.getenv("SCHEDULED_AGENT_TIER", "runner") != "sdk"
        if use_runner:
            try:
                from apps.api.src.services.auto_research import run_auto_research
                from apps.api.src.services.scheduled_agent_runner import ScheduledAgentRunner

                runner = ScheduledAgentRunner(
                    agent_type="supervisor",
                    agent_id=_SUPERVISOR_AGENT_UUID,
                    session_id=session_row_id,
                    work_dir=work_dir,
                )
                await runner.run()

                # Run auto-research after supervisor pipeline
                try:
                    research_result = await run_auto_research()
                    logger.info("Auto-research completed: %s", research_result.get("agents_analyzed"))
                except Exception as e:
                    logger.warning("Auto-research failed (non-fatal): %s", e)

                _running_tasks.pop(task_key, None)
                return
            except Exception as e:
                logger.warning("ScheduledAgentRunner failed for supervisor, falling back to SDK: %s", e)

        # Fallback: Claude SDK (Tier 3)
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            logger.error("claude-agent-sdk unavailable for supervisor")
            _running_tasks.pop(task_key, None)
            return

        async for db in _get_session():
            await self._update_session(db, session_row_id, status="running")

        prompt = (
            "You are the Phoenix Supervisor (AutoResearch). Read CLAUDE.md and run "
            "the daily routine: collect today's data, analyze performance, propose "
            "improvements, mini-backtest each, and stage passing improvements via "
            "tools/apply_changes.py --stage. Send a summary notification when done."
        )

        options = ClaudeAgentOptions(
            cwd=str(work_dir),
            permission_mode="dontAsk",
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        try:
            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "session_id"):
                    async for db in _get_session():
                        await self._update_session(db, session_row_id,
                                                   session_id=message.session_id)
                if hasattr(message, "is_error") and getattr(message, "is_error", False):
                    async for db in _get_session():
                        await self._update_session(db, session_row_id, status="error",
                                                   error="Supervisor error")
                    return
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="completed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Supervisor crashed")
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error=str(exc)[:500])
        finally:
            _running_tasks.pop(task_key, None)

    # ------------------------------------------------------------------
    # Morning Briefing Agent (first-class, singleton per day)
    # ------------------------------------------------------------------

    async def create_morning_briefing_agent(self, config: dict | None = None) -> str:
        """Spawn the Phoenix Morning Briefing Agent for today's pre-market.

        Singleton per day. If already running for today's date, returns the
        existing task key. Mirrors create_supervisor_agent but uses
        MORNING_BRIEFING_TEMPLATE and a different reserved agent UUID.
        """
        config = config or {}
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        task_key = f"morning_briefing:{day}"
        if task_key in _running_tasks and not _running_tasks[task_key].done():
            return task_key

        work_dir = DATA_DIR / "morning-briefing" / day
        work_dir.mkdir(parents=True, exist_ok=True)

        for subdir in ("tools",):
            src = MORNING_BRIEFING_TEMPLATE / subdir
            dst = work_dir / subdir
            if dst.exists():
                shutil.rmtree(dst)
            if src.exists():
                shutil.copytree(src, dst)
        claude_src = MORNING_BRIEFING_TEMPLATE / "CLAUDE.md"
        if claude_src.exists():
            shutil.copy2(claude_src, work_dir / "CLAUDE.md")

        api_url = _get_api_url()
        mb_config = {
            "agent_type": "morning_briefing",
            "phoenix_api_url": api_url,
            "phoenix_api_key": config.get("phoenix_api_key", ""),
            "lookback_hours": config.get("lookback_hours", 12),
            "target_channels": config.get("target_channels",
                                          ["whatsapp", "telegram", "ws", "db"]),
            "created_at": datetime.now(timezone.utc).isoformat(),
            **config,
        }
        (work_dir / "config.json").write_text(json.dumps(mb_config, indent=2, default=str))

        # Reserved UUID for the morning briefing singleton agent
        mb_agent_uuid = _MORNING_BRIEFING_AGENT_UUID
        session_row_id = uuid.uuid4()
        async for db in _get_session():
            # Ensure the parent agents row exists before the FK-constrained INSERT.
            # Guards against the startup seed failing silently (DB not ready, schema
            # drift, or the agents table being wiped in dev).
            await _ensure_system_agent(db, mb_agent_uuid, "Morning Briefing Agent")
            db.add(AgentSession(
                id=session_row_id,
                agent_id=mb_agent_uuid,
                agent_type="morning_briefing",
                session_role="morning_briefing",
                status="starting",
                working_dir=str(work_dir),
                config=mb_config,
            ))
            # belt-and-suspenders: get_session() also auto-commits on exit
            await db.commit()

        task = asyncio.create_task(
            self._run_morning_briefing(work_dir, session_row_id, task_key)
        )
        _running_tasks[task_key] = task
        logger.info("Spawned morning_briefing agent in %s", work_dir)
        return task_key

    async def _run_morning_briefing(self, work_dir: Path,
                                     session_row_id: uuid.UUID,
                                     task_key: str) -> None:
        """Run the morning briefing as Tier 1+2 runner (or Claude SDK fallback)."""
        use_runner = os.getenv("SCHEDULED_AGENT_TIER", "runner") != "sdk"
        if use_runner:
            try:
                from apps.api.src.services.scheduled_agent_runner import ScheduledAgentRunner

                runner = ScheduledAgentRunner(
                    agent_type="morning_briefing",
                    agent_id=_MORNING_BRIEFING_AGENT_UUID,
                    session_id=session_row_id,
                    work_dir=work_dir,
                )
                await runner.run()
                _running_tasks.pop(task_key, None)
                return
            except Exception as e:
                logger.warning("ScheduledAgentRunner failed for morning_briefing, falling back to SDK: %s", e)

        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            logger.error("claude-agent-sdk unavailable for morning briefing")
            _running_tasks.pop(task_key, None)
            return

        async for db in _get_session():
            await self._update_session(db, session_row_id, status="running")

        prompt = (
            "You are the Phoenix Morning Briefing Agent. Read CLAUDE.md and run "
            "all 5 phases in order: collect overnight events, compile briefing, "
            "wake children, dispatch briefing, then report completion. "
            "This is a one-shot run — exit cleanly when Phase 5 reports success."
        )

        options = ClaudeAgentOptions(
            cwd=str(work_dir),
            permission_mode="dontAsk",
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        try:
            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "session_id"):
                    async for db in _get_session():
                        await self._update_session(
                            db, session_row_id, session_id=message.session_id
                        )
                if hasattr(message, "is_error") and getattr(message, "is_error", False):
                    async for db in _get_session():
                        await self._update_session(
                            db, session_row_id, status="error",
                            error="Morning briefing error",
                        )
                    return
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="completed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Morning briefing crashed")
            async for db in _get_session():
                await self._update_session(
                    db, session_row_id, status="error", error=str(exc)[:500]
                )
        finally:
            _running_tasks.pop(task_key, None)

    # ------------------------------------------------------------------
    # One-shot scheduled agents (daily summary, EOD analysis, trade feedback)
    # ------------------------------------------------------------------

    async def _spawn_one_shot_agent(
        self,
        *,
        template_dir: Path,
        subdir: str,
        agent_type: str,
        reserved_uuid: uuid.UUID,
        prompt: str,
        config: dict | None = None,
    ) -> str:
        """Generic one-shot Claude Code agent spawner used by daily summary,
        EOD analysis, trade feedback, and any other cron-triggered agent.

        Returns a task_key like "{agent_type}:YYYYMMDD". If an agent with the
        same task_key is already running, returns the existing key (singleton
        per day).
        """
        config = config or {}
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        task_key = f"{agent_type}:{day}"
        if task_key in _running_tasks and not _running_tasks[task_key].done():
            return task_key

        work_dir = DATA_DIR / subdir / day
        work_dir.mkdir(parents=True, exist_ok=True)

        # Copy template tools + CLAUDE.md
        tools_src = template_dir / "tools"
        tools_dst = work_dir / "tools"
        if tools_dst.exists():
            shutil.rmtree(tools_dst)
        if tools_src.exists():
            shutil.copytree(tools_src, tools_dst)
        claude_src = template_dir / "CLAUDE.md"
        if claude_src.exists():
            shutil.copy2(claude_src, work_dir / "CLAUDE.md")

        # Write config.json with Phoenix API connection info
        api_url = _get_api_url()
        agent_config = {
            "agent_type": agent_type,
            "phoenix_api_url": api_url,
            "phoenix_api_key": config.get("phoenix_api_key", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
            **config,
        }
        (work_dir / "config.json").write_text(json.dumps(agent_config, indent=2, default=str))

        # Create AgentSession row so the dashboard can see the run
        session_row_id = uuid.uuid4()
        async for db in _get_session():
            # Ensure the parent agents row exists before the FK-constrained INSERT.
            # Guards against the startup seed failing silently (DB not ready, schema
            # drift, or the agents table being wiped in dev). Covers UUIDs 3, 4, 5.
            await _ensure_system_agent(db, reserved_uuid, _SYSTEM_AGENT_NAMES.get(agent_type, agent_type.replace("_", " ").title() + " Agent"))
            db.add(AgentSession(
                id=session_row_id,
                agent_id=reserved_uuid,
                agent_type=agent_type,
                session_role=agent_type,
                status="starting",
                working_dir=str(work_dir),
                config=agent_config,
            ))
            # belt-and-suspenders: get_session() also auto-commits on exit
            await db.commit()

        task = asyncio.create_task(
            self._run_one_shot_agent(work_dir, session_row_id, task_key, prompt, agent_type)
        )
        _running_tasks[task_key] = task
        logger.info("Spawned %s agent in %s", agent_type, work_dir)
        return task_key

    async def _run_one_shot_agent(
        self,
        work_dir: Path,
        session_row_id: uuid.UUID,
        task_key: str,
        prompt: str,
        agent_type: str,
    ) -> None:
        """Run a one-shot scheduled agent as Tier 1+2 runner (or Claude SDK fallback)."""
        use_runner = os.getenv("SCHEDULED_AGENT_TIER", "runner") != "sdk"
        # Map gateway agent_type names to ScheduledAgentRunner pipeline keys
        runner_type_map = {
            "eod_analysis": "eod_analysis",
            "daily_summary": "daily_summary",
            "trade_feedback": "trade_feedback",
        }
        runner_key = runner_type_map.get(agent_type)
        if use_runner and runner_key:
            try:
                from apps.api.src.services.scheduled_agent_runner import AGENT_PIPELINES, ScheduledAgentRunner

                if runner_key in AGENT_PIPELINES:
                    # Resolve agent_id from the task_key (format: "type:date")
                    agent_id = _SUPERVISOR_AGENT_UUID  # System-level agents share UUID
                    runner = ScheduledAgentRunner(
                        agent_type=runner_key,
                        agent_id=agent_id,
                        session_id=session_row_id,
                        work_dir=work_dir,
                    )
                    await runner.run()
                    _running_tasks.pop(task_key, None)
                    return
            except Exception as e:
                logger.warning("ScheduledAgentRunner failed for %s, falling back to SDK: %s", agent_type, e)

        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            logger.error("claude-agent-sdk unavailable for %s", agent_type)
            _running_tasks.pop(task_key, None)
            return

        # Reuse the backtester preflight so we fail fast if the CLI is broken
        preflight_err = _claude_sdk_preflight()
        if preflight_err:
            logger.error("[%s] preflight failed: %s", agent_type, preflight_err)
            async for db in _get_session():
                await self._update_session(
                    db, session_row_id, status="error",
                    error=f"preflight_failed: {preflight_err[:200]}",
                )
            _running_tasks.pop(task_key, None)
            return

        async for db in _get_session():
            await self._update_session(db, session_row_id, status="running")

        options = ClaudeAgentOptions(
            cwd=str(work_dir),
            permission_mode="dontAsk",
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        timeout_s = int(os.environ.get("ONESHOT_AGENT_TIMEOUT_SECONDS", "1800"))

        async def _pump() -> None:
            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "session_id"):
                    async for db in _get_session():
                        await self._update_session(
                            db, session_row_id, session_id=message.session_id
                        )
                if hasattr(message, "is_error") and getattr(message, "is_error", False):
                    async for db in _get_session():
                        await self._update_session(
                            db, session_row_id, status="error",
                            error=f"{agent_type} error",
                        )
                    return

        try:
            await asyncio.wait_for(_pump(), timeout=timeout_s)
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="completed")
        except asyncio.TimeoutError:
            logger.error("[%s] hit %ds timeout", agent_type, timeout_s)
            async for db in _get_session():
                await self._update_session(
                    db, session_row_id, status="error",
                    error=f"sdk_timeout_after_{timeout_s}s",
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("[%s] crashed", agent_type)
            async for db in _get_session():
                await self._update_session(
                    db, session_row_id, status="error", error=str(exc)[:500]
                )
        finally:
            _running_tasks.pop(task_key, None)

    async def create_daily_summary_agent(self, config: dict | None = None) -> str:
        """Spawn the daily-summary Claude agent. Runs at 17:00 ET."""
        return await self._spawn_one_shot_agent(
            template_dir=DAILY_SUMMARY_TEMPLATE,
            subdir="daily-summary",
            agent_type="daily_summary",
            reserved_uuid=_DAILY_SUMMARY_AGENT_UUID,
            prompt=(
                "You are the Phoenix Daily Summary Agent. Read CLAUDE.md and "
                "run all 3 phases in order: collect today's PnL, compile the "
                "narrative, persist and dispatch. Then exit cleanly."
            ),
            config=config,
        )

    async def create_eod_analysis_agent(self, config: dict | None = None) -> str:
        """Spawn the EOD analysis Claude agent. Runs at 16:45 ET."""
        return await self._spawn_one_shot_agent(
            template_dir=EOD_ANALYSIS_TEMPLATE,
            subdir="eod-analysis",
            agent_type="eod_analysis",
            reserved_uuid=_EOD_ANALYSIS_AGENT_UUID,
            prompt=(
                "You are the Phoenix EOD Analysis Agent. Read CLAUDE.md and "
                "run all 5 phases in order: collect day trades, enrich "
                "outcomes, compute missed metrics, compile the EOD brief, "
                "then persist and dispatch. Exit cleanly when done."
            ),
            config=config,
        )

    async def create_trade_feedback_agent(self, config: dict | None = None) -> str:
        """Spawn the trade-feedback Claude agent. Runs at 03:30 ET."""
        return await self._spawn_one_shot_agent(
            template_dir=TRADE_FEEDBACK_TEMPLATE,
            subdir="trade-feedback",
            agent_type="trade_feedback",
            reserved_uuid=_TRADE_FEEDBACK_AGENT_UUID,
            prompt=(
                "You are the Phoenix Trade Feedback Agent. Read CLAUDE.md and "
                "run all 3 phases: query outcomes, compute bias multipliers, "
                "apply them per-agent and report. Exit cleanly when done."
            ),
            config=config,
        )

    # ------------------------------------------------------------------
    # Specialized agent factories (UW / Social / Strategy)
    # ------------------------------------------------------------------

    async def create_specialized_agent(self, agent_id: uuid.UUID, agent_type: str,
                                        config: dict) -> str:
        """Generic factory for specialized agents (unusual_whales, social_sentiment, strategy).

        These agent types skip the Discord backtesting flow and go straight
        to live operation with their template.
        """
        template_map = {
            "unusual_whales": UW_TEMPLATE,
            "social_sentiment": SOCIAL_TEMPLATE,
            "strategy": STRATEGY_TEMPLATE,
        }
        template_dir = template_map.get(agent_type)
        if not template_dir:
            return ""

        # Build live agent directory
        work_dir = DATA_DIR / "live_agents" / str(agent_id)
        work_dir.mkdir(parents=True, exist_ok=True)

        for subdir in ("tools", "skills"):
            src = template_dir / subdir
            dst = work_dir / subdir
            if dst.exists():
                shutil.rmtree(dst)
            if src.exists():
                shutil.copytree(src, dst)

        # Inherit live-trader-v1 shared tools (robinhood_mcp, report_to_phoenix, agent_comms, decision_engine)
        live_tools = LIVE_TEMPLATE / "tools"
        for shared_tool in ("robinhood_mcp.py", "report_to_phoenix.py",
                            "agent_comms.py", "paper_portfolio.py", "watchlist_manager.py"):
            src = live_tools / shared_tool
            if src.exists():
                shutil.copy2(src, work_dir / "tools" / shared_tool)

        # Copy CLAUDE.md
        claude_src = template_dir / "CLAUDE.md"
        if claude_src.exists():
            shutil.copy2(claude_src, work_dir / "CLAUDE.md")

        # Build config
        async for db in _get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if not agent:
                return ""

            api_url = _get_api_url()
            agent_config = {
                "agent_id": str(agent_id),
                "agent_name": agent.name,
                "agent_type": agent_type,
                "phoenix_api_url": api_url,
                "phoenix_api_key": agent.phoenix_api_key or "",
                "current_mode": agent.current_mode or "conservative",
                "robinhood_credentials": (agent.config or {}).get("robinhood_credentials", {}),
                "risk_params": (agent.manifest or {}).get("risk", config.get("risk_params", {})),
                **config,
            }
            (work_dir / "config.json").write_text(json.dumps(agent_config, indent=2, default=str))
            rh_creds = agent_config.get("robinhood_credentials", {})
            _write_claude_settings(work_dir, rh_creds, paper_mode=agent_config.get("paper_mode", True))

            # Copy .claude/commands/ from live-trader-v1 template
            commands_src = LIVE_TEMPLATE / ".claude" / "commands"
            if commands_src.exists():
                commands_dst = work_dir / ".claude" / "commands"
                if commands_dst.exists():
                    shutil.rmtree(commands_dst)
                shutil.copytree(commands_src, commands_dst)

            session_row_id = uuid.uuid4()
            db.add(AgentSession(
                id=session_row_id,
                agent_id=agent_id,
                agent_type=agent_type,
                session_role="primary",
                status="starting",
                working_dir=str(work_dir),
                config=agent_config,
            ))
            agent.status = "RUNNING"
            agent.worker_status = "STARTING"
            agent.updated_at = datetime.now(timezone.utc)
            await db.commit()

        task = asyncio.create_task(
            self._run_specialized(agent_id, work_dir, session_row_id)
        )
        _running_tasks[str(agent_id)] = task
        return str(session_row_id)

    async def _run_specialized(self, agent_id: uuid.UUID, work_dir: Path,
                                session_row_id: uuid.UUID) -> None:
        """Run a specialized agent (UW, social, strategy) as a Claude Code session."""
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            logger.error("claude-agent-sdk unavailable")
            return

        async for db in _get_session():
            await self._update_session(db, session_row_id, status="running")

        prompt = (
            "You are now live. Read CLAUDE.md for your full instructions. "
            "Start your main monitoring loop. Process signals, take trades, "
            "spawn position monitor sub-agents, share knowledge with peers, "
            "and report all activity to Phoenix."
        )

        options = ClaudeAgentOptions(
            cwd=str(work_dir),
            permission_mode="dontAsk",
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        try:
            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "session_id"):
                    async for db in _get_session():
                        await self._update_session(db, session_row_id,
                                                   session_id=message.session_id)
                if hasattr(message, "is_error") and getattr(message, "is_error", False):
                    async for db in _get_session():
                        await self._update_session(db, session_row_id, status="error",
                                                   error="Agent error")
                    return
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="completed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Specialized agent crashed")
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error=str(exc)[:500])
        finally:
            _running_tasks.pop(str(agent_id), None)

    # ------------------------------------------------------------------

    async def stop_agent(self, agent_id: uuid.UUID) -> dict:
        """Stop a running agent (backtester or analyst)."""
        agent_key = str(agent_id)
        task = _running_tasks.get(agent_key)

        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        _running_tasks.pop(agent_key, None)
        _session_ids.pop(agent_key, None)
        _chat_session_ids.pop(agent_key, None)

        async for db in _get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if agent:
                agent.worker_status = "STOPPED"
                agent.updated_at = datetime.now(timezone.utc)

            sess = (await db.execute(
                select(AgentSession)
                .where(AgentSession.agent_id == agent_id, AgentSession.status.in_(["running", "starting"]))
                .order_by(AgentSession.started_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if sess:
                sess.status = "stopped"
                sess.stopped_at = datetime.now(timezone.utc)
            await db.commit()

        return {"status": "stopped", "agent_id": agent_key}

    async def pause_agent(self, agent_id: uuid.UUID) -> dict:
        """Pause a running agent (preserves session for resume)."""
        agent_key = str(agent_id)
        task = _running_tasks.get(agent_key)

        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        _running_tasks.pop(agent_key, None)

        async for db in _get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if agent:
                agent.status = "PAUSED"
                agent.worker_status = "STOPPED"
                agent.updated_at = datetime.now(timezone.utc)

            sess = (await db.execute(
                select(AgentSession)
                .where(AgentSession.agent_id == agent_id, AgentSession.status == "running")
                .order_by(AgentSession.started_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if sess:
                sess.status = "paused"
            await db.commit()

        return {"status": "paused", "agent_id": agent_key}

    async def resume_agent(self, agent_id: uuid.UUID) -> dict:
        """Resume a paused agent."""
        agent_key = str(agent_id)
        if agent_key in _running_tasks and not _running_tasks[agent_key].done():
            return {"status": "already_running", "agent_id": agent_key}

        async for db in _get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if not agent:
                return {"status": "error", "message": "Agent not found"}

            work_dir = DATA_DIR / "live_agents" / agent_key
            if not work_dir.exists():
                work_dir = await self._prepare_analyst_directory(agent, db)
            else:
                pipeline_alive = self._is_pipeline_alive(work_dir)
                _PIPELINE_FILES = {"live_pipeline.py", "discord_redis_consumer.py"}
                for subdir in ("tools", "skills"):
                    src = LIVE_TEMPLATE / subdir
                    dst = work_dir / subdir
                    if src.exists():
                        if pipeline_alive and subdir == "tools":
                            dst.mkdir(exist_ok=True)
                            for item in src.iterdir():
                                if item.name in _PIPELINE_FILES:
                                    continue
                                target = dst / item.name
                                if item.is_dir():
                                    if target.exists():
                                        shutil.rmtree(target)
                                    shutil.copytree(item, target)
                                else:
                                    shutil.copy2(item, target)
                        else:
                            if dst.exists():
                                shutil.rmtree(dst)
                            shutil.copytree(src, dst)
                startup_src = LIVE_TEMPLATE / "startup.sh"
                if startup_src.exists():
                    shutil.copy2(startup_src, work_dir / "startup.sh")

            session_row_id = uuid.uuid4()
            db.add(AgentSession(
                id=session_row_id,
                agent_id=agent_id,
                agent_type="analyst",
                status="starting",
                working_dir=str(work_dir),
            ))
            agent.status = "RUNNING"
            agent.worker_status = "STARTING"
            agent.updated_at = datetime.now(timezone.utc)
            await db.commit()

        task = asyncio.create_task(
            self._run_analyst(agent_id, work_dir, session_row_id, resume=True)
        )
        _running_tasks[agent_key] = task
        return {"status": "resuming", "agent_id": agent_key}

    async def dispatch_trigger(self, agent_id: uuid.UUID, trigger_type: str,
                                payload: dict | None = None) -> dict:
        """P9: Push a typed trigger to an agent via the Redis trigger bus.

        Also writes to `pending_tasks.json` as a redundant local signal so agents
        without Redis connectivity still wake. Safe to call even if the agent is
        not running — the trigger will be consumed next time it starts.
        """
        workdir: str | None = None
        async for db in _get_session():
            sess = (await db.execute(
                select(AgentSession)
                .where(AgentSession.agent_id == agent_id, AgentSession.status == "running")
                .order_by(AgentSession.started_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if sess and sess.working_dir:
                workdir = sess.working_dir
            break

        try:
            from shared.triggers import Trigger, TriggerType, get_bus
            tt = TriggerType(trigger_type) if not isinstance(trigger_type, TriggerType) else trigger_type
            await get_bus().publish(
                Trigger(agent_id=str(agent_id), type=tt, payload=payload or {}),
                workdir=workdir,
            )
            return {"status": "published", "workdir": workdir}
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # ------------------------------------------------------------------
    # Chat Gateway — route user messages through Claude SDK sessions
    # ------------------------------------------------------------------

    async def chat_with_agent(self, agent_id: uuid.UUID, user_message: str) -> str | None:
        """Route a chat message to a Claude SDK session with full MCP tool access.

        Immediately inserts a 'thinking' placeholder so the frontend can show a
        spinner, then replaces it in-place once the real reply is ready.
        """
        agent_key = str(agent_id)

        thinking_id = await self._write_thinking_indicator(agent_id)

        try:
            ctx = await self._load_chat_context(agent_id)
        except Exception as exc:
            logger.exception("[chat_gateway] failed to load context for %s: %s", agent_id, exc)
            await self._write_chat_reply(
                agent_id, f"(Failed to load agent context: {str(exc)[:120]})", update_id=thinking_id,
            )
            return None

        agent_info = ctx.get("agent")
        if not agent_info:
            logger.debug("[chat_gateway] agent %s not found", agent_id)
            await self._write_chat_reply(agent_id, "(Agent not found.)", update_id=thinking_id)
            return None

        rh_creds: dict = ctx.get("_rh_creds") or {}
        has_mcp = bool(rh_creds.get("username") and rh_creds.get("password"))

        if not has_mcp:
            return await self._chat_fast_path(agent_id, ctx, user_message, thinking_id=thinking_id)

        return await self._chat_sdk_path(
            agent_id, agent_key, ctx, user_message, rh_creds, thinking_id=thinking_id,
        )

    async def _load_chat_context(self, agent_id: uuid.UUID) -> dict:
        """Fetch agent record, chat history, recent trades, and RH credentials."""
        from shared.db.models.agent_chat import AgentChatMessage  # noqa: PLC0415
        from shared.db.models.agent_trade import AgentTrade  # noqa: PLC0415

        ctx: dict = {"agent": None, "chat": [], "trades": [], "_rh_creds": {}}
        async for sess in _get_session():
            res = await sess.execute(select(Agent).where(Agent.id == agent_id))
            agent = res.scalar_one_or_none()
            if not agent:
                return ctx

            ctx["agent"] = {
                "id": str(agent.id),
                "name": agent.name,
                "type": agent.type,
                "status": agent.status,
                "character": (agent.manifest or {}).get("identity", {}).get("character", ""),
                "rules": (agent.manifest or {}).get("rules", {}),
                "win_rate": agent.win_rate,
                "total_trades": agent.total_trades,
                "daily_pnl": agent.daily_pnl,
                "total_pnl": agent.total_pnl,
            }
            ctx["_rh_creds"] = (agent.config or {}).get("robinhood_credentials") or {}

            from sqlalchemy import desc  # noqa: PLC0415
            res = await sess.execute(
                select(AgentChatMessage)
                .where(AgentChatMessage.agent_id == agent_id)
                .order_by(desc(AgentChatMessage.created_at))
                .limit(12)
            )
            rows = list(res.scalars().all())
            rows.reverse()
            ctx["chat"] = [{"role": m.role, "content": m.content[:500]} for m in rows]

            try:
                since = datetime.now(timezone.utc) - timedelta(days=7)
                res = await sess.execute(
                    select(AgentTrade)
                    .where(AgentTrade.agent_id == agent_id, AgentTrade.created_at >= since)
                    .order_by(desc(AgentTrade.created_at))
                    .limit(8)
                )
                ctx["trades"] = [
                    {
                        "symbol": t.symbol,
                        "side": getattr(t, "side", None),
                        "pnl": float(getattr(t, "pnl_dollar", 0) or 0),
                        "at": t.created_at.isoformat() if t.created_at else None,
                    }
                    for t in res.scalars().all()
                ]
            except Exception:
                pass
            break
        return ctx

    def _build_chat_prompt(self, ctx: dict, user_message: str, has_mcp: bool = False) -> str:
        agent = ctx.get("agent") or {}
        chat_history = ctx.get("chat") or []
        trades = ctx.get("trades") or []

        parts: list[str] = [
            f"You are {agent.get('name', 'a Phoenix trading agent')} — a professional trader with full Robinhood access.",
            f"Character: {agent.get('character', 'a sharp, data-driven prop trader')}.",
            f"Win rate: {agent.get('win_rate', 'N/A')}, Total trades: {agent.get('total_trades', 0)},",
            f"Total P&L: {agent.get('total_pnl', 0)}, Today P&L: {agent.get('daily_pnl', 0)}.",
        ]

        if trades:
            trade_lines = [f"  {t.get('symbol','?')} {t.get('side','?')} pnl=${t.get('pnl',0)}" for t in trades[:5]]
            parts.append("Recent trades (last 7 days):\n" + "\n".join(trade_lines))

        if chat_history:
            turns = []
            for turn in chat_history[-8:]:
                role = "You" if turn.get("role") == "agent" else "User"
                turns.append(f"  {role}: {turn.get('content', '')[:300]}")
            parts.append("Chat history:\n" + "\n".join(turns))

        if has_mcp:
            parts.append(
                "You have FULL Robinhood MCP access. USE THESE TOOLS for every question:\n\n"
                "PORTFOLIO: get_all_positions (stocks + options in one call), get_option_positions "
                "(with Greeks, P&L), get_positions (stocks only)\n"
                "ACCOUNT: get_account, get_account_snapshot\n"
                "MARKET DATA: get_quote, get_nbbo, get_option_chain, get_option_greeks "
                "(delta/gamma/theta/vega/IV/chance of profit)\n"
                "HISTORY: get_order_history (recent stock + option orders)\n"
                "EXECUTION: close_position, close_option_position, place_stock_order, "
                "place_option_order, smart_limit_order\n\n"
                "CRITICAL RULES:\n"
                "- NEVER say 'I don't have access' — you DO have full access via MCP\n"
                "- NEVER ask the user what positions they hold — call get_all_positions\n"
                "- For options: always report Greeks, days to expiry, theta decay, P&L\n"
                "- Proactively warn about: near-expiry options, high theta decay, large losses\n"
                "- Give specific BUY/HOLD/SELL recommendations with reasoning\n"
                "- You can also run Python tools in your workspace for TA, research, etc."
            )

        parts.append(
            "Be direct, data-driven, and specific. Pull real numbers from your tools. "
            "Think like a prop trader managing real money.\n\n"
            f"User: {user_message}"
        )

        return "\n\n".join(parts)

    async def _chat_fast_path(
        self,
        agent_id: uuid.UUID,
        ctx: dict,
        user_message: str,
        *,
        thinking_id: uuid.UUID | None = None,
    ) -> str | None:
        """Direct Anthropic Messages API — fast (~2s), no MCP tools."""
        try:
            import anthropic  # noqa: PLC0415
        except ImportError:
            logger.error("[chat_gateway] anthropic SDK not installed")
            await self._write_chat_reply(agent_id, "(Chat unavailable — SDK not installed.)", update_id=thinking_id)
            return None

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.error("[chat_gateway] ANTHROPIC_API_KEY not set")
            await self._write_chat_reply(agent_id, "(Chat unavailable — API key not configured.)", update_id=thinking_id)
            return None

        agent = ctx.get("agent") or {}
        chat_history = ctx.get("chat") or []
        trades = ctx.get("trades") or []

        system_parts = [
            f"You are {agent.get('name', 'a Phoenix trading agent')} — a professional trader.",
            f"Character: {agent.get('character', 'a sharp, data-driven prop trader')}.",
            f"Win rate: {agent.get('win_rate', 'N/A')}, Total trades: {agent.get('total_trades', 0)},",
            f"Total P&L: {agent.get('total_pnl', 0)}, Today P&L: {agent.get('daily_pnl', 0)}.",
            "Be direct, data-driven, and specific. Think like a prop trader. "
            "If asked about live positions or account data you don't have in context, "
            "say you're checking and will follow up (the system will retry with full tools).",
        ]
        if trades:
            trade_strs = [f"  {t.get('symbol','?')} {t.get('side','?')} pnl=${t.get('pnl',0)}" for t in trades[:5]]
            system_parts.append("Recent trades:\n" + "\n".join(trade_strs))

        messages: list[dict] = []
        for turn in chat_history[-8:]:
            role = "assistant" if turn.get("role") == "agent" else "user"
            messages.append({"role": role, "content": turn.get("content", "")[:500]})
        messages.append({"role": "user", "content": user_message})

        if len(messages) >= 2 and messages[-1]["role"] == messages[-2]["role"]:
            messages = [messages[-1]]

        try:
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=400,
                system="\n".join(system_parts),
                messages=messages,
            )
            reply_text = resp.content[0].text if resp.content else "(No response generated)"
            await self._write_chat_reply(agent_id, reply_text, update_id=thinking_id)
            logger.info("[chat_gateway] fast reply for %s (%d chars)", agent_id, len(reply_text))
            return reply_text
        except Exception as exc:
            logger.error("[chat_gateway] anthropic call failed for %s: %s", agent_id, exc)
            await self._write_chat_reply(agent_id, f"(Chat error: {str(exc)[:120]})", update_id=thinking_id)
            return None

    async def _chat_sdk_path(
        self,
        agent_id: uuid.UUID,
        agent_key: str,
        ctx: dict,
        user_message: str,
        rh_creds: dict,
        *,
        thinking_id: uuid.UUID | None = None,
    ) -> str | None:
        """Claude Agent SDK path — full MCP tool access (Robinhood, etc.)."""
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query  # noqa: PLC0415
        except ImportError:
            logger.warning("[chat_gateway] claude_agent_sdk unavailable, falling back to fast path")
            return await self._chat_fast_path(agent_id, ctx, user_message, thinking_id=thinking_id)

        work_dir = await self._resolve_chat_workdir(agent_id, agent_key)

        # HOME points to the chat workdir so robin_stocks writes its session
        # pickle (~/.tokens/) there — persists across chat turns without re-auth.
        (work_dir / ".tokens").mkdir(exist_ok=True)
        mcp_env: dict[str, str] = {
            "HOME": str(work_dir),
            "PAPER_MODE": "false",
            "RH_USERNAME": rh_creds.get("username", ""),
            "RH_PASSWORD": rh_creds.get("password", ""),
            "RH_TOTP_SECRET": rh_creds.get("totp_secret", ""),
        }

        mcp_servers: dict = {
            "robinhood": {
                "command": sys.executable,
                "args": [str(_ROBINHOOD_MCP_SOURCE)],
                "env": mcp_env,
            }
        }

        allowed_tools: list[str] = ["Bash", "Read", "Grep", "Glob"] + _ROBINHOOD_CHAT_TOOLS

        options = ClaudeAgentOptions(
            cwd=str(work_dir),
            permission_mode="dontAsk",
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers,
        )

        chat_session_id = _chat_session_ids.get(agent_key)
        if chat_session_id:
            options.resume = chat_session_id

        prompt = self._build_chat_prompt(ctx, user_message, has_mcp=True)

        async def _run_query() -> str:
            response_text = ""
            new_session_id: str | None = None

            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "session_id") and message.session_id:
                    new_session_id = message.session_id

                if hasattr(message, "result") and message.result:
                    response_text = message.result

                if hasattr(message, "content") and isinstance(message.content, list):
                    for block in message.content:
                        if hasattr(block, "text") and block.text:
                            response_text = block.text

            if new_session_id:
                _chat_session_ids[agent_key] = new_session_id

            return response_text or "(Agent completed without a text response.)"

        try:
            reply = await asyncio.wait_for(_run_query(), timeout=CHAT_REPLY_TIMEOUT)
            await self._write_chat_reply(agent_id, reply, update_id=thinking_id)
            logger.info("[chat_gateway] SDK reply for %s (%d chars)", agent_id, len(reply))
            return reply
        except asyncio.TimeoutError:
            logger.warning("[chat_gateway] SDK timed out for %s, falling back to fast path", agent_id)
            return await self._chat_fast_path(agent_id, ctx, user_message, thinking_id=thinking_id)
        except Exception as exc:
            logger.exception("[chat_gateway] SDK chat failed for %s: %s", agent_id, exc)
            logger.info("[chat_gateway] falling back to fast path for %s", agent_id)
            return await self._chat_fast_path(agent_id, ctx, user_message, thinking_id=thinking_id)

    async def _resolve_chat_workdir(self, agent_id: uuid.UUID, agent_key: str) -> Path:
        """Find the best working directory for a chat session.

        Prefers the running agent's workdir (has all context files).
        Falls back to the standard live_agents directory.
        Creates a minimal temp dir as last resort.
        """
        if agent_key in _running_tasks and not _running_tasks[agent_key].done():
            async for db in _get_session():
                sess = (await db.execute(
                    select(AgentSession)
                    .where(AgentSession.agent_id == agent_id, AgentSession.status == "running")
                    .order_by(AgentSession.started_at.desc())
                    .limit(1)
                )).scalar_one_or_none()
                if sess and sess.working_dir and Path(sess.working_dir).exists():
                    return Path(sess.working_dir)
                break

        agent_dir = DATA_DIR / "live_agents" / agent_key
        if agent_dir.exists():
            return agent_dir

        fallback = DATA_DIR / "chat_sessions" / agent_key
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    async def _write_thinking_indicator(self, agent_id: uuid.UUID) -> uuid.UUID:
        """Insert a 'thinking' placeholder that the frontend renders as a spinner."""
        from shared.db.models.agent_chat import AgentChatMessage  # noqa: PLC0415

        row_id = uuid.uuid4()
        async for sess in _get_session():
            sess.add(AgentChatMessage(
                id=row_id,
                agent_id=agent_id,
                role="agent",
                content="Thinking\u2026",
                message_type="thinking",
                extra_data={"source": "chat_gateway"},
            ))
            await sess.commit()
            break
        return row_id

    async def _write_chat_reply(
        self,
        agent_id: uuid.UUID,
        text: str,
        update_id: uuid.UUID | None = None,
    ) -> None:
        """Persist an agent reply — updates the thinking row in-place when possible."""
        from shared.db.models.agent_chat import AgentChatMessage  # noqa: PLC0415

        async for sess in _get_session():
            if update_id:
                row = await sess.get(AgentChatMessage, update_id)
                if row:
                    row.content = text[:4000]
                    row.message_type = "text"
                    row.extra_data = {"source": "chat_gateway"}
                    await sess.commit()
                    return

            sess.add(AgentChatMessage(
                id=uuid.uuid4(),
                agent_id=agent_id,
                role="agent",
                content=text[:4000],
                message_type="text",
                extra_data={"source": "chat_gateway"},
            ))
            await sess.commit()
            break

    # ------------------------------------------------------------------

    async def send_task(self, agent_id: uuid.UUID, task_prompt: str) -> dict:
        """Send a task/query to a running agent.

        Strategy: write the task to a "pending_tasks.json" file in the agent's
        working directory. The agent's main loop polls this file periodically
        and processes pending tasks. This is more reliable than trying to inject
        a prompt into a running Claude SDK session, which doesn't have a stable
        re-entry API.

        For more interactive flows (like real-time chat), the agent's chat tool
        polls the agent_chat_messages table directly via Phoenix API.
        """
        agent_key = str(agent_id)
        if agent_key not in _running_tasks or _running_tasks[agent_key].done():
            # Try to start a fresh session with this prompt
            return {"status": "error", "message": "Agent is not running"}

        # Find the agent's working directory
        async for db in _get_session():
            sess = (await db.execute(
                select(AgentSession)
                .where(AgentSession.agent_id == agent_id, AgentSession.status == "running")
                .order_by(AgentSession.started_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if not sess or not sess.working_dir:
                return {"status": "error", "message": "No active session working directory"}

            work_dir = Path(sess.working_dir)
            tasks_file = work_dir / "pending_tasks.json"

            # Append task to pending_tasks.json
            tasks: list[dict] = []
            if tasks_file.exists():
                try:
                    tasks = json.loads(tasks_file.read_text())
                except (json.JSONDecodeError, OSError):
                    tasks = []

            task_entry = {
                "id": str(uuid.uuid4()),
                "prompt": task_prompt,
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            tasks.append(task_entry)
            try:
                tasks_file.write_text(json.dumps(tasks, indent=2))
            except OSError as exc:
                return {"status": "error", "message": f"Could not write task: {exc}"}

            return {
                "status": "queued",
                "task_id": task_entry["id"],
                "working_dir": str(work_dir),
            }

    async def get_status(self, agent_id: uuid.UUID) -> dict:
        """Get the status of an agent's Claude Code session."""
        agent_key = str(agent_id)
        task = _running_tasks.get(agent_key)
        session_id = _session_ids.get(agent_key)

        db_status = None
        async for db in _get_session():
            sess = (await db.execute(
                select(AgentSession)
                .where(AgentSession.agent_id == agent_id)
                .order_by(AgentSession.started_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if sess:
                db_status = {
                    "session_row_id": str(sess.id),
                    "agent_type": sess.agent_type,
                    "status": sess.status,
                    "session_id": sess.session_id,
                    "started_at": sess.started_at.isoformat() if sess.started_at else None,
                    "last_heartbeat": sess.last_heartbeat.isoformat() if sess.last_heartbeat else None,
                }

        return {
            "running": task is not None and not task.done() if task else False,
            "cancelled": task.cancelled() if task and task.done() else False,
            "session_id": session_id,
            "db_session": db_status,
        }

    async def list_agents(self) -> list[dict]:
        """List all active agent sessions."""
        result = []
        async for db in _get_session():
            rows = (await db.execute(
                select(AgentSession)
                .where(AgentSession.status.in_(["running", "starting", "paused"]))
                .order_by(AgentSession.started_at.desc())
            )).scalars().all()
            for s in rows:
                task = _running_tasks.get(str(s.agent_id))
                result.append({
                    "session_row_id": str(s.id),
                    "agent_id": str(s.agent_id),
                    "agent_type": s.agent_type,
                    "status": s.status,
                    "actually_running": task is not None and not task.done() if task else False,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                })
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _update_session(
        self, db, session_row_id: uuid.UUID, *,
        status: str | None = None,
        session_id: str | None = None,
        error: str | None = None,
    ) -> None:
        sess = (await db.execute(
            select(AgentSession).where(AgentSession.id == session_row_id)
        )).scalar_one_or_none()
        if not sess:
            return
        if status:
            sess.status = status
        if session_id:
            sess.session_id = session_id
        if error:
            sess.error_message = error
        if status in ("completed", "error", "stopped"):
            sess.stopped_at = datetime.now(timezone.utc)
        sess.last_heartbeat = datetime.now(timezone.utc)
        await db.commit()


# Module-level singleton
gateway = AgentGateway()


# ------------------------------------------------------------------
# Standalone helpers (shared with routes)
# ------------------------------------------------------------------

def _can_use_claude_sdk() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    if not shutil.which("claude"):
        return False
    return True


def _sdk_unavailable_reason() -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY not set"
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return "claude-agent-sdk not installed"
    if not shutil.which("claude"):
        return "claude CLI not found in PATH"
    return "unknown"


def _claude_sdk_preflight() -> str | None:
    """F2: fail-fast checks before entering the Claude SDK query loop.

    Returns None if everything looks good, or a string error message
    describing what's wrong. Runs quickly (<5s) with subprocess timeouts.
    """
    import subprocess as _sp

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY not set in container env"

    claude_bin = shutil.which("claude")
    if not claude_bin:
        return "claude CLI binary not found in PATH"

    try:
        proc = _sp.run(
            [claude_bin, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0:
            return f"claude --version exited {proc.returncode}: {proc.stderr[:200]}"
    except _sp.TimeoutExpired:
        return "claude --version hung >5s (binary may be broken)"
    except Exception as exc:
        return f"claude --version spawn failed: {exc}"

    # Verify the SDK import still works (caught earlier but belt-and-braces)
    try:
        import claude_agent_sdk  # noqa: F401
    except Exception as exc:
        return f"claude_agent_sdk import failed: {exc}"

    # Verify ~/.claude is writable
    home = os.environ.get("HOME", "/root")
    claude_dir = Path(home) / ".claude"
    try:
        claude_dir.mkdir(parents=True, exist_ok=True)
        test_file = claude_dir / ".phoenix_preflight"
        test_file.write_text("ok")
        test_file.unlink()
    except Exception as exc:
        return f"{claude_dir} not writable: {exc}"

    return None


def _chown_to_phoenix(path: Path) -> None:
    try:
        pw = pwd.getpwnam("phoenix")
        uid, gid = pw.pw_uid, pw.pw_gid
        for p in [path] + list(path.rglob("*")):
            os.chown(p, uid, gid)
    except (KeyError, PermissionError):
        pass


def _build_backtest_prompt(agent_id: uuid.UUID, config: dict, work_dir: Path) -> str:
    api_url = config.get("phoenix_api_url", "")
    api_key = config.get("phoenix_api_key", "")
    tools_dir = str(BACKTESTING_TOOLS)
    # work_dir is now the versioned output dir (e.g. data/backtest_{id}/output/v3/)
    # so output and config live directly in it.
    output_dir = str(work_dir)
    config_path = str(work_dir / "config.json")

    return f"""You are the Phoenix Backtesting Agent. Run the complete backtesting pipeline.

## Configuration
Config file: {config_path}
Tools directory: {tools_dir}
Output directory: {output_dir}

## Pipeline Steps — run in order

1. **Transform**: `python {tools_dir}/transform.py --config {config_path} --output {output_dir}/transformed.parquet`
2. **Enrich**: `python {tools_dir}/enrich.py --input {output_dir}/transformed.parquet --output {output_dir}/enriched.parquet`
3. **Text Embeddings**: `python {tools_dir}/compute_text_embeddings.py --input {output_dir}/enriched.parquet --output {output_dir}/`
4. **Preprocess**: `python {tools_dir}/preprocess.py --input {output_dir}/enriched.parquet --output {output_dir}/`

### Model Selection (intelligent — picks models based on data size)
5. **Select Models**: `python {tools_dir}/model_selector.py --data {output_dir} --output {output_dir}/model_selection.json`
   - Read `{output_dir}/model_selection.json` to see which models to train.
   - The selector chooses optimal models based on dataset size and features.

### Model Training (run ONLY the selected models, sequentially)
6. **Train selected base models**: For each model listed in `model_selection.json["models"]`, run:
   `python {tools_dir}/train_<model_name>.py --data {output_dir} --output {output_dir}/models/`
   Run ONE AT A TIME. Do NOT run in parallel — PyTorch models need full memory.

7. **Train ensemble models** (after all base models): Run these if they appear in the selection:
   - `python {tools_dir}/train_hybrid.py --data {output_dir} --output {output_dir}/models/`
   - `python {tools_dir}/train_meta_learner.py --models-dir {output_dir}/models/ --data {output_dir} --output {output_dir}/models/`

### Evaluation and Analysis
8. **Evaluate**: `python {tools_dir}/evaluate_models.py --models-dir {output_dir}/models --output {output_dir}/models/best_model.json`
9. **Explainability**: `python {tools_dir}/build_explainability.py --model {output_dir}/models --data {output_dir} --output {output_dir}/explainability.json`
10. **LLM Pattern Discovery** (NEW): `python {tools_dir}/llm_pattern_discovery.py --data {output_dir} --explainability {output_dir}/explainability.json --output {output_dir}/llm_discovered_patterns.json`
    - Two-stage: Sonnet generates 15 candidates from 80 sampled trades, Opus refines top candidates.
    - Each candidate is validated against the full dataset before being kept.
    - Leaky meta-features (analyst_*, ticker_win_rate, etc.) are forbidden in the prompt.
11. **Pattern Discovery**: `python {tools_dir}/discover_patterns.py --data {output_dir} --output {output_dir}/patterns.json`
    - Merges decision-tree rules + grouped aggregations + LLM patterns from step 10.
    - IMPORTANT: run step 10 FIRST so discover_patterns.py can pick up llm_discovered_patterns.json.
12. **LLM Strategy Analysis**: `python {tools_dir}/analyze_patterns_llm.py --data {output_dir} --output {output_dir}/llm_patterns.json --config {config_path}`
13. **Create Live Agent**: `python {tools_dir}/create_live_agent.py --config {config_path} --models {output_dir}/models --output {output_dir}/live_agent/`

## Progress Reporting

After each step, report progress via curl (best-effort — do NOT retry or stop if curl fails):
```bash
curl -s -X POST "{api_url}/api/v2/agents/{agent_id}/backtest-progress" \\
  -H "Content-Type: application/json" \\
  -H "X-Agent-Key: {api_key}" \\
  -d '{{"step": "<step_name>", "message": "<what happened>", "progress_pct": <pct>}}' \\
  || true
```

**IMPORTANT**: Progress curl calls are fire-and-forget. If curl returns a non-zero exit code or an HTTP error (404, 500, etc.), log a one-line warning and **continue immediately to the next pipeline step**. Never retry a failed curl and never treat a failed curl as a pipeline failure.

Progress percentages: transform=10, enrich=22, text_embeddings=25, preprocess=28, model_selection=30, training=30-63 (distribute evenly across selected models), evaluate=68, explainability=75, patterns=80, llm_patterns=85, create_live_agent=95

When fully complete:
```bash
curl -s -X POST "{api_url}/api/v2/agents/{agent_id}/backtest-progress" \\
  -H "Content-Type: application/json" \\
  -H "X-Agent-Key: {api_key}" \\
  -d '{{"step": "completed", "message": "Pipeline complete", "progress_pct": 100, "status": "COMPLETED"}}' \\
  || true
```

If a step fails after retrying:
```bash
curl -s -X POST "{api_url}/api/v2/agents/{agent_id}/backtest-progress" \\
  -H "Content-Type: application/json" \\
  -H "X-Agent-Key: {api_key}" \\
  -d '{{"step": "<failed_step>", "message": "<error>", "progress_pct": <pct>, "status": "FAILED"}}' \\
  || true
```

## Rules
- Create {output_dir}/models/ directories before running training steps
- Run model_selector.py FIRST before any training — only train the models it selects
- Run training steps SEQUENTIALLY one at a time — do NOT run them in parallel
- Ensemble models (hybrid, meta_learner) must wait for ALL selected base models to finish
- If a script fails, read the error, attempt to fix it, and retry ONCE
- If a script is missing a Python dependency, install it with pip
- Do NOT modify the tool scripts unless absolutely necessary to fix a bug
- Report progress after EVERY step
- The enrichment step uses ~200 features across 8 categories — this is normal and expected
"""


async def _syslog(
    db, agent_id: uuid.UUID, backtest_id: uuid.UUID | None,
    step: str, pct: int, message: str,
) -> None:
    if backtest_id:
        bt = (await db.execute(
            select(AgentBacktest).where(AgentBacktest.id == backtest_id)
        )).scalar_one_or_none()
        if bt:
            bt.current_step = step
            bt.progress_pct = pct

    db.add(SystemLog(
        id=uuid.uuid4(), source="backtest", level="INFO", service="agent-gateway",
        agent_id=str(agent_id),
        backtest_id=str(backtest_id) if backtest_id else None,
        message=message, step=step, progress_pct=pct,
    ))
    await db.commit()


async def _mark_backtest_completed(db, agent_id: uuid.UUID, backtest_id: uuid.UUID) -> None:
    now = datetime.now(timezone.utc)
    bt = (await db.execute(
        select(AgentBacktest).where(AgentBacktest.id == backtest_id)
    )).scalar_one_or_none()
    if bt:
        bt.status = "COMPLETED"
        bt.progress_pct = 100
        bt.current_step = "completed"
        bt.completed_at = now
        m = bt.metrics or {}
        bt.total_trades = m.get("total_trades") or m.get("trades") or 0
        bt.win_rate = m.get("win_rate")
        bt.sharpe_ratio = m.get("sharpe_ratio")
        bt.max_drawdown = m.get("max_drawdown")
        bt.total_return = m.get("total_return")

    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent:
        agent.status = "BACKTEST_COMPLETE"
        agent.error_message = None
        agent.updated_at = now
        if bt:
            m = bt.metrics or {}
            agent.model_type = m.get("best_model") or m.get("model")
            agent.model_accuracy = m.get("accuracy")
            agent.total_trades = bt.total_trades or 0
            agent.win_rate = bt.win_rate or 0.0

    db.add(SystemLog(
        id=uuid.uuid4(), source="backtest", level="INFO", service="agent-gateway",
        agent_id=str(agent_id), backtest_id=str(backtest_id),
        message="Backtesting pipeline completed", step="completed", progress_pct=100,
    ))
    await db.commit()
    logger.info("Backtest completed for agent %s", agent_id)


async def _mark_backtest_failed(
    db, agent_id: uuid.UUID, backtest_id: uuid.UUID, step: str, error_msg: str
) -> None:
    now = datetime.now(timezone.utc)
    bt = (await db.execute(
        select(AgentBacktest).where(AgentBacktest.id == backtest_id)
    )).scalar_one_or_none()
    if bt:
        bt.status = "FAILED"
        bt.error_message = error_msg
        bt.completed_at = now

    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent:
        agent.status = "ERROR"
        agent.error_message = error_msg
        agent.updated_at = now

    db.add(SystemLog(
        id=uuid.uuid4(), source="backtest", level="ERROR", service="agent-gateway",
        agent_id=str(agent_id), backtest_id=str(backtest_id),
        message=error_msg, step=step,
    ))
    await db.commit()
    logger.error("Backtest failed for agent %s: %s", agent_id, error_msg)


def get_running_agents() -> list[str]:
    return [k for k, t in _running_tasks.items() if not t.done()]


def get_agent_status(agent_id: str) -> dict:
    task = _running_tasks.get(agent_id)
    session_id = _session_ids.get(agent_id)
    if not task:
        return {"running": False, "session_id": session_id}
    return {
        "running": not task.done(),
        "cancelled": task.cancelled() if task.done() else False,
        "session_id": session_id,
    }


def cancel_backtest(agent_id: str) -> bool:
    task = _running_tasks.get(agent_id)
    if task and not task.done():
        task.cancel()
        return True
    return False
