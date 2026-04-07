"""Agent Gateway — central hub for managing Claude Code agent lifecycle.

Replaces both agent_manager.py (live agents) and claude_backtester.py (backtest agents)
with a unified gateway that:
  - Tracks all active Claude Code sessions in the DB (agent_sessions table)
  - Creates backtesting and analyst agent sessions from templates
  - Manages lifecycle: start, stop, pause, resume, health-check
  - Orchestrates the backtest → auto-create-analyst flow
"""

import asyncio
import json
import logging
import os
import pwd
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from shared.db.engine import get_session as _get_session
from shared.db.models.agent import Agent, AgentBacktest
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
DATA_DIR = REPO_ROOT / "data"

_running_tasks: dict[str, asyncio.Task] = {}


def _get_api_url() -> str:
    """Return the Phoenix API base URL for intra-cluster curl calls.

    Priority:
      1. PHOENIX_API_URL env var (explicit override)
      2. PUBLIC_API_URL env var (legacy alias)
      3. http://localhost:8011 (safe local default — never the production domain)
    """
    return os.getenv("PHOENIX_API_URL", os.getenv("PUBLIC_API_URL", "http://localhost:8011"))
_session_ids: dict[str, str] = {}

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
        """Original backtester body — wrapped by _run_backtester for the semaphore."""
        _chown_to_phoenix(work_dir)

        # Transition backtest from PENDING → RUNNING now that we're actually executing
        async for db in _get_session():
            bt = (await db.execute(
                select(AgentBacktest).where(AgentBacktest.id == backtest_id)
            )).scalar_one_or_none()
            if bt and bt.status == "PENDING":
                bt.status = "RUNNING"
                await db.commit()

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
                from claude_agent_sdk import query, ClaudeAgentOptions

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

                async def _consume_query() -> bool:
                    """Inner coroutine so we can wrap the whole generator in wait_for."""
                    nonlocal last_text, hit_error_message, first_message_seen
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
                        if hasattr(message, "is_error") and getattr(message, "is_error", False):
                            hit_error_message = True
                            async for db in _get_session():
                                await self._update_session(db, session_row_id, status="error",
                                                           error=f"Claude agent error: {last_text[:500]}")
                                await _mark_backtest_failed(db, agent_id, backtest_id, "claude_agent", last_text[:500])
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
            from claude_agent_sdk import query, ClaudeAgentOptions
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

        prompt = (
            home_export +
            "You are now live. Read CLAUDE.md for your full instructions. "
            "Start the operation loop: run pre-market analysis, start the Discord listener, "
            "and begin monitoring for trade signals. Report all activity to Phoenix."
        )
        if resume:
            prompt = (
                home_export +
                "Resume your live trading session. Check your current positions in positions.json, "
                "restart the Discord listener, and continue monitoring. "
                "Report your resumed status to Phoenix."
            )

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
                        if hasattr(block, "text"):
                            last_text = block.text[-500:]
                if hasattr(message, "session_id"):
                    _session_ids[agent_key] = message.session_id
                    async for db in _get_session():
                        await self._update_session(db, session_row_id,
                                                   session_id=message.session_id)
                if hasattr(message, "is_error") and getattr(message, "is_error", False):
                    async for db in _get_session():
                        await self._update_session(db, session_row_id, status="error",
                                                   error=f"Agent error: {last_text[:500]}")
                        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                        if agent:
                            agent.worker_status = "ERROR"
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
            logger.exception("Live agent %s crashed", agent_id)
            async for db in _get_session():
                await self._update_session(db, session_row_id, status="error",
                                           error=str(exc)[:500])
                agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                if agent:
                    agent.worker_status = "ERROR"
                    agent.updated_at = datetime.now(timezone.utc)
                await db.commit()
        finally:
            _running_tasks.pop(agent_key, None)

    async def _prepare_analyst_directory(self, agent: Agent, session) -> Path:
        """Build the analyst agent's working directory with all artifacts."""
        work_dir = DATA_DIR / "live_agents" / str(agent.id)
        work_dir.mkdir(parents=True, exist_ok=True)

        for subdir in ("tools", "skills"):
            src = LIVE_TEMPLATE / subdir
            dst = work_dir / subdir
            if dst.exists():
                shutil.rmtree(dst)
            if src.exists():
                shutil.copytree(src, dst)

        claude_settings_dst = work_dir / ".claude"
        claude_settings_dst.mkdir(exist_ok=True)
        settings_src = LIVE_TEMPLATE / ".claude" / "settings.json"
        if settings_src.exists():
            shutil.copy2(settings_src, claude_settings_dst / "settings.json")

        commands_src = LIVE_TEMPLATE / ".claude" / "commands"
        if commands_src.exists():
            commands_dst = claude_settings_dst / "commands"
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
            "modes": manifest.get("modes", {}),
            "rules": manifest.get("rules", []),
            "models": manifest.get("models", {}),
            "knowledge": manifest.get("knowledge", {}),
        }

        # Resolve primary connector_id for Redis stream key alignment (Story 2.1)
        connector_ids = agent.config.get("connector_ids") or [] if agent.config else []
        primary_connector_id = connector_ids[0] if connector_ids else ""
        agent_config["connector_id"] = primary_connector_id

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
        self._render_claude_md(agent, manifest, work_dir)
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

        # Write position.json
        position_data.setdefault("position_id", position_id)
        position_data.setdefault("status", "open")
        position_data.setdefault("opened_at", datetime.now(timezone.utc).isoformat())
        (work_dir / "position.json").write_text(json.dumps(position_data, indent=2, default=str))

        # Build config from parent agent
        async for db in _get_session():
            parent = (await db.execute(
                select(Agent).where(Agent.id == parent_agent_id)
            )).scalar_one_or_none()
            if not parent:
                logger.error("Parent agent %s not found", parent_agent_id)
                return ""

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
        """Run the position monitor as a Claude Code session."""
        task_key = f"{parent_agent_id}:{position_id}"

        try:
            from claude_agent_sdk import query, ClaudeAgentOptions
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
        sup_agent_uuid = uuid.UUID("00000000-0000-0000-0000-000000000001")  # Reserved supervisor UUID
        async for db in _get_session():
            db.add(AgentSession(
                id=session_row_id,
                agent_id=sup_agent_uuid,
                agent_type="supervisor",
                session_role="supervisor",
                status="starting",
                working_dir=str(work_dir),
                config=sup_config,
            ))
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
        """Run the supervisor as a Claude Code session."""
        try:
            from claude_agent_sdk import query, ClaudeAgentOptions
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
        mb_agent_uuid = uuid.UUID("00000000-0000-0000-0000-000000000002")
        session_row_id = uuid.uuid4()
        async for db in _get_session():
            db.add(AgentSession(
                id=session_row_id,
                agent_id=mb_agent_uuid,
                agent_type="morning_briefing",
                session_role="morning_briefing",
                status="starting",
                working_dir=str(work_dir),
                config=mb_config,
            ))
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
        """Run the morning briefing as a one-shot Claude Code session."""
        try:
            from claude_agent_sdk import query, ClaudeAgentOptions
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
            db.add(AgentSession(
                id=session_row_id,
                agent_id=reserved_uuid,
                agent_type=agent_type,
                session_role=agent_type,
                status="starting",
                working_dir=str(work_dir),
                config=agent_config,
            ))
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
        """Run a one-shot Claude Code session. Shared by daily_summary, eod,
        trade_feedback. 30-min hard timeout matches the backtester."""
        try:
            from claude_agent_sdk import query, ClaudeAgentOptions
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
            reserved_uuid=uuid.UUID("00000000-0000-0000-0000-000000000004"),
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
            reserved_uuid=uuid.UUID("00000000-0000-0000-0000-000000000003"),
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
            reserved_uuid=uuid.UUID("00000000-0000-0000-0000-000000000005"),
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
            from claude_agent_sdk import query, ClaudeAgentOptions
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
            from shared.triggers import get_bus, Trigger, TriggerType
            tt = TriggerType(trigger_type) if not isinstance(trigger_type, TriggerType) else trigger_type
            await get_bus().publish(
                Trigger(agent_id=str(agent_id), type=tt, payload=payload or {}),
                workdir=workdir,
            )
            return {"status": "published", "workdir": workdir}
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

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

    async def _fallback_subprocess(
        self, agent_id: uuid.UUID, backtest_id: uuid.UUID, config: dict
    ) -> None:
        """Run the pipeline using the subprocess-based task_runner."""
        try:
            from apps.api.src.services.task_runner import _run_pipeline
            await _run_pipeline(agent_id, backtest_id, config)
        except Exception as exc:
            logger.exception("Subprocess fallback also failed for agent %s", agent_id)
            async for db in _get_session():
                await _mark_backtest_failed(db, agent_id, backtest_id, "subprocess", str(exc)[:500])
        finally:
            _running_tasks.pop(str(agent_id), None)


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
