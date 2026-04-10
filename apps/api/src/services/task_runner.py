"""Task Runner — executes backtesting pipeline as local Python subprocesses.

Each step in agents/backtesting/tools/ is a standalone CLI script with its own
argparse flags.  This runner maps step names to the correct CLI arguments and
orchestrates sequential execution, writing progress to PostgreSQL so the
dashboard can poll it.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from shared.db.engine import get_session as _get_session
from shared.db.models.agent import Agent, AgentBacktest
from shared.db.models.system_log import SystemLog

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKTESTING_TOOLS = REPO_ROOT / "agents" / "backtesting" / "tools"

_running_tasks: dict[str, asyncio.Task] = {}


def _build_step_args(cfg: str, w: str) -> dict[str, list[str]]:
    """Return CLI arg lists keyed by step name.

    cfg = path to config JSON file
    w   = work directory for this backtest run
    """
    pre = f"{w}/preprocessed"
    models = f"{w}/models"
    return {
        "transform":          ["--config", cfg, "--output", f"{w}/transformed.parquet"],
        "enrich":             ["--input", f"{w}/transformed.parquet", "--output", f"{w}/enriched.parquet"],
        "text_embeddings":    ["--input", f"{w}/enriched.parquet", "--output", w],
        "preprocess":         ["--input", f"{w}/enriched.parquet", "--output", w],
        "train_xgboost":      ["--data", w, "--output", models],
        "train_lightgbm":     ["--data", w, "--output", models],
        "train_catboost":     ["--data", w, "--output", models],
        "train_rf":           ["--data", w, "--output", models],
        "train_lstm":         ["--data", w, "--output", models],
        "train_transformer":  ["--data", w, "--output", models],
        "train_tft":          ["--data", w, "--output", models],
        "train_tcn":          ["--data", w, "--output", models],
        "train_hybrid":       ["--data", w, "--output", models],
        "train_meta_learner": ["--models-dir", models, "--data", w, "--output", models],
        "evaluate":           ["--models-dir", models, "--output", f"{models}/best_model.json"],
        "explainability":     ["--model", models, "--data", w, "--output", f"{w}/explainability.json"],
        "patterns":           ["--data", w, "--output", f"{w}/patterns.json"],
        "llm_patterns":       ["--data", w, "--output", f"{w}/llm_patterns.json", "--config", cfg],
        "validate_model":     ["--data", w, "--models", models, "--output", f"{w}/validation_report.json"],
        "create_live_agent":  ["--config", cfg, "--models", models, "--output", f"{w}/live_agent"],
    }


async def run_backtest(
    agent_id: uuid.UUID,
    backtest_id: uuid.UUID,
    config: dict,
) -> None:
    """Kick off the full backtesting pipeline in the background.

    Each step is a Python script in agents/backtesting/tools/. Progress is
    written to the DB so the dashboard can poll it. On completion, the agent
    status transitions to BACKTEST_COMPLETE.
    """
    task_key = str(agent_id)
    if task_key in _running_tasks and not _running_tasks[task_key].done():
        logger.warning("Backtest already running for agent %s", agent_id)
        return

    task = asyncio.create_task(_run_pipeline(agent_id, backtest_id, config))
    _running_tasks[task_key] = task


async def _run_pipeline(
    agent_id: uuid.UUID,
    backtest_id: uuid.UUID,
    config: dict,
) -> None:
    """Execute each pipeline step, updating DB progress along the way."""
    work_dir = REPO_ROOT / "data" / f"backtest_{agent_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "models").mkdir(exist_ok=True)

    config_path = work_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2, default=str))

    step_args = _build_step_args(str(config_path), str(work_dir))

    env_extra = {
        "PHOENIX_API_URL": config.get("phoenix_api_url", ""),
        "PHOENIX_API_KEY": config.get("phoenix_api_key", ""),
        "PHOENIX_AGENT_ID": str(agent_id),
        "PHOENIX_BACKTEST_ID": str(backtest_id),
    }

    steps = [
        ("transform",         "transform.py",              10),
        ("enrich",            "enrich.py",                 22),
        ("text_embeddings",   "compute_text_embeddings.py", 25),
        ("preprocess",        "preprocess.py",             28),
    ]

    parallel_training_steps = [
        ("train_xgboost",     "train_xgboost.py"),
        ("train_lightgbm",    "train_lightgbm.py"),
        ("train_catboost",    "train_catboost.py"),
        ("train_rf",          "train_rf.py"),
        ("train_lstm",        "train_lstm.py"),
        ("train_transformer", "train_transformer.py"),
        ("train_tft",         "train_tft.py"),
        ("train_tcn",         "train_tcn.py"),
    ]

    post_training_steps = [
        ("train_hybrid",       "train_hybrid.py",           60),
        ("train_meta_learner", "train_meta_learner.py",     63),
        ("evaluate",           "evaluate_models.py",        68),
        ("explainability",     "build_explainability.py",   75),
        ("patterns",           "discover_patterns.py",      80),
        ("llm_patterns",       "analyze_patterns_llm.py",   85),
        ("validate_model",     "validate_model.py",         88),
        ("create_live_agent",  "create_live_agent.py",      95),
    ]

    async for session in _get_session():
        try:
            # Phase 1: sequential preprocessing
            for step_name, script, pct in steps:
                script_path = BACKTESTING_TOOLS / script
                if not script_path.exists():
                    logger.warning("Step %s script not found: %s", step_name, script_path)
                    continue

                args = step_args.get(step_name, [])
                await _update_progress(session, agent_id, backtest_id, step_name, pct, f"Running {step_name}...")

                exit_code, stdout, stderr = await _run_script(script_path, args, env_extra)

                if exit_code != 0:
                    error_msg = (stderr or stdout or "Unknown error")[:500]
                    logger.error("Step %s failed (exit %d): %s", step_name, exit_code, error_msg)
                    await _mark_failed(session, agent_id, backtest_id, step_name, error_msg)
                    return

                logger.info("Step %s completed for agent %s", step_name, agent_id)

            # Phase 2: parallel base model training
            await _update_progress(session, agent_id, backtest_id, "training", 30,
                                   f"Training {len(parallel_training_steps)} models in parallel...")

            async def _train_one(step_name: str, script: str):
                script_path = BACKTESTING_TOOLS / script
                if not script_path.exists():
                    logger.warning("Step %s script not found: %s", step_name, script_path)
                    return step_name, 0, "", ""
                args = step_args.get(step_name, [])
                ec, so, se = await _run_script(script_path, args, env_extra)
                return step_name, ec, so, se

            results = await asyncio.gather(
                *[_train_one(sn, sc) for sn, sc in parallel_training_steps],
                return_exceptions=True,
            )

            for res in results:
                if isinstance(res, Exception):
                    logger.error("Training task raised exception: %s", res)
                    await _mark_failed(session, agent_id, backtest_id, "training", str(res)[:500])
                    return
                step_name, exit_code, stdout, stderr = res
                if exit_code != 0:
                    error_msg = (stderr or stdout or "Unknown error")[:500]
                    logger.error("Step %s failed (exit %d): %s", step_name, exit_code, error_msg)
                    await _mark_failed(session, agent_id, backtest_id, step_name, error_msg)
                    return
                logger.info("Step %s completed for agent %s", step_name, agent_id)

            await _update_progress(session, agent_id, backtest_id, "training_done", 56,
                                   "All base models trained")

            # Phase 3: sequential post-training steps
            for step_name, script, pct in post_training_steps:
                script_path = BACKTESTING_TOOLS / script
                if not script_path.exists():
                    logger.warning("Step %s script not found: %s", step_name, script_path)
                    continue

                args = step_args.get(step_name, [])
                await _update_progress(session, agent_id, backtest_id, step_name, pct, f"Running {step_name}...")

                exit_code, stdout, stderr = await _run_script(script_path, args, env_extra)

                if exit_code != 0:
                    error_msg = (stderr or stdout or "Unknown error")[:500]
                    logger.error("Step %s failed (exit %d): %s", step_name, exit_code, error_msg)
                    await _mark_failed(session, agent_id, backtest_id, step_name, error_msg)
                    return

                logger.info("Step %s completed for agent %s", step_name, agent_id)

            await _mark_completed(session, agent_id, backtest_id)

        except Exception as exc:
            logger.exception("Pipeline crashed for agent %s", agent_id)
            await _mark_failed(session, agent_id, backtest_id, "pipeline_error", str(exc)[:500])
        finally:
            _running_tasks.pop(str(agent_id), None)


async def _run_script(
    script_path: Path,
    cli_args: list[str],
    env_extra: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a Python script as an asyncio subprocess with proper CLI args."""
    python = os.getenv("PYTHON_BIN", "python3")
    env = {**os.environ, **(env_extra or {})}
    proc = await asyncio.create_subprocess_exec(
        python, str(script_path), *cli_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(BACKTESTING_TOOLS.parent),
        env=env,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout_bytes.decode(errors="replace")[-2000:],
        stderr_bytes.decode(errors="replace")[-2000:],
    )


async def _update_progress(
    session, agent_id: uuid.UUID, backtest_id: uuid.UUID,
    step: str, pct: int, message: str,
) -> None:
    bt_result = await session.execute(select(AgentBacktest).where(AgentBacktest.id == backtest_id))
    bt = bt_result.scalar_one_or_none()
    if bt:
        bt.current_step = step
        bt.progress_pct = pct

    log = SystemLog(
        id=uuid.uuid4(), source="backtest", level="INFO", service="task-runner",
        agent_id=str(agent_id), backtest_id=str(backtest_id),
        message=message, step=step, progress_pct=pct,
    )
    session.add(log)
    await session.commit()


def _resolve_version_dir(work_dir: Path, output_dir: Path) -> Path:
    """Find the latest versioned output directory (e.g. output/v2/)."""
    latest_file = work_dir / "latest.json"
    if latest_file.exists():
        try:
            data = json.loads(latest_file.read_text())
            vdir = data.get("output_dir", "")
            if vdir and Path(vdir).exists():
                return Path(vdir)
            v_num = data.get("version")
            if v_num and (output_dir / f"v{v_num}").exists():
                return output_dir / f"v{v_num}"
        except Exception:
            pass
    for vd in sorted(output_dir.glob("v*"), reverse=True):
        if vd.is_dir():
            return vd
    return output_dir


def _backfill_metrics_from_files(version_dir: Path, work_dir: Path, output_dir: Path, m: dict) -> dict:
    """Read model results from disk and compute summary metrics."""
    m = dict(m)

    # Collect model results
    all_results = []
    for mdir in [version_dir / "models", work_dir / "models", output_dir / "models"]:
        if mdir.exists():
            for rf in sorted(mdir.glob("*_results.json")):
                try:
                    all_results.append(json.loads(rf.read_text()))
                except Exception:
                    pass
            if all_results:
                break

    if all_results:
        m["all_model_results"] = all_results
        best = max(all_results, key=lambda r: r.get("auc_roc", r.get("accuracy", 0)) or 0)
        m["best_model"] = best.get("model_name", "unknown")
        m["accuracy"] = best.get("accuracy", 0)

    # Read enriched parquet for trade stats
    for enriched_path in [version_dir / "enriched.parquet", work_dir / "enriched.parquet", output_dir / "enriched.parquet"]:
        if enriched_path.exists():
            try:
                import pandas as pd
                edf = pd.read_parquet(enriched_path)
                m["total_trades"] = len(edf)
                if "win" in edf.columns:
                    m["win_rate"] = round(float(edf["win"].mean()), 4)
                elif "pnl_pct" in edf.columns:
                    m["win_rate"] = round(float((edf["pnl_pct"] > 0).mean()), 4)
                if "pnl_pct" in edf.columns:
                    m["total_return"] = round(float(edf["pnl_pct"].sum()), 2)
            except Exception:
                pass
            break

    # Read meta.json for feature info
    for meta_path in [version_dir / "meta.json", work_dir / "meta.json", output_dir / "meta.json"]:
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                m["feature_names"] = meta.get("feature_columns", [])
                m.setdefault("preprocessing_summary", {
                    "total_rows": meta.get("total_rows", 0),
                    "train_rows": meta.get("train_rows", 0),
                    "val_rows": meta.get("val_rows", 0),
                    "test_rows": meta.get("test_rows", 0),
                    "feature_count": meta.get("num_features", len(meta.get("feature_columns", []))),
                })
            except Exception:
                pass
            break

    return m


async def _mark_completed(session, agent_id: uuid.UUID, backtest_id: uuid.UUID) -> None:
    now = datetime.now(timezone.utc)

    bt_result = await session.execute(select(AgentBacktest).where(AgentBacktest.id == backtest_id))
    bt = bt_result.scalar_one_or_none()
    if bt:
        bt.status = "COMPLETED"
        bt.progress_pct = 100
        bt.current_step = "completed"
        bt.completed_at = now

        m = bt.metrics or {}

        # Backfill metrics from output files when DB metrics are empty
        if not m.get("total_trades") and not m.get("win_rate"):
            work_dir = REPO_ROOT / "data" / f"backtest_{agent_id}"
            output_dir = work_dir / "output"
            version_dir = _resolve_version_dir(work_dir, output_dir)
            m = _backfill_metrics_from_files(version_dir, work_dir, output_dir, m)
            bt.metrics = m

        bt.total_trades = m.get("total_trades") or m.get("trades") or 0
        bt.win_rate = m.get("win_rate")
        bt.sharpe_ratio = m.get("sharpe_ratio")
        bt.max_drawdown = m.get("max_drawdown")
        bt.total_return = m.get("total_return")

    agent_result = await session.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if agent:
        agent.status = "BACKTEST_COMPLETE"
        agent.updated_at = now
        if bt:
            m = bt.metrics or {}
            agent.model_type = m.get("best_model") or m.get("model")
            agent.model_accuracy = m.get("accuracy")
            agent.total_trades = bt.total_trades or 0
            agent.win_rate = bt.win_rate or 0.0

    log = SystemLog(
        id=uuid.uuid4(), source="backtest", level="INFO", service="task-runner",
        agent_id=str(agent_id), backtest_id=str(backtest_id),
        message="Backtesting pipeline completed successfully", step="completed", progress_pct=100,
    )
    session.add(log)
    await session.commit()
    logger.info("Backtest completed for agent %s", agent_id)


async def _mark_failed(
    session, agent_id: uuid.UUID, backtest_id: uuid.UUID,
    step: str, error_msg: str,
) -> None:
    now = datetime.now(timezone.utc)

    bt_result = await session.execute(select(AgentBacktest).where(AgentBacktest.id == backtest_id))
    bt = bt_result.scalar_one_or_none()
    if bt:
        bt.status = "FAILED"
        bt.error_message = error_msg
        bt.completed_at = now

    agent_result = await session.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if agent:
        agent.status = "CREATED"
        agent.updated_at = now

    log = SystemLog(
        id=uuid.uuid4(), source="backtest", level="ERROR", service="task-runner",
        agent_id=str(agent_id), backtest_id=str(backtest_id),
        message=error_msg, step=step,
    )
    session.add(log)
    await session.commit()


def get_running_backtests() -> list[str]:
    """Return agent IDs with active backtest tasks."""
    return [k for k, t in _running_tasks.items() if not t.done()]


def cancel_backtest(agent_id: str) -> bool:
    """Cancel a running backtest task."""
    task = _running_tasks.get(agent_id)
    if task and not task.done():
        task.cancel()
        return True
    return False
