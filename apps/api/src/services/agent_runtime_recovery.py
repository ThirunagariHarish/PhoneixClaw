"""Agent runtime recovery on API startup.

Phase H3 — fixes the catastrophic problem that `_running_tasks` in agent_gateway
is a module-level dict. When the API container restarts, all running agent
processes are killed but the database still shows `agent_sessions.status =
'running'`. The dashboard lies about what's running.

This module runs on lifespan startup and:
1. Queries `agent_sessions WHERE status IN ('running', 'starting')`
2. For each, checks whether the working_dir still exists and the process is alive
3. Marks dead ones as `interrupted` with a recovery_at timestamp
4. For resumable session types (analyst, position monitor), calls gateway.resume_agent()
   so the work continues from the latest persisted state
5. Records the recovery action in `system_logs` for audit
"""
from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Session types that we KNOW how to resume safely — expanded for three-tier
RESUMABLE_TYPES = {"analyst", "live_trader"}

# Tier 2 agents that can be re-spawned cheaply (no Claude SDK needed)
RESPAWNABLE_TYPES = {"position_monitor", "supervisor", "morning_briefing",
                     "eod_analysis", "daily_summary", "trade_feedback", "backtester"}


async def recover_agents_on_startup() -> dict:
    """Main entrypoint, called from lifespan.

    Returns a summary dict for logging.
    """
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "found_running": 0,
        "marked_interrupted": 0,
        "resumed": 0,
        "tools_deployed": 0,
        "errors": [],
    }

    try:
        from sqlalchemy import select

        from shared.db.engine import get_session
        from shared.db.models.agent_session import AgentSession
        from shared.db.models.system_log import SystemLog
    except Exception as exc:
        summary["errors"].append(f"import failed: {exc}")
        return summary

    sessions_to_recover: list[dict] = []

    async for db in get_session():
        result = await db.execute(
            select(AgentSession).where(
                AgentSession.status.in_(["running", "starting", "stale"]),
            )
        )
        rows = list(result.scalars().all())
        summary["found_running"] = len(rows)

        for sess in rows:
            sessions_to_recover.append({
                "id": sess.id,
                "agent_id": sess.agent_id,
                "agent_type": sess.agent_type,
                "session_role": sess.session_role,
                "working_dir": sess.working_dir,
                "parent_agent_id": sess.parent_agent_id,
                "position_ticker": sess.position_ticker,
            })

    # Mark all as interrupted first (since we know the process is dead — we just started)
    now = datetime.now(timezone.utc)
    interrupted_ids: list[uuid.UUID] = []

    async for db in get_session():
        for s in sessions_to_recover:
            try:
                row = (await db.execute(
                    select(AgentSession).where(AgentSession.id == s["id"])
                )).scalar_one_or_none()
                if not row:
                    continue
                row.status = "interrupted"
                row.error_message = "API restart — process terminated"
                row.stopped_at = now
                interrupted_ids.append(s["id"])

                db.add(SystemLog(
                    id=uuid.uuid4(),
                    source="recovery",
                    level="WARN",
                    service="agent-runtime-recovery",
                    agent_id=str(s["agent_id"]),
                    message=(
                        f"Marked session {s['id']} ({s['agent_type']}) as interrupted "
                        f"after API restart"
                    ),
                ))
            except Exception as exc:
                summary["errors"].append(f"mark interrupted {s['id']}: {str(exc)[:200]}")
        await db.commit()

    summary["marked_interrupted"] = len(interrupted_ids)
    logger.info("[recovery] Marked %d sessions interrupted", len(interrupted_ids))

    # Hot-deploy any new/missing critical tools to all live agent directories.
    # Runs before resumption so that resuming agents already have the latest tools.
    try:
        deployed = _hot_deploy_critical_tools()
        summary["tools_deployed"] = deployed
        if deployed:
            logger.info("[recovery] Hot-deployed %d missing tool file(s) to live agent dirs", deployed)
    except Exception as exc:
        logger.warning("[recovery] Tool hot-deploy failed (non-fatal): %s", exc)

    # Now attempt to resume the resumable ones
    try:
        from apps.api.src.services.agent_gateway import gateway
    except Exception as exc:
        summary["errors"].append(f"gateway import failed: {exc}")
        return summary

    # Resume Tier 3 (Claude SDK) agents: analyst / live_trader
    for s in sessions_to_recover:
        if s["agent_type"] not in RESUMABLE_TYPES:
            continue
        if s.get("session_role") in ("position_monitor",):
            continue

        wd = s.get("working_dir")
        if wd and not Path(wd).exists():
            logger.warning("[recovery] Skipping resume of %s — working_dir gone: %s",
                           s["id"], wd)
            continue

        try:
            result = await gateway.resume_agent(s["agent_id"])
            status = result.get("status") if isinstance(result, dict) else str(result)
            if status in ("resuming", "already_running"):
                summary["resumed"] += 1
                logger.info("[recovery] Resumed analyst %s: %s", s["agent_id"], status)
            else:
                summary["errors"].append(f"resume {s['agent_id']}: {status}")
        except Exception as exc:
            summary["errors"].append(f"resume {s['agent_id']}: {str(exc)[:200]}")

    # Respawn Tier 2 position monitors (PositionMicroAgent)
    for s in sessions_to_recover:
        if s.get("session_role") != "position_monitor":
            continue
        if not s.get("position_ticker"):
            continue

        wd = s.get("working_dir")
        if not wd or not Path(wd).exists():
            continue

        try:
            position_file = Path(wd) / "position.json"
            config_file = Path(wd) / "config.json"
            if not position_file.exists():
                continue

            import json as _json
            position = _json.loads(position_file.read_text())
            config = _json.loads(config_file.read_text()) if config_file.exists() else {}

            import asyncio as _asyncio

            from apps.api.src.services.position_micro_agent import PositionMicroAgent

            new_session_id = uuid.uuid4()
            agent = PositionMicroAgent(
                agent_id=s["agent_id"],
                session_id=new_session_id,
                position=position,
                config=config,
                work_dir=Path(wd),
            )

            from apps.api.src.services.agent_gateway import _running_tasks
            task_key = f"{s['agent_id']}:{position.get('position_id', s['position_ticker'])}"
            task = _asyncio.create_task(agent.run())
            _running_tasks[task_key] = task
            summary["resumed"] += 1
            logger.info("[recovery] Re-spawned position micro-agent for %s", s["position_ticker"])
        except Exception as exc:
            summary["errors"].append(f"respawn position {s.get('position_ticker')}: {str(exc)[:200]}")

    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "[recovery] Done: found=%d interrupted=%d resumed=%d tools_deployed=%d errors=%d",
        summary["found_running"], summary["marked_interrupted"],
        summary["resumed"], summary["tools_deployed"], len(summary["errors"]),
    )
    return summary


def _hot_deploy_critical_tools() -> int:
    """Copy any missing critical tool files to all live agent working directories.

    Uses ``_AGENT_CRITICAL_TOOLS`` from agent_gateway as the single source of
    truth for which tools are required.

    Only copies files that do NOT yet exist in the agent's tools/ dir — never
    overwrites files that are already present (avoids disrupting running agents).

    Returns the number of tool files copied.
    """
    try:
        from apps.api.src.services.agent_gateway import (
            _AGENT_CRITICAL_TOOLS,
            DATA_DIR,
            LIVE_TEMPLATE,
        )
    except Exception as exc:
        logger.warning("[hot_deploy] Could not import gateway paths: %s", exc)
        return 0

    live_agents_dir = DATA_DIR / "live_agents"
    if not live_agents_dir.exists():
        return 0

    deployed = 0
    dirs_checked = 0
    for agent_dir in live_agents_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        tools_dst = agent_dir / "tools"
        if not tools_dst.exists():
            continue
        dirs_checked += 1
        for tool_name in _AGENT_CRITICAL_TOOLS:
            src = LIVE_TEMPLATE / "tools" / tool_name
            dst = tools_dst / tool_name
            if src.exists() and not dst.exists():
                try:
                    shutil.copy2(src, dst)
                    deployed += 1
                    logger.info(
                        "[hot_deploy] Deployed %s → %s", tool_name, tools_dst
                    )
                except Exception as exc:
                    logger.warning(
                        "[hot_deploy] Failed to copy %s to %s: %s", tool_name, tools_dst, exc
                    )
    if not deployed:
        logger.debug(
            "[hot_deploy] No missing critical tools found across %d agent dir(s)", dirs_checked
        )
    return deployed
