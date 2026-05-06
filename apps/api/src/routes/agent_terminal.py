"""P14: Admin-only WebSocket terminal into an agent's working directory.

Gated by:
    - JWT auth (existing middleware — user must be authenticated)
    - RBAC: user.role must be 'admin' (checked against the JWT claims)
    - Feature flag ENABLE_AGENT_TERMINAL=1 (off by default in prod)

Frontend pairs this with xterm.js + WebSocket client.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid as _uuid
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/agents", tags=["agent_terminal"])


def _terminal_enabled() -> bool:
    return os.environ.get("ENABLE_AGENT_TERMINAL", "0") == "1"


async def _resolve_workdir(agent_id: str) -> Path | None:
    """Find the agent's working directory from AgentSession or a fallback."""
    try:
        from sqlalchemy import select

        from shared.db.engine import get_session
        from shared.db.models.agent_session import AgentSession
        async for sess in get_session():
            res = await sess.execute(
                select(AgentSession)
                .where(AgentSession.agent_id == _uuid.UUID(agent_id))
                .order_by(AgentSession.started_at.desc())
                .limit(1)
            )
            row = res.scalar_one_or_none()
            if row and row.working_dir:
                p = Path(row.working_dir)
                if p.exists():
                    return p
            break
    except Exception as exc:
        logger.debug("[agent_terminal] resolve workdir failed: %s", exc)

    # Fallback: standard agent dir layout
    candidate = Path(os.environ.get("PHOENIX_DATA_DIR", "/app/data")) / "agents" / "live" / agent_id
    if candidate.exists():
        return candidate
    return None


@router.websocket("/{agent_id}/terminal")
async def agent_terminal(websocket: WebSocket, agent_id: str):
    if not _terminal_enabled():
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="terminal_disabled")
        return

    # Best-effort RBAC check — middleware populates state.user.role
    try:
        user = getattr(websocket.state, "user", None)
        role = getattr(user, "role", None) if user else None
        if role != "admin":
            await websocket.close(code=4001, reason="admin_only")
            return
    except Exception:
        await websocket.close(code=4001, reason="auth_required")
        return

    workdir = await _resolve_workdir(agent_id)
    if workdir is None:
        await websocket.close(code=4004, reason="workdir_not_found")
        return

    await websocket.accept()
    await websocket.send_text(f"\r\n[phoenix-terminal] connected to {workdir}\r\n$ ")

    try:
        import pty
        master, slave = pty.openpty()
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash", "-i",
            cwd=str(workdir),
            stdin=slave, stdout=slave, stderr=slave,
            env={**os.environ, "TERM": "xterm-256color", "PS1": "$ "},
        )
    except Exception as exc:
        await websocket.send_text(f"\r\n[phoenix-terminal] failed to spawn shell: {exc}\r\n")
        await websocket.close()
        return

    async def _pump_out():
        loop = asyncio.get_event_loop()
        try:
            while True:
                data = await loop.run_in_executor(None, os.read, master, 4096)
                if not data:
                    break
                try:
                    await websocket.send_text(data.decode("utf-8", errors="replace"))
                except Exception:
                    break
        except Exception:
            pass

    pump_task = asyncio.create_task(_pump_out())

    try:
        while True:
            msg = await websocket.receive_text()
            os.write(master, msg.encode("utf-8"))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("[agent_terminal] loop error: %s", exc)
    finally:
        pump_task.cancel()
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            os.close(master)
        except Exception:
            pass
