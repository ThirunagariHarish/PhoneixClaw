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
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKTESTING_TOOLS = REPO_ROOT / "agents" / "backtesting" / "tools"

STEP_TIMEOUT = 600  # 10 min per step
LLM_STEP_TIMEOUT = 120

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

# Feature pipeline: plug-and-play enrichment steps
FEATURE_PIPELINE: list[str] = [
    "transform.py",
    "enrich.py",
    "compute_text_embeddings.py",
    "compute_labels.py",
    "preprocess.py",
]

# Post-training pipeline
POST_TRAINING_PIPELINE: list[str] = [
    "evaluate_models.py",
    "model_selector.py",
    "build_explainability.py",
    "discover_patterns.py",
    "compute_trading_metrics.py",
    "compute_kelly_sizing.py",
    "compute_price_buffer.py",
    "compute_regime_calibration.py",
    "validate_model.py",
    "create_live_agent.py",
]


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

    async def run(self) -> dict:
        """Execute the full backtest pipeline with checkpoint recovery."""
        logger.info(
            "BacktestOrchestrator starting: agent=%s session=%s work_dir=%s",
            self.agent_id, self.session_id, self.work_dir,
        )

        start_time = datetime.now(timezone.utc)
        all_steps = self._build_pipeline()
        total_steps = len(all_steps)
        results: list[dict] = []
        failed_step = None

        await self._update_status("running")

        for i, (script, description, step_type) in enumerate(all_steps):
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
                result = await self._run_llm_step(script, description)
            else:
                result = await self._run_python_step(script)

            result["step"] = step_num
            result["description"] = description
            results.append(result)

            if result.get("success"):
                self._write_checkpoint(step_num, script)
            else:
                # Retry once
                logger.warning("Step %d failed, retrying once...", step_num)
                retry = await self._run_python_step(script) if step_type != "llm" else await self._run_llm_step(script, description)
                if retry.get("success"):
                    self._write_checkpoint(step_num, script)
                    retry["step"] = step_num
                    retry["description"] = f"{description} (retry)"
                    results.append(retry)
                else:
                    failed_step = step_num
                    logger.error("Step %d failed after retry: %s", step_num, retry.get("error", ""))
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

    def _build_pipeline(self) -> list[tuple[str, str, str]]:
        """Build the ordered pipeline of (script, description, type) tuples."""
        steps: list[tuple[str, str, str]] = []

        # Feature engineering pipeline
        for script in FEATURE_PIPELINE:
            steps.append((script, f"Feature: {script.replace('.py', '')}", "python"))

        # Training algorithms (sorted by order, filtered by enabled)
        algos = sorted(
            ALGORITHM_REGISTRY.items(),
            key=lambda x: x[1].get("order", 99),
        )
        for name, info in algos:
            if not info.get("enabled", True):
                continue
            if self.enabled_algorithms and name not in self.enabled_algorithms:
                continue
            steps.append((info["script"], f"Train: {name}", "python"))

        # LLM pattern discovery (the one Tier 2 step)
        steps.append(("llm_pattern_discovery.py", "LLM Pattern Discovery", "llm"))
        steps.append(("analyze_patterns_llm.py", "LLM Pattern Analysis", "llm"))

        # Post-training pipeline
        for script in POST_TRAINING_PIPELINE:
            steps.append((script, f"Post: {script.replace('.py', '')}", "python"))

        # Report to Phoenix
        steps.append(("report_to_phoenix.py", "Report to Phoenix", "python"))

        return steps

    async def _run_python_step(self, script: str) -> dict:
        """Run a Python script as a subprocess."""
        script_path = BACKTESTING_TOOLS / script
        if not script_path.exists():
            return {"success": False, "script": script, "error": f"Script not found: {script_path}"}

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.work_dir),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=STEP_TIMEOUT,
            )

            return {
                "success": proc.returncode == 0,
                "script": script,
                "output": (stdout.decode(errors="replace") if stdout else "")[:3000],
                "error": (stderr.decode(errors="replace") if stderr else "")[:1000] if proc.returncode != 0 else "",
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            return {"success": False, "script": script, "error": f"Timeout after {STEP_TIMEOUT}s"}
        except Exception as e:
            return {"success": False, "script": script, "error": str(e)[:500]}

    async def _run_llm_step(self, script: str, description: str) -> dict:
        """Run an LLM-dependent step (Tier 2 via ModelRouter)."""
        # First try running the script itself (it may handle its own LLM calls)
        result = await self._run_python_step(script)
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
        return self._checkpoint_dir / f"step_{step:03d}_{script.replace('.py', '')}.json"

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
                            "session_id": str(self.session_id),
                            "current_step": step,
                            "total_steps": total,
                            "description": description,
                            "pct": round(step / total * 100),
                        },
                        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                        timeout=5,
                    )
        except Exception:
            pass
