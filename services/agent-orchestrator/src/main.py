"""Phoenix Agent Orchestrator — microservice for Claude Code agent lifecycle.

Manages starting, stopping, resuming, and monitoring live trading agents.
Each agent runs as an asyncio.Task wrapping a Claude Code SDK session.
A background keepalive loop ensures agents that should be running are
automatically restarted when their sessions end cleanly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PHOENIX_API_URL = os.environ.get("PHOENIX_API_URL", "http://phoenix-api:8011")
BROKER_GATEWAY_URL = os.environ.get("BROKER_GATEWAY_URL", "http://phoenix-broker-gateway:8040")
INFERENCE_SERVICE_URL = os.environ.get("INFERENCE_SERVICE_URL", "http://phoenix-inference-service:8045")

REPO_ROOT = Path(os.environ.get("PHOENIX_REPO_ROOT", "/app"))
LIVE_TEMPLATE = REPO_ROOT / "agents" / "templates" / "live-trader-v1"
DATA_DIR = REPO_ROOT / "data"

KEEPALIVE_INTERVAL_SECONDS = int(os.environ.get("KEEPALIVE_INTERVAL_SECONDS", "60"))
MAX_ERROR_RESTARTS_PER_HOUR = int(os.environ.get("AGENT_MAX_RESTARTS_PER_HOUR", "3"))
MAX_CLEAN_RESTARTS_PER_HOUR = int(os.environ.get("AGENT_MAX_CLEAN_RESTARTS_PER_HOUR", "20"))

_engine = create_async_engine(DATABASE_URL, pool_size=10, max_overflow=5, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)

_running_agents: dict[str, asyncio.Task] = {}
_session_ids: dict[str, str] = {}
_agent_start_times: dict[str, float] = {}
_restart_history: dict[str, list[float]] = {}
_keepalive_task: asyncio.Task | None = None


class StartRequest(BaseModel):
    mode: str = Field(default="live", pattern="^(live|paper)$")
    resume: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class StopResponse(BaseModel):
    status: str
    agent_id: str | None = None


class StatusResponse(BaseModel):
    running: bool
    session_id: str | None = None
    uptime_seconds: float | None = None


async def _get_db() -> AsyncSession:
    return _session_factory()


async def _fetch_agent(db: AsyncSession, agent_id: str):
    from shared.db.models.agent import Agent
    result = await db.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    return result.scalar_one_or_none()


async def _fetch_latest_session(db: AsyncSession, agent_id: str):
    from shared.db.models.agent_session import AgentSession
    result = await db.execute(
        select(AgentSession)
        .where(
            AgentSession.agent_id == uuid.UUID(agent_id),
            AgentSession.agent_type.in_(["analyst", "live_trader"]),
        )
        .order_by(AgentSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _prepare_working_directory(agent_id: str, agent: Any, config: dict[str, Any]) -> Path:
    """Build the agent's working directory with tools, skills, models, and config."""
    work_dir = DATA_DIR / "live_agents" / agent_id
    work_dir.mkdir(parents=True, exist_ok=True)

    for subdir in ("tools", "skills"):
        src = LIVE_TEMPLATE / subdir
        dst = work_dir / subdir
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    commands_src = LIVE_TEMPLATE / ".claude" / "commands"
    if commands_src.exists():
        commands_dst = work_dir / ".claude" / "commands"
        commands_dst.parent.mkdir(parents=True, exist_ok=True)
        if commands_dst.exists():
            shutil.rmtree(commands_dst)
        shutil.copytree(commands_src, commands_dst)

    _download_model_bundle(agent_id, work_dir)

    manifest = getattr(agent, "manifest", {}) or {}
    config_data = getattr(agent, "config", {}) or {}
    merged_config = {
        "agent_id": agent_id,
        "agent_name": getattr(agent, "name", ""),
        "channel_name": getattr(agent, "channel_name", "") or "",
        "analyst_name": getattr(agent, "analyst_name", "") or "",
        "current_mode": config.get("mode", getattr(agent, "current_mode", "conservative")),
        "phoenix_api_url": PHOENIX_API_URL,
        "broker_gateway_url": BROKER_GATEWAY_URL,
        "inference_service_url": INFERENCE_SERVICE_URL,
        "phoenix_api_key": getattr(agent, "phoenix_api_key", "") or "",
        "redis_url": REDIS_URL,
        "risk": manifest.get("risk", config_data.get("risk_params", {})),
        "risk_params": manifest.get("risk", config_data.get("risk_params", {})),
        "modes": manifest.get("modes", {}),
        "rules": manifest.get("rules", []),
        "models": manifest.get("models", {}),
        "knowledge": manifest.get("knowledge", {}),
        **config,
    }

    (work_dir / "config.json").write_text(json.dumps(merged_config, indent=2, default=str))
    _write_claude_settings(work_dir)
    _render_claude_md(agent, manifest, work_dir)

    startup_src = LIVE_TEMPLATE / "startup.sh"
    if startup_src.exists():
        startup_dst = work_dir / "startup.sh"
        shutil.copy2(startup_src, startup_dst)
        startup_dst.chmod(0o755)

    return work_dir


def _download_model_bundle(agent_id: str, work_dir: Path) -> None:
    """Download the latest approved model bundle from MinIO (sync, best-effort)."""
    try:
        from minio import Minio

        endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
        ak = os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER", "minioadmin")
        sk = os.environ.get("MINIO_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
        secure = endpoint.startswith("https")
        clean_endpoint = endpoint.replace("https://", "").replace("http://", "")
        client = Minio(clean_endpoint, access_key=ak, secret_key=sk, secure=secure)

        bucket = "phoenix-models"
        prefix = f"models/{agent_id}/"
        objects = list(client.list_objects(bucket, prefix=prefix, recursive=True))
        bundles = [o for o in objects if o.object_name.endswith("bundle.tar.gz")]
        if not bundles:
            log.info("No model bundle found for agent %s in MinIO", agent_id)
            return

        bundles.sort(key=lambda o: o.last_modified, reverse=True)
        latest = bundles[0]

        import io
        import tarfile

        models_dir = work_dir / "models"
        models_dir.mkdir(parents=True, exist_ok=True)

        response = client.get_object(bucket, latest.object_name)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()

        tar_buffer = io.BytesIO(data)
        with tarfile.open(fileobj=tar_buffer, mode="r:gz") as tar:
            tar.extractall(path=models_dir, filter="data")

        log.info("Extracted model bundle %s to %s", latest.object_name, models_dir)
    except Exception as exc:
        log.warning("Model bundle download failed for agent %s (non-fatal): %s", agent_id, exc)


def _write_claude_settings(work_dir: Path) -> None:
    """Write .claude/settings.json with SDK permissions."""
    claude_dir = work_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings: dict = {
        "permissions": {
            "allow": [
                "Bash(python *)", "Bash(python3 *)", "Bash(pip *)",
                "Bash(pip3 *)", "Bash(curl *)", "Read", "Write", "Edit", "Grep", "Glob",
            ],
            "deny": [
                "Bash(rm -rf /)", "Bash(rm -rf ~)", "Bash(git push --force *)",
                "Bash(shutdown *)", "Bash(reboot *)",
            ],
        },
    }

    settings_path = claude_dir / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2))
    settings_path.chmod(0o600)


def _render_claude_md(agent: Any, manifest: dict, work_dir: Path) -> None:
    """Render CLAUDE.md from the Jinja2 template."""
    template_path = LIVE_TEMPLATE / "CLAUDE.md.jinja2"
    fallback = f"# Live Trading Agent: {getattr(agent, 'name', 'Agent')}\n\nMonitor Discord and trade."

    if not template_path.exists():
        (work_dir / "CLAUDE.md").write_text(fallback)
        return

    try:
        from jinja2 import Environment, FileSystemLoader, Undefined

        env = Environment(loader=FileSystemLoader(str(LIVE_TEMPLATE)), undefined=Undefined)
        template = env.get_template("CLAUDE.md.jinja2")

        characters = {
            "balanced-intraday": (
                "You are a balanced intraday trader. You take calculated risks based on "
                "model confidence and pattern matches."
            ),
            "aggressive-scalper": (
                "You are an aggressive scalper. You act fast on high-confidence signals "
                "and aim for quick profits."
            ),
            "conservative-swing": (
                "You are a conservative swing trader. You wait for high-conviction setups "
                "and hold positions for days."
            ),
        }

        identity = manifest.get("identity", {})
        character_key = identity.get("character", "balanced-intraday")

        rendered = template.render(
            identity={
                "name": getattr(agent, "name", "Agent"),
                "channel": getattr(agent, "channel_name", "") or "",
                "analyst": getattr(agent, "analyst_name", "") or "",
            },
            character_description=characters.get(character_key, characters["balanced-intraday"]),
            modes=manifest.get("modes", {}),
            rules=manifest.get("rules", []),
            risk=manifest.get("risk", {}),
            knowledge=manifest.get("knowledge", {}),
            models=manifest.get("models", {}),
            broker_gateway_url=BROKER_GATEWAY_URL,
            inference_service_url=INFERENCE_SERVICE_URL,
        )
        (work_dir / "CLAUDE.md").write_text(rendered)
    except Exception as exc:
        log.warning("Failed to render CLAUDE.md for agent %s: %s", getattr(agent, "id", "?"), exc)
        (work_dir / "CLAUDE.md").write_text(fallback)


async def _run_agent_session(agent_id: str, work_dir: Path, session_row_id: uuid.UUID, resume: bool = False) -> None:
    """Run a Claude Code SDK session for the agent. Stubbed for runtime without npm."""
    from shared.db.models.agent import Agent
    from shared.db.models.agent_session import AgentSession

    db = await _get_db()
    try:
        sess = (await db.execute(
            select(AgentSession).where(AgentSession.id == session_row_id)
        )).scalar_one_or_none()
        if sess:
            sess.status = "running"
        agent = (await db.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))).scalar_one_or_none()
        if agent:
            agent.worker_status = "RUNNING"
            agent.updated_at = datetime.now(timezone.utc)
        await db.commit()
    finally:
        await db.close()

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query

        prompt = (
            f"First, run: `export HOME={work_dir}` so any Robinhood session gets cached. "
            "You are now live. Read CLAUDE.md for your full instructions.\n"
            "FIRST: run `bash startup.sh` to verify your environment.\n"
            "Then enter your SIGNAL POLLING LOOP:\n"
            "1. Run: `python3 tools/check_messages.py --config config.json`\n"
            "2. If count > 0, process each signal via decision_engine.py\n"
            "3. Sleep 5 seconds\n4. Repeat\n"
            "NEVER exit this loop."
        )

        options = ClaudeAgentOptions(
            work_dir=str(work_dir),
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        existing_sid = _session_ids.get(agent_id)
        if resume and existing_sid:
            options.resume = existing_sid

        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "session_id"):
                _session_ids[agent_id] = message.session_id
                db = await _get_db()
                try:
                    sess = (await db.execute(
                        select(AgentSession).where(AgentSession.id == session_row_id)
                    )).scalar_one_or_none()
                    if sess:
                        sess.session_id = message.session_id
                    await db.commit()
                finally:
                    await db.close()

    except ImportError:
        log.warning("claude_agent_sdk not available — agent %s session is a no-op stub", agent_id)
        await asyncio.sleep(1)
    except asyncio.CancelledError:
        log.info("Agent %s session cancelled", agent_id)
        raise
    except Exception as exc:
        log.error("Agent %s session failed: %s", agent_id, exc)
        db = await _get_db()
        try:
            sess = (await db.execute(
                select(AgentSession).where(AgentSession.id == session_row_id)
            )).scalar_one_or_none()
            if sess:
                sess.status = "error"
                sess.error_message = str(exc)[:500]
                sess.stopped_at = datetime.now(timezone.utc)
            await db.commit()
        finally:
            await db.close()
        return
    finally:
        _running_agents.pop(agent_id, None)
        _agent_start_times.pop(agent_id, None)

    db = await _get_db()
    try:
        sess = (await db.execute(
            select(AgentSession).where(AgentSession.id == session_row_id)
        )).scalar_one_or_none()
        if sess:
            sess.status = "completed"
            sess.stopped_at = datetime.now(timezone.utc)
        agent = (await db.execute(
            select(Agent).where(Agent.id == uuid.UUID(agent_id))
        )).scalar_one_or_none()
        if agent:
            agent.worker_status = "STOPPED"
            agent.updated_at = datetime.now(timezone.utc)
        await db.commit()
    finally:
        await db.close()


async def _keepalive_loop() -> None:
    """Background loop: restart agents that should be running but whose sessions ended."""
    while True:
        await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
        try:
            await _keepalive_tick()
        except Exception:
            log.exception("Keepalive tick failed")


async def _keepalive_tick() -> None:
    """Single keepalive check iteration."""
    from shared.db.models.agent import Agent
    from shared.db.models.agent_session import AgentSession

    db = await _get_db()
    try:
        result = await db.execute(
            select(Agent).where(Agent.status.in_(["RUNNING", "PAPER"]))
        )
        candidates = list(result.scalars().all())
    finally:
        await db.close()

    now_ts = time.time()

    for agent in candidates:
        agent_key = str(agent.id)

        if agent_key in _running_agents and not _running_agents[agent_key].done():
            continue

        db = await _get_db()
        try:
            last_sess = (await db.execute(
                select(AgentSession)
                .where(
                    AgentSession.agent_id == agent.id,
                    AgentSession.agent_type.in_(["analyst", "live_trader"]),
                )
                .order_by(AgentSession.started_at.desc())
                .limit(1)
            )).scalar_one_or_none()
        finally:
            await db.close()

        if last_sess is None:
            continue

        if last_sess.status in ("error", "interrupted"):
            continue

        if last_sess.status in ("running", "starting"):
            continue

        history = _restart_history.get(agent_key, [])
        history = [ts for ts in history if ts > now_ts - 3600]
        _restart_history[agent_key] = history

        max_restarts = MAX_CLEAN_RESTARTS_PER_HOUR if last_sess.status == "completed" else MAX_ERROR_RESTARTS_PER_HOUR
        if len(history) >= max_restarts:
            log.warning(
                "Circuit breaker: agent %s restarted %d times in the last hour (max %d) — skipping",
                agent_key, len(history), max_restarts,
            )
            continue

        log.info("Keepalive restarting agent %s (last_status=%s)", agent_key, last_sess.status)

        try:
            work_dir = DATA_DIR / "live_agents" / agent_key
            db = await _get_db()
            try:
                if not work_dir.exists():
                    work_dir = _prepare_working_directory(agent_key, agent, {})

                session_row_id = uuid.uuid4()
                from shared.db.models.agent_session import AgentSession as AgentSess
                db.add(AgentSess(
                    id=session_row_id,
                    agent_id=agent.id,
                    agent_type="live_trader",
                    status="starting",
                    working_dir=str(work_dir),
                    config={},
                    trading_mode="paper" if agent.status == "PAPER" else "live",
                ))
                await db.commit()
            finally:
                await db.close()

            task = asyncio.create_task(
                _run_agent_session(agent_key, work_dir, session_row_id, resume=True)
            )
            _running_agents[agent_key] = task
            _agent_start_times[agent_key] = now_ts
            _restart_history[agent_key].append(now_ts)
        except Exception as exc:
            log.warning("Keepalive restart failed for agent %s: %s", agent_key, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _keepalive_task
    _keepalive_task = asyncio.create_task(_keepalive_loop())
    log.info("Agent orchestrator started — keepalive interval %ds", KEEPALIVE_INTERVAL_SECONDS)
    yield
    if _keepalive_task:
        _keepalive_task.cancel()
        try:
            await _keepalive_task
        except asyncio.CancelledError:
            pass

    for agent_key, task in list(_running_agents.items()):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _running_agents.clear()
    _session_ids.clear()

    await _engine.dispose()
    log.info("Agent orchestrator shutdown complete")


app = FastAPI(title="Phoenix Agent Orchestrator", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "running_agents": len([k for k, t in _running_agents.items() if not t.done()]),
        "total_tracked": len(_running_agents),
    }


@app.get("/agents")
async def list_agents():
    agents = []
    for agent_key, task in _running_agents.items():
        start_time = _agent_start_times.get(agent_key)
        agents.append({
            "agent_id": agent_key,
            "running": not task.done(),
            "session_id": _session_ids.get(agent_key),
            "uptime_seconds": round(time.time() - start_time, 1) if start_time else None,
        })
    return {"agents": agents, "count": len(agents)}


@app.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str, body: StartRequest):
    if agent_id in _running_agents and not _running_agents[agent_id].done():
        return {
            "status": "already_running",
            "session_id": _session_ids.get(agent_id),
        }

    db = await _get_db()
    try:
        agent = await _fetch_agent(db, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        eligible = ("BACKTEST_COMPLETE", "APPROVED", "PAPER", "RUNNING", "PAUSED")
        if agent.status not in eligible:
            raise HTTPException(
                status_code=409,
                detail=f"Agent status '{agent.status}' not eligible. Must be one of {eligible}",
            )

        work_dir = _prepare_working_directory(agent_id, agent, body.config)

        session_row_id = uuid.uuid4()
        from shared.db.models.agent_session import AgentSession
        db.add(AgentSession(
            id=session_row_id,
            agent_id=uuid.UUID(agent_id),
            agent_type="live_trader",
            status="starting",
            working_dir=str(work_dir),
            config=body.config,
            trading_mode="paper" if body.mode == "paper" else "live",
        ))

        if body.mode != "paper" and agent.status != "PAPER":
            agent.status = "RUNNING"
        agent.worker_status = "STARTING"
        agent.updated_at = datetime.now(timezone.utc)
        await db.commit()
    finally:
        await db.close()

    task = asyncio.create_task(
        _run_agent_session(agent_id, work_dir, session_row_id, resume=body.resume)
    )
    _running_agents[agent_id] = task
    _agent_start_times[agent_id] = time.time()

    return {"status": "started", "session_id": str(session_row_id)}


@app.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    task = _running_agents.get(agent_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    _running_agents.pop(agent_id, None)
    _session_ids.pop(agent_id, None)
    _agent_start_times.pop(agent_id, None)

    db = await _get_db()
    try:
        agent = await _fetch_agent(db, agent_id)
        if agent:
            if agent.status == "RUNNING":
                agent.status = "PAUSED"
            agent.worker_status = "STOPPED"
            agent.updated_at = datetime.now(timezone.utc)
            await db.commit()
    finally:
        await db.close()

    return StopResponse(status="stopped", agent_id=agent_id)


@app.post("/agents/{agent_id}/resume")
async def resume_agent(agent_id: str):
    if agent_id in _running_agents and not _running_agents[agent_id].done():
        return {"status": "already_running", "session_id": _session_ids.get(agent_id)}

    db = await _get_db()
    try:
        agent = await _fetch_agent(db, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        work_dir = DATA_DIR / "live_agents" / agent_id
        if not work_dir.exists():
            work_dir = _prepare_working_directory(agent_id, agent, {})

        session_row_id = uuid.uuid4()
        from shared.db.models.agent_session import AgentSession
        db.add(AgentSession(
            id=session_row_id,
            agent_id=uuid.UUID(agent_id),
            agent_type="live_trader",
            status="starting",
            working_dir=str(work_dir),
            config={},
            trading_mode="paper" if agent.status == "PAPER" else "live",
        ))
        agent.worker_status = "STARTING"
        agent.updated_at = datetime.now(timezone.utc)
        await db.commit()
    finally:
        await db.close()

    task = asyncio.create_task(
        _run_agent_session(agent_id, work_dir, session_row_id, resume=True)
    )
    _running_agents[agent_id] = task
    _agent_start_times[agent_id] = time.time()

    return {"status": "resumed", "session_id": str(session_row_id)}


@app.get("/agents/{agent_id}/status")
async def agent_status(agent_id: str):
    task = _running_agents.get(agent_id)
    session_id = _session_ids.get(agent_id)
    start_time = _agent_start_times.get(agent_id)

    if not task:
        return StatusResponse(running=False, session_id=session_id)

    uptime = round(time.time() - start_time, 1) if start_time else None
    return StatusResponse(running=not task.done(), session_id=session_id, uptime_seconds=uptime)
