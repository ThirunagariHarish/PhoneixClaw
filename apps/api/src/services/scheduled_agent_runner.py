"""Scheduled Agent Runner (Tier 1 + Tier 2).

Replaces full Claude SDK sessions for scheduled agents (morning briefing,
supervisor, EOD analysis, daily summary, trade feedback) with:
  - Tier 1: Python subprocess execution of each pipeline script ($0)
  - Tier 2: Single cheap LLM call for narrative compilation (~$0.001)

Each agent type has a defined pipeline of scripts + an optional LLM step.
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
TEMPLATES_DIR = REPO_ROOT / "agents" / "templates"

STEP_TIMEOUT = 120
PIPELINE_TIMEOUT = 600
PREFLIGHT_TIMEOUT = 10


AgentPipeline = list[tuple[str, str]]  # [(script_or_cmd, description), ...]

AGENT_PIPELINES: dict[str, dict[str, Any]] = {
    "morning_briefing": {
        "template": "morning-briefing-agent",
        "steps": [
            ("collect_overnight_events.py", "Collect overnight market events"),
            ("compile_briefing.py", "Compile raw data into briefing sections"),
            ("compile_pm_section.py", "Add pre-market analysis section"),
        ],
        "llm_step": ("briefing_compile", "Compile a concise morning briefing from the collected data"),
        "report_script": "report_briefing.py",
        "report_to_phoenix": "report_to_phoenix.py",
    },
    "supervisor": {
        "template": "supervisor-agent",
        "steps": [
            ("collect_daily_data.py --output daily_data.json", "Collect daily agent data"),
            ("analyze_performance.py --input daily_data.json --output analysis.json", "Analyze performance"),
            ("propose_improvements.py --input analysis.json --output improvements.json", "Propose improvements"),
        ],
        "llm_step": ("supervisor_analysis", "Analyze trading performance and propose improvements"),
        "report_script": "notify_user.py --event supervisor_report --data improvements.json",
    },
    "eod_analysis": {
        "template": "eod-analysis-agent",
        "steps": [
            ("collect_day_trades.py", "Collect today's trades"),
            ("enrich_outcomes.py", "Enrich with outcomes"),
            ("compute_missed.py", "Compute missed opportunities"),
        ],
        "llm_step": ("narrative", "Summarize EOD analysis results"),
        "report_script": "compile_eod_brief.py",
        "report_to_phoenix": "report_to_phoenix.py",
    },
    "daily_summary": {
        "template": "daily-summary-agent",
        "steps": [
            ("collect_today_pnl.py", "Collect P&L data"),
            ("compile_summary.py", "Compile summary data"),
        ],
        "llm_step": ("narrative", "Compile daily summary narrative"),
        "report_script": "report_summary.py",
        "report_to_phoenix": "report_to_phoenix.py",
    },
    "trade_feedback": {
        "template": "trade-feedback-agent",
        "steps": [
            ("compute_bias.py", "Compute trading bias corrections"),
            ("apply_bias.py", "Apply bias corrections to models"),
        ],
        "report_to_phoenix": "report_to_phoenix.py",
    },
}


class ScheduledAgentRunner:
    """Generic pipeline runner for scheduled agents."""

    def __init__(
        self,
        agent_type: str,
        agent_id: uuid.UUID,
        session_id: uuid.UUID,
        work_dir: Path,
        config: dict | None = None,
    ):
        self.agent_type = agent_type
        self.agent_id = agent_id
        self.session_id = session_id
        self.work_dir = work_dir
        self.config = config or {}
        self._pipeline = AGENT_PIPELINES.get(agent_type)
        if not self._pipeline:
            raise ValueError(f"Unknown agent type: {agent_type}")
        self._template_dir = TEMPLATES_DIR / self._pipeline["template"]
        self._step_results: list[dict] = []

    async def run(self) -> dict:
        """Execute the full pipeline."""
        logger.info(
            "ScheduledAgentRunner starting: type=%s agent=%s session=%s",
            self.agent_type, self.agent_id, self.session_id,
        )

        start_time = datetime.now(timezone.utc)
        steps = self._pipeline.get("steps", [])
        status = "completed"
        error_msg = ""

        await self._update_session_status("running")

        # Preflight: verify tools directory exists
        tools_dir = self._template_dir / "tools"
        if not tools_dir.exists():
            logger.error("Tools directory not found: %s", tools_dir)
            await self._update_session_status("failed")
            return {"status": "failed", "error": f"Tools directory missing: {tools_dir}"}

        # Run pipeline steps
        for i, (script_cmd, description) in enumerate(steps):
            step_num = i + 1
            logger.info("Step %d/%d: %s", step_num, len(steps), description)

            await self._report_progress(step_num, len(steps), description)

            result = await self._run_step(script_cmd)
            self._step_results.append({
                "step": step_num,
                "script": script_cmd,
                "description": description,
                "success": result.get("success", False),
                "output": result.get("output", "")[:2000],
                "error": result.get("error", ""),
            })

            if not result.get("success", False):
                logger.warning("Step %d failed: %s — continuing pipeline", step_num, result.get("error", ""))

        # LLM narrative compilation step (Tier 2)
        llm_step = self._pipeline.get("llm_step")
        if llm_step:
            task_type, description = llm_step
            logger.info("LLM step: %s", description)
            await self._report_progress(len(steps) + 1, len(steps) + 2, f"LLM: {description}")

            try:
                narrative = await self._compile_narrative(task_type, description)
                self._step_results.append({
                    "step": "llm",
                    "task_type": task_type,
                    "description": description,
                    "success": True,
                    "output": narrative[:2000],
                })
            except Exception as e:
                logger.warning("LLM narrative step failed: %s — pipeline continues", e)
                self._step_results.append({
                    "step": "llm",
                    "task_type": task_type,
                    "success": False,
                    "error": str(e)[:500],
                })

        # Run report script
        report_script = self._pipeline.get("report_script")
        if report_script:
            logger.info("Running report script: %s", report_script)
            await self._run_step(report_script)

        report_phoenix = self._pipeline.get("report_to_phoenix")
        if report_phoenix:
            await self._run_step(report_phoenix)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        await self._update_session_status("completed")

        result = {
            "status": status,
            "agent_type": self.agent_type,
            "session_id": str(self.session_id),
            "steps": self._step_results,
            "elapsed_seconds": round(elapsed, 1),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        # Write checkpoint
        try:
            checkpoint = self.work_dir / f"{self.agent_type}_done.json"
            checkpoint.write_text(json.dumps(result, indent=2, default=str))
        except Exception:
            pass

        logger.info(
            "ScheduledAgentRunner completed: type=%s elapsed=%.1fs steps=%d",
            self.agent_type, elapsed, len(self._step_results),
        )
        return result

    async def _run_step(self, script_cmd: str) -> dict:
        """Execute a single pipeline script."""
        parts = script_cmd.split()
        script_name = parts[0]
        extra_args = parts[1:] if len(parts) > 1 else []

        script_path = self._template_dir / "tools" / script_name
        if not script_path.exists():
            return {"success": False, "error": f"Script not found: {script_path}"}

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(script_path), *extra_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.work_dir),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=STEP_TIMEOUT,
            )

            success = proc.returncode == 0
            output = stdout.decode(errors="replace") if stdout else ""
            error_output = stderr.decode(errors="replace") if stderr else ""

            if not success:
                logger.warning("Step %s failed (rc=%d): %s", script_name, proc.returncode, error_output[:300])

            return {
                "success": success,
                "output": output[:5000],
                "error": error_output[:1000] if not success else "",
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": f"Timeout after {STEP_TIMEOUT}s"}
        except Exception as e:
            return {"success": False, "error": str(e)[:500]}

    async def _compile_narrative(self, task_type: str, description: str) -> str:
        """Use ModelRouter for narrative compilation (Tier 2)."""
        from shared.utils.model_router import get_router

        router = get_router(agent_id=self.agent_id)

        collected_data = "\n".join(
            f"Step {s['step']} ({s['description']}): {s['output'][:500]}"
            for s in self._step_results
            if s.get("success") and s.get("output")
        )

        if not collected_data:
            return "No data collected from pipeline steps."

        system = (
            f"You are generating a {self.agent_type.replace('_', ' ')} report for a trading bot. "
            "Be concise, actionable, and data-driven. Focus on key metrics and insights."
        )

        prompt = f"""{description}

Here is the data collected from the pipeline:

{collected_data[:3000]}

Generate a concise, well-structured report."""

        resp = await router.complete(
            task_type=task_type,
            prompt=prompt,
            system=system,
            temperature=0.5,
            max_tokens=1024,
            agent_id=self.agent_id,
        )

        # Save narrative
        narrative_path = self.work_dir / f"{self.agent_type}_narrative.md"
        try:
            narrative_path.write_text(resp.text)
        except Exception:
            pass

        return resp.text

    async def _update_session_status(self, status: str) -> None:
        """Update the AgentSession status in the DB."""
        try:
            from shared.db.engine import get_session
            from shared.db.models.agent_session import AgentSession
            from sqlalchemy import update

            async for db in get_session():
                values: dict[str, Any] = {
                    "status": status,
                    "last_heartbeat": datetime.now(timezone.utc),
                }
                if status == "completed":
                    values["completed_at"] = datetime.now(timezone.utc)
                await db.execute(
                    update(AgentSession)
                    .where(AgentSession.id == self.session_id)
                    .values(**values)
                )
                await db.commit()
        except Exception as e:
            logger.debug("Session status update failed (non-fatal): %s", e)

    async def _report_progress(self, step: int, total: int, description: str) -> None:
        """Report progress for dashboard display."""
        try:
            from shared.db.engine import get_session
            from shared.db.models.agent_session import AgentSession
            from sqlalchemy import update

            progress = {
                "current_step": step,
                "total_steps": total,
                "description": description,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            async for db in get_session():
                await db.execute(
                    update(AgentSession)
                    .where(AgentSession.id == self.session_id)
                    .values(last_heartbeat=datetime.now(timezone.utc))
                )
                await db.commit()
        except Exception:
            pass
