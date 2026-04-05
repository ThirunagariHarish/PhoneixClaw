"""Agent Manager — lifecycle management for live trading Claude Code agents.

Each analyst (e.g., "SPX Vinod") becomes a persistent Claude Code agent that:
  - Monitors its Discord channel for new signals
  - Runs inference on each signal using the trained model
  - Checks risk rules and executes trades via Robinhood
  - Reports activity and metrics back to Phoenix via HTTP callbacks

Uses ClaudeSDKClient for session persistence so agents can be paused/resumed.
"""

import asyncio
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from shared.db.engine import get_session as _get_session
from shared.db.models.agent import Agent, AgentBacktest
from shared.db.models.system_log import SystemLog

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
LIVE_TEMPLATE = REPO_ROOT / "agents" / "templates" / "live-trader-v1"
AGENTS_DIR = REPO_ROOT / "data" / "live_agents"

_running_agents: dict[str, asyncio.Task] = {}
_session_ids: dict[str, str] = {}


async def start_agent(agent_id: uuid.UUID) -> dict:
    """Start a live trading agent as a Claude Code session."""
    agent_key = str(agent_id)
    if agent_key in _running_agents and not _running_agents[agent_key].done():
        return {"status": "already_running", "agent_id": agent_key}

    async for session in _get_session():
        agent = (await session.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if not agent:
            return {"status": "error", "message": "Agent not found"}

        if agent.status not in ("BACKTEST_COMPLETE", "APPROVED", "PAPER", "RUNNING", "PAUSED"):
            return {"status": "error", "message": f"Agent not ready for live trading (status: {agent.status})"}

        work_dir = await _prepare_agent_directory(agent, session)

        agent.status = "RUNNING"
        agent.worker_status = "STARTING"
        agent.updated_at = datetime.now(timezone.utc)
        await session.commit()

    task = asyncio.create_task(_run_live_agent(agent_id, work_dir))
    _running_agents[agent_key] = task
    return {"status": "starting", "agent_id": agent_key, "work_dir": str(work_dir)}


async def stop_agent(agent_id: uuid.UUID) -> dict:
    """Stop a running live trading agent."""
    agent_key = str(agent_id)
    task = _running_agents.get(agent_key)

    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    _running_agents.pop(agent_key, None)
    _session_ids.pop(agent_key, None)

    async for session in _get_session():
        agent = (await session.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if agent:
            agent.worker_status = "STOPPED"
            agent.updated_at = datetime.now(timezone.utc)
            await session.commit()

    return {"status": "stopped", "agent_id": agent_key}


async def pause_agent(agent_id: uuid.UUID) -> dict:
    """Pause a running agent (preserves session for resume)."""
    agent_key = str(agent_id)
    task = _running_agents.get(agent_key)

    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    _running_agents.pop(agent_key, None)

    async for session in _get_session():
        agent = (await session.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if agent:
            agent.status = "PAUSED"
            agent.worker_status = "STOPPED"
            agent.updated_at = datetime.now(timezone.utc)
            await session.commit()

    return {"status": "paused", "agent_id": agent_key}


async def resume_agent(agent_id: uuid.UUID) -> dict:
    """Resume a paused agent, continuing its previous session if possible."""
    agent_key = str(agent_id)
    if agent_key in _running_agents and not _running_agents[agent_key].done():
        return {"status": "already_running", "agent_id": agent_key}

    async for session in _get_session():
        agent = (await session.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if not agent:
            return {"status": "error", "message": "Agent not found"}

        work_dir = AGENTS_DIR / agent_key
        if not work_dir.exists():
            work_dir = await _prepare_agent_directory(agent, session)

        agent.status = "RUNNING"
        agent.worker_status = "STARTING"
        agent.updated_at = datetime.now(timezone.utc)
        await session.commit()

    task = asyncio.create_task(_run_live_agent(agent_id, work_dir, resume=True))
    _running_agents[agent_key] = task
    return {"status": "resuming", "agent_id": agent_key}


async def _prepare_agent_directory(agent: Agent, session) -> Path:
    """Build the agent's working directory with CLAUDE.md, tools, skills, config."""
    work_dir = AGENTS_DIR / str(agent.id)
    work_dir.mkdir(parents=True, exist_ok=True)

    tools_dst = work_dir / "tools"
    if tools_dst.exists():
        shutil.rmtree(tools_dst)
    shutil.copytree(LIVE_TEMPLATE / "tools", tools_dst)

    skills_dst = work_dir / "skills"
    if skills_dst.exists():
        shutil.rmtree(skills_dst)
    shutil.copytree(LIVE_TEMPLATE / "skills", skills_dst)

    claude_settings_dst = work_dir / ".claude"
    claude_settings_dst.mkdir(exist_ok=True)
    shutil.copy2(LIVE_TEMPLATE / ".claude" / "settings.json", claude_settings_dst / "settings.json")

    manifest = agent.manifest or {}
    config_data = agent.config or {}

    bt = (await session.execute(
        select(AgentBacktest)
        .where(AgentBacktest.agent_id == agent.id, AgentBacktest.status == "COMPLETED")
        .order_by(AgentBacktest.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    bt_work_dir = REPO_ROOT / "data" / f"backtest_{agent.id}"
    models_src = bt_work_dir / "output" / "models"
    if models_src.exists():
        models_dst = work_dir / "models"
        if models_dst.exists():
            shutil.rmtree(models_dst)
        shutil.copytree(models_src, models_dst)

    api_url = os.getenv("PHOENIX_API_URL", os.getenv("PUBLIC_API_URL", "https://cashflowus.com"))
    agent_config = {
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "channel_name": agent.channel_name or "",
        "analyst_name": agent.analyst_name or "",
        "current_mode": agent.current_mode or "conservative",
        "phoenix_api_url": api_url,
        "phoenix_api_key": agent.phoenix_api_key or "",
        "discord_token": config_data.get("discord_token", ""),
        "channel_id": config_data.get("channel_id", config_data.get("selected_channel", {}).get("channel_id", "")),
        "server_id": config_data.get("server_id", ""),
        "risk": manifest.get("risk", config_data.get("risk_params", {})),
        "modes": manifest.get("modes", {}),
        "rules": manifest.get("rules", []),
        "models": manifest.get("models", {}),
        "knowledge": manifest.get("knowledge", {}),
    }
    (work_dir / "config.json").write_text(json.dumps(agent_config, indent=2, default=str))

    _render_claude_md(agent, manifest, work_dir)

    return work_dir


def _render_claude_md(agent: Agent, manifest: dict, work_dir: Path) -> None:
    """Render CLAUDE.md from the Jinja2 template using the agent's manifest."""
    template_path = LIVE_TEMPLATE / "CLAUDE.md.jinja2"
    if not template_path.exists():
        (work_dir / "CLAUDE.md").write_text(f"# Live Trading Agent: {agent.name}\n\nMonitor Discord and trade.")
        return

    try:
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader(str(LIVE_TEMPLATE)), undefined=__import__("jinja2").Undefined)
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
        (work_dir / "CLAUDE.md").write_text(f"# Live Trading Agent: {agent.name}\n\nMonitor Discord and trade.")


async def _run_live_agent(
    agent_id: uuid.UUID,
    work_dir: Path,
    resume: bool = False,
) -> None:
    """Run the live trading agent as a Claude Code session."""
    agent_key = str(agent_id)

    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
    except ImportError:
        logger.error("claude-agent-sdk not installed — cannot start live agent")
        async for session in _get_session():
            agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if agent:
                agent.worker_status = "ERROR"
                agent.updated_at = datetime.now(timezone.utc)
            session.add(SystemLog(
                id=uuid.uuid4(), source="agent", level="ERROR", service="agent-manager",
                agent_id=agent_key, message="claude-agent-sdk not installed",
            ))
            await session.commit()
        return

    async for session in _get_session():
        agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if agent:
            agent.worker_status = "RUNNING"
            agent.updated_at = datetime.now(timezone.utc)
        session.add(SystemLog(
            id=uuid.uuid4(), source="agent", level="INFO", service="agent-manager",
            agent_id=agent_key,
            message=f"Live agent {'resumed' if resume else 'started'} in {work_dir}",
        ))
        await session.commit()

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
        permission_mode="bypassPermissions",
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

            if hasattr(message, "is_error") and getattr(message, "is_error", False):
                async for session in _get_session():
                    agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                    if agent:
                        agent.worker_status = "ERROR"
                        agent.updated_at = datetime.now(timezone.utc)
                    session.add(SystemLog(
                        id=uuid.uuid4(), source="agent", level="ERROR", service="agent-manager",
                        agent_id=agent_key, message=f"Agent error: {last_text}",
                    ))
                    await session.commit()
                return

        async for session in _get_session():
            agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if agent:
                agent.worker_status = "STOPPED"
                agent.updated_at = datetime.now(timezone.utc)
            session.add(SystemLog(
                id=uuid.uuid4(), source="agent", level="INFO", service="agent-manager",
                agent_id=agent_key, message="Agent session completed naturally",
            ))
            await session.commit()

    except asyncio.CancelledError:
        logger.info("Live agent %s cancelled (pause/stop)", agent_id)
        raise
    except Exception as exc:
        logger.exception("Live agent %s crashed", agent_id)
        async for session in _get_session():
            agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if agent:
                agent.worker_status = "ERROR"
                agent.updated_at = datetime.now(timezone.utc)
            session.add(SystemLog(
                id=uuid.uuid4(), source="agent", level="ERROR", service="agent-manager",
                agent_id=agent_key, message=f"Agent crash: {str(exc)[:500]}",
            ))
            await session.commit()
    finally:
        _running_agents.pop(agent_key, None)


def get_running_agents() -> list[str]:
    return [k for k, t in _running_agents.items() if not t.done()]


def get_agent_status(agent_id: str) -> dict:
    task = _running_agents.get(agent_id)
    session_id = _session_ids.get(agent_id)
    if not task:
        return {"running": False, "session_id": session_id}
    return {
        "running": not task.done(),
        "cancelled": task.cancelled() if task.done() else False,
        "session_id": session_id,
    }
