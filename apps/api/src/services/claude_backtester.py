"""Claude Code Agent backtester — runs the pipeline via an autonomous Claude agent.

Instead of rigid subprocess steps with hardcoded CLI args, this spawns a
Claude Code agent that reads the pipeline instructions, runs each tool,
self-heals on errors, and reports progress back to Phoenix via HTTP callbacks.

Falls back to task_runner.py if the claude-agent-sdk is unavailable.
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
BACKTESTING_DIR = REPO_ROOT / "agents" / "backtesting"
BACKTESTING_TOOLS = BACKTESTING_DIR / "tools"

_running_tasks: dict[str, asyncio.Task] = {}


async def run_backtest(
    agent_id: uuid.UUID,
    backtest_id: uuid.UUID,
    config: dict,
) -> None:
    """Kick off backtesting via a Claude Code agent (or fall back to subprocess)."""
    task_key = str(agent_id)
    if task_key in _running_tasks and not _running_tasks[task_key].done():
        logger.warning("Backtest already running for agent %s", agent_id)
        return

    task = asyncio.create_task(_run_claude_pipeline(agent_id, backtest_id, config))
    _running_tasks[task_key] = task


def _build_prompt(agent_id: uuid.UUID, config: dict, work_dir: Path) -> str:
    """Build the Claude Code agent prompt with all necessary context."""
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
3. **Preprocess**: `python {tools_dir}/preprocess.py --input {output_dir}/enriched.parquet --output {output_dir}/preprocessed/`
4. **Train XGBoost**: `python {tools_dir}/train_xgboost.py --data {output_dir}/preprocessed --output {output_dir}/models/`
5. **Train LightGBM**: `python {tools_dir}/train_lightgbm.py --data {output_dir}/preprocessed --output {output_dir}/models/`
6. **Train CatBoost**: `python {tools_dir}/train_catboost.py --data {output_dir}/preprocessed --output {output_dir}/models/`
7. **Train RF**: `python {tools_dir}/train_rf.py --data {output_dir}/preprocessed --output {output_dir}/models/`
8. **Evaluate**: `python {tools_dir}/evaluate_models.py --models-dir {output_dir}/models --output {output_dir}/models/best_model.json`
9. **Patterns**: `python {tools_dir}/discover_patterns.py --data {output_dir} --output {output_dir}/patterns.json`
10. **Explainability**: `python {tools_dir}/build_explainability.py --model {output_dir}/models --data {output_dir}/preprocessed --output {output_dir}/explainability.json`
11. **Create Live Agent**: `python {tools_dir}/create_live_agent.py --config {config_path} --models {output_dir}/models --output {output_dir}/live_agent/`

## Progress Reporting

After each step, report progress via curl:
```bash
curl -s -X POST "{api_url}/api/v2/agents/{agent_id}/backtest-progress" \\
  -H "Content-Type: application/json" \\
  -H "X-Agent-Key: {api_key}" \\
  -d '{{"step": "<step_name>", "message": "<what happened>", "progress_pct": <pct>}}'
```

Progress percentages: transform=15, enrich=30, preprocess=35, train_xgboost=45, train_lightgbm=50, train_catboost=55, train_rf=58, evaluate=70, patterns=80, explainability=85, create_live_agent=95

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
- Create {output_dir}/models/ and {output_dir}/preprocessed/ directories before running those steps
- If a script fails, read the error, attempt to fix it, and retry ONCE
- If a script is missing a Python dependency, install it with pip
- Do NOT modify the tool scripts unless absolutely necessary to fix a bug
- Steps 4-7 (training) can run in parallel if you want, but sequential is fine too
- Report progress after EVERY step
"""


async def _run_claude_pipeline(
    agent_id: uuid.UUID,
    backtest_id: uuid.UUID,
    config: dict,
) -> None:
    """Try Claude Agent SDK first; fall back to subprocess pipeline on any failure."""
    work_dir = REPO_ROOT / "data" / f"backtest_{agent_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "output").mkdir(exist_ok=True)
    (work_dir / "output" / "models").mkdir(exist_ok=True)
    (work_dir / "output" / "preprocessed").mkdir(exist_ok=True)

    config_path = work_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2, default=str))

    use_claude = _can_use_claude_sdk()

    if not use_claude:
        async for session in _get_session():
            await _log(session, agent_id, backtest_id, "fallback", 3,
                       f"Claude SDK unavailable ({_sdk_unavailable_reason()}), using subprocess pipeline")
        await _fallback_to_task_runner(agent_id, backtest_id, config)
        return

    async for session in _get_session():
        await _log(session, agent_id, backtest_id, "claude_agent_start", 2,
                   "Starting Claude Code agent for backtesting")

    try:
        from claude_agent_sdk import query, ClaudeAgentOptions

        prompt = _build_prompt(agent_id, config, work_dir)
        options = ClaudeAgentOptions(
            cwd=str(work_dir),
            permission_mode="bypassPermissions",
            allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
        )

        last_text = ""
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "content") and isinstance(message.content, list):
                for block in message.content:
                    if hasattr(block, "text"):
                        last_text = block.text[-500:]
                        logger.debug("Claude agent [%s]: %s", agent_id, block.text[:200])

            if hasattr(message, "is_error"):
                if getattr(message, "is_error", False):
                    async for session in _get_session():
                        error_msg = f"Claude agent error: {last_text}"
                        await _mark_failed(session, agent_id, backtest_id, "claude_agent", error_msg[:500])
                    return

        async for session in _get_session():
            bt = (await session.execute(
                select(AgentBacktest).where(AgentBacktest.id == backtest_id)
            )).scalar_one_or_none()
            if bt and bt.status not in ("COMPLETED", "FAILED"):
                await _mark_completed(session, agent_id, backtest_id)

    except Exception as exc:
        error_str = str(exc)[:500]
        logger.warning("Claude SDK failed for agent %s: %s — falling back to subprocess", agent_id, error_str)
        async for session in _get_session():
            await _log(session, agent_id, backtest_id, "sdk_fallback", 3,
                       f"Claude SDK error ({error_str[:200]}), retrying with subprocess pipeline")
        await _fallback_to_task_runner(agent_id, backtest_id, config)
    finally:
        _running_tasks.pop(str(agent_id), None)


def _can_use_claude_sdk() -> bool:
    """Check if the Claude Agent SDK and CLI are available."""
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


async def _fallback_to_task_runner(
    agent_id: uuid.UUID,
    backtest_id: uuid.UUID,
    config: dict,
) -> None:
    """Run the pipeline using the subprocess-based task_runner."""
    from apps.api.src.services.task_runner import _run_pipeline
    await _run_pipeline(agent_id, backtest_id, config)


async def _log(
    session,
    agent_id: uuid.UUID,
    backtest_id: uuid.UUID,
    step: str,
    pct: int,
    message: str,
) -> None:
    bt = (await session.execute(
        select(AgentBacktest).where(AgentBacktest.id == backtest_id)
    )).scalar_one_or_none()
    if bt:
        bt.current_step = step
        bt.progress_pct = pct

    session.add(SystemLog(
        id=uuid.uuid4(), source="backtest", level="INFO", service="claude-backtester",
        agent_id=str(agent_id), backtest_id=str(backtest_id),
        message=message, step=step, progress_pct=pct,
    ))
    await session.commit()


async def _mark_completed(session, agent_id: uuid.UUID, backtest_id: uuid.UUID) -> None:
    now = datetime.now(timezone.utc)

    bt = (await session.execute(
        select(AgentBacktest).where(AgentBacktest.id == backtest_id)
    )).scalar_one_or_none()
    if bt:
        bt.status = "COMPLETED"
        bt.progress_pct = 100
        bt.current_step = "completed"
        bt.completed_at = now

    agent = (await session.execute(
        select(Agent).where(Agent.id == agent_id)
    )).scalar_one_or_none()
    if agent:
        agent.status = "BACKTEST_COMPLETE"
        agent.updated_at = now

    session.add(SystemLog(
        id=uuid.uuid4(), source="backtest", level="INFO", service="claude-backtester",
        agent_id=str(agent_id), backtest_id=str(backtest_id),
        message="Backtesting pipeline completed via Claude Code agent",
        step="completed", progress_pct=100,
    ))
    await session.commit()
    logger.info("Claude agent backtest completed for agent %s", agent_id)


async def _mark_failed(
    session,
    agent_id: uuid.UUID,
    backtest_id: uuid.UUID,
    step: str,
    error_msg: str,
) -> None:
    now = datetime.now(timezone.utc)

    bt = (await session.execute(
        select(AgentBacktest).where(AgentBacktest.id == backtest_id)
    )).scalar_one_or_none()
    if bt:
        bt.status = "FAILED"
        bt.error_message = error_msg
        bt.completed_at = now

    agent = (await session.execute(
        select(Agent).where(Agent.id == agent_id)
    )).scalar_one_or_none()
    if agent:
        agent.status = "CREATED"
        agent.updated_at = now

    session.add(SystemLog(
        id=uuid.uuid4(), source="backtest", level="ERROR", service="claude-backtester",
        agent_id=str(agent_id), backtest_id=str(backtest_id),
        message=error_msg, step=step,
    ))
    await session.commit()
    logger.error("Claude agent backtest failed for agent %s: %s", agent_id, error_msg)


def get_running_backtests() -> list[str]:
    return [k for k, t in _running_tasks.items() if not t.done()]


def cancel_backtest(agent_id: str) -> bool:
    task = _running_tasks.get(agent_id)
    if task and not task.done():
        task.cancel()
        return True
    return False
