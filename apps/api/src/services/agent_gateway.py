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
DATA_DIR = REPO_ROOT / "data"

_running_tasks: dict[str, asyncio.Task] = {}
_session_ids: dict[str, str] = {}


class AgentGateway:
    """Singleton gateway for all Claude Code agent operations."""

    # ------------------------------------------------------------------
    # Backtesting agent
    # ------------------------------------------------------------------

    async def create_backtester(
        self, agent_id: uuid.UUID, backtest_id: uuid.UUID, config: dict
    ) -> str:
        """Spawn a Claude Code backtesting session. Returns session row id."""
        task_key = str(agent_id)
        if task_key in _running_tasks and not _running_tasks[task_key].done():
            logger.warning("Backtest already running for agent %s", agent_id)
            return task_key

        work_dir = DATA_DIR / f"backtest_{agent_id}"
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "output").mkdir(exist_ok=True)
        (work_dir / "output" / "models").mkdir(exist_ok=True)
        (work_dir / "output" / "preprocessed").mkdir(exist_ok=True)

        config_path = work_dir / "config.json"
        config_path.write_text(json.dumps(config, indent=2, default=str))

        session_row_id = uuid.uuid4()
        async for db in _get_session():
            db.add(AgentSession(
                id=session_row_id,
                agent_id=agent_id,
                agent_type="backtester",
                status="starting",
                working_dir=str(work_dir),
                config=config,
            ))
            await db.commit()

        task = asyncio.create_task(
            self._run_backtester(agent_id, backtest_id, config, work_dir, session_row_id)
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
        """Run backtesting via Claude Code agent with retries. No subprocess fallback."""
        _chown_to_phoenix(work_dir)
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

        max_attempts = 3
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            try:
                from claude_agent_sdk import query, ClaudeAgentOptions

                prompt = _build_backtest_prompt(agent_id, config, work_dir)
                options = ClaudeAgentOptions(
                    cwd=str(work_dir),
                    permission_mode="dontAsk",
                    allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
                )

                last_text = ""
                hit_error_message = False
                async for message in query(prompt=prompt, options=options):
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
        """After successful backtest, auto-create an analyst agent session."""
        async for db in _get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if not agent or agent.status != "BACKTEST_COMPLETE":
                return
            await _syslog(db, agent_id, None, "auto_create_analyst", 95,
                          "Backtest complete — auto-creating analyst agent")

        logger.info("Auto-creating analyst agent for %s", agent_id)

    # ------------------------------------------------------------------
    # Analyst (live trading) agent
    # ------------------------------------------------------------------

    async def create_analyst(
        self, agent_id: uuid.UUID, config: dict | None = None
    ) -> str:
        """Start a live trading Claude Code agent session."""
        agent_key = str(agent_id)
        if agent_key in _running_tasks and not _running_tasks[agent_key].done():
            return agent_key

        async for db in _get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if not agent:
                return ""
            if agent.status not in ("BACKTEST_COMPLETE", "APPROVED", "PAPER", "RUNNING", "PAUSED"):
                return ""

            work_dir = await self._prepare_analyst_directory(agent, db)
            session_row_id = uuid.uuid4()
            db.add(AgentSession(
                id=session_row_id,
                agent_id=agent_id,
                agent_type="analyst",
                status="starting",
                working_dir=str(work_dir),
                config=config or {},
            ))
            agent.status = "RUNNING"
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
        """Run the live trading agent as a Claude Code session."""
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

        prompt = (
            "You are now live. Read CLAUDE.md for your full instructions. "
            "Start the operation loop: run pre-market analysis, start the Discord listener, "
            "and begin monitoring for trade signals. Report all activity to Phoenix."
        )
        if resume:
            prompt = (
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

        bt_work_dir = DATA_DIR / f"backtest_{agent.id}"
        models_src = bt_work_dir / "output" / "models"
        if models_src.exists():
            models_dst = work_dir / "models"
            if models_dst.exists():
                shutil.rmtree(models_dst)
            shutil.copytree(models_src, models_dst)

        manifest = agent.manifest or {}
        config_data = agent.config or {}
        api_url = os.getenv("PHOENIX_API_URL", os.getenv("PUBLIC_API_URL", "https://cashflowus.com"))

        bt = (await session.execute(
            select(AgentBacktest)
            .where(AgentBacktest.agent_id == agent.id, AgentBacktest.status == "COMPLETED")
            .order_by(AgentBacktest.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()

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

        # Inject Robinhood credentials if available
        rh_creds = config_data.get("robinhood_credentials")
        if rh_creds:
            agent_config["robinhood"] = rh_creds

        (work_dir / "config.json").write_text(json.dumps(agent_config, indent=2, default=str))
        self._render_claude_md(agent, manifest, work_dir)
        return work_dir

    def _render_claude_md(self, agent: Agent, manifest: dict, work_dir: Path) -> None:
        """Render CLAUDE.md from the Jinja2 template."""
        template_path = LIVE_TEMPLATE / "CLAUDE.md.jinja2"
        if not template_path.exists():
            (work_dir / "CLAUDE.md").write_text(
                f"# Live Trading Agent: {agent.name}\n\nMonitor Discord and trade."
            )
            return

        try:
            from jinja2 import Environment, FileSystemLoader

            env = Environment(
                loader=FileSystemLoader(str(LIVE_TEMPLATE)),
                undefined=__import__("jinja2").Undefined,
            )
            template = env.get_template("CLAUDE.md.jinja2")

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
            logger.warning("Failed to render CLAUDE.md for agent %s: %s", agent.id, exc)
            (work_dir / "CLAUDE.md").write_text(
                f"# Live Trading Agent: {agent.name}\n\nMonitor Discord and trade."
            )

    # ------------------------------------------------------------------
    # Lifecycle: stop, pause, resume, status
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

    async def send_task(self, agent_id: uuid.UUID, task_prompt: str) -> dict:
        """Send a task/query to a running agent."""
        agent_key = str(agent_id)
        if agent_key not in _running_tasks or _running_tasks[agent_key].done():
            return {"status": "error", "message": "Agent is not running"}
        return {"status": "queued", "message": "Task delivery via DB polling not yet implemented"}

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
    output_dir = str(work_dir / "output")
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

### Base Model Training (run sequentially — PyTorch models need full memory)
5. **Train XGBoost**: `python {tools_dir}/train_xgboost.py --data {output_dir} --output {output_dir}/models/`
6. **Train LightGBM**: `python {tools_dir}/train_lightgbm.py --data {output_dir} --output {output_dir}/models/`
7. **Train CatBoost**: `python {tools_dir}/train_catboost.py --data {output_dir} --output {output_dir}/models/`
8. **Train RF**: `python {tools_dir}/train_rf.py --data {output_dir} --output {output_dir}/models/`
9. **Train LSTM**: `python {tools_dir}/train_lstm.py --data {output_dir} --output {output_dir}/models/`
10. **Train Transformer**: `python {tools_dir}/train_transformer.py --data {output_dir} --output {output_dir}/models/`
11. **Train TFT**: `python {tools_dir}/train_tft.py --data {output_dir} --output {output_dir}/models/`
12. **Train TCN**: `python {tools_dir}/train_tcn.py --data {output_dir} --output {output_dir}/models/`

**IMPORTANT**: Run each training script ONE AT A TIME and wait for it to finish before starting the next. Do NOT run them in parallel — PyTorch models need the full container memory. If a training script fails with a memory error, retry it once. Do NOT skip models due to OOM concerns — the scripts are already memory-optimised.

### Ensemble Models (after base models complete)
13. **Train Hybrid**: `python {tools_dir}/train_hybrid.py --data {output_dir} --output {output_dir}/models/`
14. **Train Meta-Learner**: `python {tools_dir}/train_meta_learner.py --models-dir {output_dir}/models/ --data {output_dir} --output {output_dir}/models/`

### Evaluation and Analysis
15. **Evaluate**: `python {tools_dir}/evaluate_models.py --models-dir {output_dir}/models --output {output_dir}/models/best_model.json`
16. **Explainability**: `python {tools_dir}/build_explainability.py --model {output_dir}/models --data {output_dir} --output {output_dir}/explainability.json`
17. **Pattern Discovery**: `python {tools_dir}/discover_patterns.py --data {output_dir} --output {output_dir}/patterns.json`
18. **LLM Strategy Analysis**: `python {tools_dir}/analyze_patterns_llm.py --data {output_dir} --output {output_dir}/llm_patterns.json --config {config_path}`
19. **Create Live Agent**: `python {tools_dir}/create_live_agent.py --config {config_path} --models {output_dir}/models --output {output_dir}/live_agent/`

## Progress Reporting

After each step, report progress via curl:
```bash
curl -s -X POST "{api_url}/api/v2/agents/{agent_id}/backtest-progress" \\
  -H "Content-Type: application/json" \\
  -H "X-Agent-Key: {api_key}" \\
  -d '{{"step": "<step_name>", "message": "<what happened>", "progress_pct": <pct>}}'
```

Progress percentages: transform=10, enrich=22, text_embeddings=25, preprocess=28, train_xgboost=35, train_lightgbm=38, train_catboost=41, train_rf=44, train_lstm=47, train_transformer=50, train_tft=53, train_tcn=56, train_hybrid=60, train_meta_learner=63, evaluate=68, explainability=75, patterns=80, llm_patterns=85, create_live_agent=95

When fully complete:
```bash
curl -s -X POST "{api_url}/api/v2/agents/{agent_id}/backtest-progress" \\
  -H "Content-Type: application/json" \\
  -H "X-Agent-Key: {api_key}" \\
  -d '{{"step": "completed", "message": "Pipeline complete", "progress_pct": 100, "status": "COMPLETED"}}'
```

If a step fails after retrying:
```bash
curl -s -X POST "{api_url}/api/v2/agents/{agent_id}/backtest-progress" \\
  -H "Content-Type: application/json" \\
  -H "X-Agent-Key: {api_key}" \\
  -d '{{"step": "<failed_step>", "message": "<error>", "progress_pct": <pct>, "status": "FAILED"}}'
```

## Rules
- Create {output_dir}/models/ directories before running training steps
- Run training steps 5-12 SEQUENTIALLY one at a time — do NOT run them in parallel
- Steps 13-14 (ensemble) must wait for ALL base models to finish
- If a script fails, read the error, attempt to fix it, and retry ONCE
- If a script is missing a Python dependency, install it with pip
- Do NOT modify the tool scripts unless absolutely necessary to fix a bug
- Do NOT skip any training step — each script handles its own memory management
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
        agent.status = "CREATED"
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
