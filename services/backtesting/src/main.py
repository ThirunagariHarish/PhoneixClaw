"""Phoenix backtesting service — lifecycle management for Claude Code backtest sessions.

Manages starting, monitoring, and approving backtesting runs. Each backtest
runs as an asyncio.Task wrapping a Claude Code SDK session that executes the
12-step backtesting pipeline from ``agents/backtesting/``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")

REPO_ROOT = Path(os.environ.get("PHOENIX_REPO_ROOT", "/app"))
BACKTEST_TEMPLATE = REPO_ROOT / "agents" / "backtesting"
DATA_DIR = REPO_ROOT / "data" / "backtests"

_engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=3, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)

_active_backtests: dict[str, dict[str, Any]] = {}


class BacktestRequest(BaseModel):
    agent_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    date_range: dict[str, str] = Field(
        default_factory=dict,
        description="Keys: start_date, end_date (YYYY-MM-DD)",
    )


class ApproveRequest(BaseModel):
    approved_by: str = "system"


class BacktestSummary(BaseModel):
    backtest_id: str
    agent_id: str
    status: str
    created_at: str
    finished_at: str | None = None
    error: str | None = None


async def _get_db() -> AsyncSession:
    return _session_factory()


def _prepare_backtest_directory(backtest_id: str, agent_id: str, config: dict[str, Any]) -> Path:
    """Build a working directory for this backtest run, copying the template tools."""
    work_dir = DATA_DIR / backtest_id
    work_dir.mkdir(parents=True, exist_ok=True)

    for subdir in ("tools", ".claude"):
        src = BACKTEST_TEMPLATE / subdir
        dst = work_dir / subdir
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    claude_md_src = BACKTEST_TEMPLATE / "CLAUDE.md"
    if claude_md_src.exists():
        shutil.copy2(claude_md_src, work_dir / "CLAUDE.md")

    bt_config = {
        "backtest_id": backtest_id,
        "agent_id": agent_id,
        "minio_endpoint": MINIO_ENDPOINT,
        "minio_access_key": MINIO_ACCESS_KEY,
        "minio_secret_key": MINIO_SECRET_KEY,
        "database_url": DATABASE_URL.replace("+asyncpg", ""),
        "redis_url": REDIS_URL,
        **config,
    }
    (work_dir / "config.json").write_text(json.dumps(bt_config, indent=2, default=str))
    _write_claude_settings(work_dir)

    return work_dir


def _write_claude_settings(work_dir: Path) -> None:
    """Write .claude/settings.json with SDK permissions for backtesting."""
    claude_dir = work_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings: dict[str, Any] = {
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


async def _upload_bundle(backtest_id: str, agent_id: str, work_dir: Path) -> str | None:
    """After training, look for a bundle tarball and upload it to MinIO via ModelRegistryClient."""
    from shared.db.models.feature_store import ModelBundle

    bundle_path = work_dir / "models" / "bundle.tar.gz"
    if not bundle_path.exists():
        bundle_candidates = list((work_dir / "models").glob("*.tar.gz")) if (work_dir / "models").exists() else []
        if bundle_candidates:
            bundle_path = bundle_candidates[0]
        else:
            log.warning("No bundle tarball found in %s/models/ for backtest %s", work_dir, backtest_id)
            return None

    db = await _get_db()
    try:
        from shared.model_registry.client import ModelRegistryClient

        result = await db.execute(
            select(ModelBundle)
            .where(ModelBundle.agent_id == uuid.UUID(agent_id))
            .order_by(ModelBundle.version.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        next_version = (latest.version + 1) if latest else 1

        registry = ModelRegistryClient(
            db_session=db,
            minio_endpoint=MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
        )
        minio_path = registry.upload_bundle(agent_id, next_version, bundle_path)

        metrics = _read_metrics(work_dir)
        bundle_id = await registry.register_bundle(agent_id, next_version, minio_path, metrics)
        await db.commit()

        log.info("Bundle uploaded for backtest %s: %s (bundle_id=%s)", backtest_id, minio_path, bundle_id)
        return str(bundle_id)
    except Exception as exc:
        log.error("Bundle upload failed for backtest %s: %s", backtest_id, exc)
        await db.rollback()
        return None
    finally:
        await db.close()


def _read_metrics(work_dir: Path) -> dict[str, Any]:
    """Read evaluation metrics from the backtest output."""
    metrics_path = work_dir / "models" / "meta.json"
    if metrics_path.exists():
        try:
            return json.loads(metrics_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    eval_path = work_dir / "evaluation_results.json"
    if eval_path.exists():
        try:
            return json.loads(eval_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    return {}


async def _run_backtest(backtest_id: str, agent_id: str, work_dir: Path) -> None:
    """Run the backtest Claude Code session. Updates _active_backtests in-place."""
    entry = _active_backtests.get(backtest_id)
    if not entry:
        return

    entry["status"] = "running"
    entry["started_at"] = datetime.now(timezone.utc).isoformat()

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query  # type: ignore[import-not-found]

        prompt = (
            "You are a backtesting agent. Read CLAUDE.md for full instructions.\n"
            "Your config is in config.json. Run the full 12-step pipeline:\n"
            "1. transform → 2. enrich → 3. compute_text_embeddings → 4. preprocess\n"
            "→ 5. train all models → 6. evaluate → 7. build_explainability\n"
            "→ 8. discover_patterns → 9. analyze_patterns_llm → 10. validate_model\n"
            "→ 11. report_to_phoenix → 12. create_live_agent\n\n"
            "Run each step sequentially. If a step fails, log the error and continue.\n"
            "When complete, write a summary to backtest_results.json."
        )

        options = ClaudeAgentOptions(
            work_dir=str(work_dir),
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "session_id"):
                entry["session_id"] = message.session_id

    except ImportError:
        log.warning("claude_agent_sdk not available — backtest %s running as stub", backtest_id)
        await asyncio.sleep(1)
    except asyncio.CancelledError:
        entry["status"] = "cancelled"
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()
        log.info("Backtest %s cancelled", backtest_id)
        raise
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)[:500]
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()
        log.error("Backtest %s failed: %s", backtest_id, exc)
        return

    bundle_id = await _upload_bundle(backtest_id, agent_id, work_dir)
    entry["bundle_id"] = bundle_id
    entry["status"] = "completed"
    entry["finished_at"] = datetime.now(timezone.utc).isoformat()
    entry["results"] = _read_results(work_dir)
    log.info("Backtest %s completed", backtest_id)


def _read_results(work_dir: Path) -> dict[str, Any]:
    """Read the backtest results JSON produced by the Claude session."""
    results_path = work_dir / "backtest_results.json"
    if results_path.exists():
        try:
            return json.loads(results_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Backtesting service started — data dir: %s", DATA_DIR)
    yield
    for bt_id, entry in list(_active_backtests.items()):
        task = entry.get("task")
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _active_backtests.clear()
    await _engine.dispose()
    log.info("Backtesting service shutdown complete")


app = FastAPI(title="Phoenix Backtesting Service", lifespan=lifespan)


@app.get("/health")
async def health():
    active_count = sum(1 for e in _active_backtests.values() if e.get("status") == "running")
    return {
        "status": "ok",
        "active_backtests": active_count,
        "total_tracked": len(_active_backtests),
    }


@app.post("/backtests", status_code=201)
async def create_backtest(body: BacktestRequest):
    backtest_id = str(uuid.uuid4())

    work_dir = _prepare_backtest_directory(backtest_id, body.agent_id, {**body.config, **body.date_range})

    entry: dict[str, Any] = {
        "backtest_id": backtest_id,
        "agent_id": body.agent_id,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "error": None,
        "bundle_id": None,
        "session_id": None,
        "results": {},
        "work_dir": str(work_dir),
    }
    _active_backtests[backtest_id] = entry

    task = asyncio.create_task(_run_backtest(backtest_id, body.agent_id, work_dir))
    entry["task"] = task

    return {"backtest_id": backtest_id, "status": "pending"}


@app.get("/backtests")
async def list_backtests():
    summaries = []
    for entry in _active_backtests.values():
        summaries.append(BacktestSummary(
            backtest_id=entry["backtest_id"],
            agent_id=entry["agent_id"],
            status=entry["status"],
            created_at=entry["created_at"],
            finished_at=entry.get("finished_at"),
            error=entry.get("error"),
        ))
    return {"backtests": [s.model_dump() for s in summaries], "count": len(summaries)}


@app.get("/backtests/{backtest_id}")
async def get_backtest(backtest_id: str):
    entry = _active_backtests.get(backtest_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Backtest {backtest_id} not found")
    return BacktestSummary(
        backtest_id=entry["backtest_id"],
        agent_id=entry["agent_id"],
        status=entry["status"],
        created_at=entry["created_at"],
        finished_at=entry.get("finished_at"),
        error=entry.get("error"),
    ).model_dump()


@app.get("/backtests/{backtest_id}/results")
async def get_backtest_results(backtest_id: str):
    entry = _active_backtests.get(backtest_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Backtest {backtest_id} not found")

    if entry["status"] not in ("completed", "error"):
        return {"backtest_id": backtest_id, "status": entry["status"], "results": None}

    return {
        "backtest_id": backtest_id,
        "status": entry["status"],
        "bundle_id": entry.get("bundle_id"),
        "results": entry.get("results", {}),
    }


@app.post("/backtests/{backtest_id}/approve")
async def approve_backtest(backtest_id: str, body: ApproveRequest):
    entry = _active_backtests.get(backtest_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Backtest {backtest_id} not found")

    if entry["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"Cannot approve backtest with status '{entry['status']}'")

    bundle_id = entry.get("bundle_id")
    if not bundle_id:
        raise HTTPException(status_code=409, detail="No model bundle associated with this backtest")

    from shared.db.models.feature_store import ModelBundle

    db = await _get_db()
    try:
        result = await db.execute(
            update(ModelBundle)
            .where(ModelBundle.id == uuid.UUID(bundle_id))
            .values(status="approved", deployed_at=datetime.now(timezone.utc))
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Bundle {bundle_id} not found in database")
        await db.commit()
    finally:
        await db.close()

    entry["status"] = "approved"
    log.info("Backtest %s approved by %s (bundle_id=%s)", backtest_id, body.approved_by, bundle_id)
    return {"backtest_id": backtest_id, "bundle_id": bundle_id, "status": "approved"}


@app.delete("/backtests/{backtest_id}")
async def cancel_backtest(backtest_id: str):
    entry = _active_backtests.get(backtest_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Backtest {backtest_id} not found")

    task = entry.get("task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    entry["status"] = "cancelled"
    entry["finished_at"] = datetime.now(timezone.utc).isoformat()

    return {"backtest_id": backtest_id, "status": "cancelled"}
