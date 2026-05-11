"""Backtest Pipeline Orchestrator (Tier 1).

Replaces the full Claude SDK session for backtesting with a Python asyncio
runner. Each pipeline step is run via asyncio.create_subprocess_exec.

Only step 8 (LLM pattern discovery) uses ModelRouter (Tier 2, ~$0.02).
All other steps are pure Python ($0).

Features:
  - Modular plug-and-play algorithm registry
  - Checkpoint files for crash recovery
  - Progress callbacks to the dashboard
  - Idempotent: re-running after crash resumes from last checkpoint
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_python_executable() -> str:
    """Return a subprocess-safe Python path.

    On macOS, sys.executable may point to the Framework GUI binary
    (Python.app/Contents/MacOS/Python) which can fail to initialise
    sys.stdin/stdout/stderr when spawned without a TTY.  The non-GUI
    binary lives in the Framework's bin/ directory and is always safe.
    """
    exe = sys.executable
    if "Python.app/Contents/MacOS/Python" in exe:
        candidate = exe.replace(
            "Resources/Python.app/Contents/MacOS/Python",
            "bin/python3.13",
        )
        if Path(candidate).exists():
            return candidate
    return exe

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKTESTING_TOOLS = REPO_ROOT / "agents" / "backtesting" / "tools"

STEP_TIMEOUT = 600  # 10 min default per step
LLM_STEP_TIMEOUT = 120

# Per-script timeout overrides for steps known to be slow on real-world data.
# enrich.py has to fetch yfinance OHLC bars for every unique ticker (sometimes
# 100s of them) and then compute ~200 features per trade across thousands of
# trades; 10 min is not enough on first run with a cold price_cache.
PER_SCRIPT_TIMEOUT = {
    "enrich.py": 1800,                # 30 min
    "compute_text_embeddings.py": 1200,
    "preprocess.py": 900,
    "llm_pattern_discovery.py": 600,
    "analyze_patterns_llm.py": 600,
}

# Modular algorithm registry: add/remove models by editing this dict.
# Each entry maps to a training script in agents/backtesting/tools/.
ALGORITHM_REGISTRY: dict[str, dict[str, Any]] = {
    "xgboost": {"script": "train_xgboost.py", "enabled": True, "order": 1},
    "lightgbm": {"script": "train_lightgbm.py", "enabled": True, "order": 2},
    "catboost": {"script": "train_catboost.py", "enabled": True, "order": 3},
    "random_forest": {"script": "train_rf.py", "enabled": True, "order": 4},
    "lstm": {"script": "train_lstm.py", "enabled": True, "order": 5},
    "transformer": {"script": "train_transformer.py", "enabled": True, "order": 6},
    "tft": {"script": "train_tft.py", "enabled": True, "order": 7},
    "tcn": {"script": "train_tcn.py", "enabled": True, "order": 8},
    "hybrid": {"script": "train_hybrid.py", "enabled": True, "order": 9},
    "meta_learner": {"script": "train_meta_learner.py", "enabled": True, "order": 10},
}

# FEATURE_PIPELINE and POST_TRAINING_PIPELINE were removed — _build_pipeline()
# now carries per-step CLI args inline.
# NOTE: compute_trading_metrics.py is a shared library (no __main__), not a
# standalone pipeline step — it is intentionally absent from the pipeline.


class BacktestOrchestrator:
    """Python-native backtesting pipeline runner."""

    def __init__(
        self,
        agent_id: uuid.UUID,
        session_id: uuid.UUID,
        work_dir: Path,
        config: dict | None = None,
        enabled_algorithms: list[str] | None = None,
    ):
        self.agent_id = agent_id
        self.session_id = session_id
        self.work_dir = work_dir
        self.config = config or {}
        self.enabled_algorithms = enabled_algorithms
        self._checkpoint_dir = work_dir / ".checkpoints"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        # R05: include a hash of enabled_algorithms in checkpoint names so that
        # changing the algorithm set invalidates stale checkpoints automatically.
        _algo_key = ",".join(sorted(enabled_algorithms)) if enabled_algorithms else "all"
        import hashlib
        self._config_hash = hashlib.md5(_algo_key.encode(), usedforsecurity=False).hexdigest()[:8]

    async def run(self) -> dict:
        """Execute the full backtest pipeline with checkpoint recovery."""
        logger.info(
            "BacktestOrchestrator starting: agent=%s session=%s work_dir=%s",
            self.agent_id, self.session_id, self.work_dir,
        )

        # Pre-seed: export channel_messages from DB so transform.py has data
        await self._export_db_messages()

        start_time = datetime.now(timezone.utc)
        all_steps = self._build_pipeline()
        total_steps = len(all_steps)
        results: list[dict] = []
        failed_step = None

        await self._update_status("running")

        for i, (script, description, step_type, step_args) in enumerate(all_steps):
            step_num = i + 1
            logger.info("Step %d/%d: %s (%s)", step_num, total_steps, description, script)

            # Check checkpoint
            if self._is_step_complete(step_num, script):
                logger.info("Step %d already complete (checkpoint), skipping", step_num)
                results.append({
                    "step": step_num, "script": script,
                    "description": description, "status": "skipped_checkpoint",
                })
                await self._report_progress(step_num, total_steps, f"[cached] {description}")
                continue

            await self._report_progress(step_num, total_steps, description)

            if step_type == "llm":
                result = await self._run_llm_step(script, description, step_args)
            else:
                result = await self._run_python_step(script, step_args)

            result["step"] = step_num
            result["description"] = description
            results.append(result)

            if result.get("success"):
                self._write_checkpoint(step_num, script)

                # After preprocess completes, check if there is enough data to train.
                # ML models need a minimum number of samples to learn anything
                # meaningful. With too few rows, skip training gracefully.
                MIN_TRAIN_ROWS = 10
                if "preprocess" in script:
                    meta_path = self.work_dir / "preprocessed" / "meta.json"
                    try:
                        meta = json.loads(meta_path.read_text())
                        n_train = meta.get("n_train", 0)
                        if n_train < MIN_TRAIN_ROWS:
                            logger.warning(
                                "Preprocess produced %d training rows for agent %s "
                                "(minimum %d required) — skipping training/post-training.",
                                n_train, self.agent_id, MIN_TRAIN_ROWS,
                            )
                            break  # failed_step is None → status = "completed"
                    except Exception as e:
                        logger.debug("Could not read preprocessed/meta.json: %s", e)
            else:
                # Retry once — log stdout/stderr as separate calls for structured log backends
                logger.warning("Step %d (%s) failed, retrying once.", step_num, script)
                logger.warning("Step %d stdout: %s", step_num, result.get("output", "")[:500])
                logger.warning("Step %d stderr: %s", step_num, result.get("error", "")[:500])
                retry = await self._run_python_step(script, step_args) if step_type != "llm" else await self._run_llm_step(script, description, step_args)
                if retry.get("success"):
                    self._write_checkpoint(step_num, script)
                    retry["step"] = step_num
                    retry["description"] = f"{description} (retry)"
                    results.append(retry)
                else:
                    failed_step = step_num
                    logger.error("Step %d (%s) failed after retry.", step_num, script)
                    logger.error("Step %d stdout: %s", step_num, retry.get("output", "")[:1000])
                    logger.error("Step %d stderr: %s", step_num, retry.get("error", "")[:1000])
                    break

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        status = "completed" if failed_step is None else "failed"

        await self._update_status(status)

        summary = {
            "status": status,
            "agent_id": str(self.agent_id),
            "session_id": str(self.session_id),
            "total_steps": total_steps,
            "completed_steps": sum(1 for r in results if r.get("success") or r.get("status") == "skipped_checkpoint"),
            "failed_step": failed_step,
            "elapsed_seconds": round(elapsed, 1),
            "results": results,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        # Write final result
        try:
            (self.work_dir / "backtest_result.json").write_text(
                json.dumps(summary, indent=2, default=str)
            )
        except Exception:
            pass

        logger.info(
            "BacktestOrchestrator %s: %d/%d steps in %.1fs",
            status, summary["completed_steps"], total_steps, elapsed,
        )
        return summary

    async def _export_db_messages(self) -> None:
        """Export channel_messages from the DB into a JSON file for transform.py.

        This bridges the connector-based ingestion with the ML pipeline:
        the ingestion service already stores messages in channel_messages;
        transform.py can read them via --messages-file instead of hitting
        the Discord API directly (which requires credentials in config.json).
        """
        messages_path = self.work_dir / "messages.json"
        if messages_path.exists():
            try:
                existing = json.loads(messages_path.read_text())
                if existing:
                    logger.info("messages.json already exists with %d messages, skipping export", len(existing))
                    return
            except Exception:
                pass

        try:
            from sqlalchemy import select as sa_select

            from shared.db.engine import get_session
            from shared.db.models.channel_message import ChannelMessage
            from shared.db.models.connector import ConnectorAgent

            messages = []
            async for db in get_session():
                # Find connector_ids linked to this agent
                links = (await db.execute(
                    sa_select(ConnectorAgent).where(ConnectorAgent.agent_id == self.agent_id)
                )).scalars().all()

                connector_ids = [link.connector_id for link in links]
                if not connector_ids:
                    logger.warning("No connectors linked to agent %s, skipping DB message export", self.agent_id)
                    return

                rows = (await db.execute(
                    sa_select(ChannelMessage)
                    .where(ChannelMessage.connector_id.in_(connector_ids))
                    .order_by(ChannelMessage.posted_at.asc())
                )).scalars().all()

                for row in rows:
                    messages.append({
                        "content": row.content,
                        "author": row.author,
                        "timestamp": row.posted_at.isoformat(),
                        "message_id": row.platform_message_id,
                    })

            # Always write the file (even empty) so _build_pipeline can pass
            # --messages-file unconditionally and transform.py never falls back
            # to the seed DB at port 5434.
            messages_path.write_text(json.dumps(messages, indent=2, default=str))
            if messages:
                logger.info("Exported %d DB messages to %s", len(messages), messages_path)
            else:
                logger.warning(
                    "No messages found in DB for agent %s connectors — wrote empty messages.json "
                    "(transform.py will produce an empty dataset; backtest will complete with no trades)",
                    self.agent_id,
                )
        except Exception as e:
            logger.warning("DB message export failed (non-fatal): %s", e)
            # Write empty file so _build_pipeline always passes --messages-file
            # and transform.py never tries to hit the wrong seed DB.
            try:
                messages_path.write_text("[]")
                logger.info("Wrote empty messages.json as fallback after export error")
            except Exception:
                pass

    def _build_pipeline(self) -> list[tuple[str, str, str, list[str]]]:
        """Build the ordered pipeline of (script, description, type, args) tuples."""
        steps: list[tuple[str, str, str, list[str]]] = []

        # ── Feature engineering pipeline ────────────────────────────────────
        transform_args = ["--config", "config.json", "--output", "transformed.parquet", "--force"]
        if (self.work_dir / "messages.json").exists():
            transform_args += ["--messages-file", "messages.json"]
        steps.append((
            "transform.py", "Feature: transform", "python",
            transform_args,
        ))
        steps.append((
            "enrich.py", "Feature: enrich", "python",
            ["--input", "transformed.parquet", "--output", "enriched.parquet"],
        ))
        steps.append((
            "compute_text_embeddings.py", "Feature: compute_text_embeddings", "python",
            # Output to work_dir root ('.') so preprocess.py finds text_embeddings.npy
            # at input_path.parent/text_embeddings.npy as it expects.
            ["--input", "enriched.parquet", "--output", "."],
        ))
        steps.append((
            "compute_labels.py", "Feature: compute_labels", "python",
            ["--input", "enriched.parquet", "--output", "labeled.parquet"],
        ))
        steps.append((
            "preprocess.py", "Feature: preprocess", "python",
            ["--input", "labeled.parquet", "--output", "preprocessed"],
        ))

        # ── Training algorithms (sorted by order, filtered by enabled) ───────
        algos = sorted(
            ALGORITHM_REGISTRY.items(),
            key=lambda x: x[1].get("order", 99),
        )
        for name, info in algos:
            if not info.get("enabled", True):
                continue
            if self.enabled_algorithms and name not in self.enabled_algorithms:
                continue
            model_out = f"models/{name}"
            if name == "meta_learner":
                steps.append((
                    info["script"], f"Train: {name}", "python",
                    ["--data", "preprocessed", "--models-dir", "models", "--output", model_out],
                ))
            else:
                steps.append((
                    info["script"], f"Train: {name}", "python",
                    ["--data", "preprocessed", "--output", model_out],
                ))

        # ── LLM pattern discovery — run as python subprocesses (scripts handle
        #    their own LLM calls internally; no ModelRouter fallback needed here)
        steps.append((
            "llm_pattern_discovery.py", "LLM Pattern Discovery", "python",
            ["--data", ".", "--output", "llm_discovered_patterns.json"],
        ))
        steps.append((
            "analyze_patterns_llm.py", "LLM Pattern Analysis", "python",
            ["--data", ".", "--output", "llm_patterns.json", "--config", "config.json"],
        ))

        # ── Post-training pipeline ───────────────────────────────────────────
        steps.append((
            "evaluate_models.py", "Post: evaluate_models", "python",
            ["--models-dir", "models", "--output", "models/best_model.json"],
        ))
        steps.append((
            "model_selector.py", "Post: model_selector", "python",
            ["--data", ".", "--output", "model_selection.json"],
        ))
        steps.append((
            "build_explainability.py", "Post: build_explainability", "python",
            ["--model", "models", "--data", "preprocessed", "--output", "models/explainability.json"],
        ))
        steps.append((
            "discover_patterns.py", "Post: discover_patterns", "python",
            ["--data", ".", "--output", "patterns.json"],
        ))
        steps.append((
            "compute_kelly_sizing.py", "Post: compute_kelly_sizing", "python",
            ["--data", "enriched.parquet", "--output", "kelly_sizing.json"],
        ))
        steps.append((
            "compute_price_buffer.py", "Post: compute_price_buffer", "python",
            ["--data", "enriched.parquet", "--output", "price_buffers.json"],
        ))
        steps.append((
            "compute_regime_calibration.py", "Post: compute_regime_calibration", "python",
            ["--enriched", "enriched.parquet", "--predictions", "model_selection.json",
             "--output", "regime_calibration.json"],
        ))
        steps.append((
            "validate_model.py", "Post: validate_model", "python",
            ["--data", "preprocessed", "--models", "models", "--output", "validation_report.json"],
        ))
        steps.append((
            "create_live_agent.py", "Post: create_live_agent", "python",
            ["--config", "config.json", "--models", "models", "--output", "."],
        ))

        # ── Report to Phoenix ────────────────────────────────────────────────
        steps.append((
            "report_to_phoenix.py", "Report to Phoenix", "python",
            ["--event", "complete", "--step", "report_to_phoenix", "--progress", "100"],
        ))

        return steps

    async def _run_python_step(self, script: str, args: list[str] | None = None) -> dict:
        """Run a Python script as a subprocess with optional CLI arguments."""
        script_path = BACKTESTING_TOOLS / script
        if not script_path.exists():
            return {"success": False, "script": script, "error": f"Script not found: {script_path}"}

        timeout = PER_SCRIPT_TIMEOUT.get(script, STEP_TIMEOUT)
        proc = None
        try:
            cmd = [_safe_python_executable(), str(script_path)] + (args or [])
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=str(self.work_dir),
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[4])},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )

            return {
                "success": proc.returncode == 0,
                "script": script,
                "output": (stdout.decode(errors="replace") if stdout else "")[:3000],
                "error": (stderr.decode(errors="replace") if stderr else "")[:1000] if proc.returncode != 0 else "",
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            # asyncio.wait_for only abandons the future — the OS subprocess is
            # still running and will hold its file descriptors, network sockets,
            # and the price_cache directory open indefinitely. Kill it loud.
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    # Reap so we don't leave a zombie.
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except (ProcessLookupError, asyncio.TimeoutError):
                    pass
                except Exception as kill_err:
                    logger.warning("Failed to kill timed-out subprocess for %s: %s", script, kill_err)
            return {
                "success": False,
                "script": script,
                "error": f"Timeout after {timeout}s (subprocess killed)",
            }
        except Exception as e:
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            return {"success": False, "script": script, "error": str(e)[:500]}

    async def _run_llm_step(self, script: str, description: str, args: list[str] | None = None) -> dict:
        """ModelRouter fallback for any step registered as type 'llm'.

        Attempts to run the script as a normal Python subprocess first (passing
        args so required CLI params are satisfied), then falls back to the
        ModelRouter if the script itself fails.
        """
        # First try running the script itself (it may handle its own LLM calls)
        result = await self._run_python_step(script, args)
        if result.get("success"):
            return result

        # Fallback: Use ModelRouter directly for pattern discovery
        try:
            from shared.utils.model_router import get_router

            router = get_router(agent_id=self.agent_id)

            # Read any available data files for context
            context_files = ["analysis.json", "evaluation_report.json", "trading_metrics.json"]
            context_data = ""
            for cf in context_files:
                p = self.work_dir / cf
                if p.exists():
                    try:
                        content = p.read_text()[:2000]
                        context_data += f"\n--- {cf} ---\n{content}\n"
                    except Exception:
                        pass

            if not context_data:
                return {"success": False, "script": script, "error": "No context data available for LLM step"}

            resp = await router.complete(
                task_type="pattern_discovery",
                prompt=f"""Analyze the following backtest results and identify trading patterns:

{context_data}

Identify:
1. Strongest predictive features
2. Market conditions where the model performs best/worst
3. Suggested pattern-based trading rules
4. Risk factors to monitor

Return a JSON object with your findings.""",
                system="You are a quantitative analyst reviewing backtesting results.",
                temperature=0.3,
                max_tokens=2048,
                agent_id=self.agent_id,
            )

            # Save LLM output
            output_path = self.work_dir / "llm_patterns.json"
            try:
                patterns = json.loads(resp.text)
                output_path.write_text(json.dumps(patterns, indent=2))
            except json.JSONDecodeError:
                output_path.write_text(resp.text)

            return {
                "success": True,
                "script": script,
                "output": resp.text[:2000],
                "model": resp.model,
                "cost": resp.cost_usd,
            }
        except Exception as e:
            return {"success": False, "script": script, "error": f"LLM fallback failed: {e}"}

    def _checkpoint_path(self, step: int, script: str) -> Path:
        # R05: embed config hash so that changing enabled_algorithms invalidates
        # stale checkpoints from a previous run with a different algorithm set.
        return self._checkpoint_dir / f"step_{step:03d}_{script.replace('.py', '')}_{self._config_hash}.json"

    def _is_step_complete(self, step: int, script: str) -> bool:
        """Check if a step has a valid checkpoint."""
        cp = self._checkpoint_path(step, script)
        if not cp.exists():
            return False
        try:
            data = json.loads(cp.read_text())
            return data.get("success", False)
        except Exception:
            return False

    def _write_checkpoint(self, step: int, script: str) -> None:
        cp = self._checkpoint_path(step, script)
        try:
            cp.write_text(json.dumps({
                "step": step,
                "script": script,
                "success": True,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2))
        except Exception:
            pass

    async def _update_status(self, status: str) -> None:
        """Update session status in DB."""
        try:
            from sqlalchemy import update

            from shared.db.engine import get_session
            from shared.db.models.agent_session import AgentSession

            async for db in get_session():
                values: dict[str, Any] = {
                    "status": status,
                    "last_heartbeat": datetime.now(timezone.utc),
                }
                if status in ("completed", "failed"):
                    values["completed_at"] = datetime.now(timezone.utc)
                await db.execute(
                    update(AgentSession)
                    .where(AgentSession.id == self.session_id)
                    .values(**values)
                )
                await db.commit()
        except Exception as e:
            logger.debug("Status update failed (non-fatal): %s", e)

    async def _report_progress(self, step: int, total: int, description: str) -> None:
        """Report progress to the dashboard via API."""
        try:
            import httpx
            api_url = self.config.get("phoenix_api_url", "")
            api_key = self.config.get("phoenix_api_key", "")
            if api_url:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{api_url}/api/v2/agents/{self.agent_id}/backtest-progress",
                        json={
                            "step": description[:100] or f"step_{step}",
                            "message": f"Step {step}/{total}: {description}",
                            "progress_pct": round(step / total * 100),
                        },
                        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                        timeout=5,
                    )
        except Exception:
            pass
