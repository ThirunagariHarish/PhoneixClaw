"""
Agent Learning API routes — manage behavior learning sessions.

Sessions ingest content from YouTube, Discord, or trade logs to build
trading behavior profiles that can be deployed as autonomous agents.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session as get_db_session
from shared.db.models.learning_session import LearningSession

router = APIRouter(prefix="/api/v2/agent-learning", tags=["agent-learning"])

_STANDALONE_AGENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _snapshot_defaults() -> dict[str, Any]:
    return {
        "source_url": "",
        "learning_depth": "standard",
        "auto_deploy": False,
        "behavior_profile": None,
        "key_concepts": [],
        "progress": 0,
    }


def _row_to_api(ls: LearningSession) -> dict[str, Any]:
    extra = _snapshot_defaults()
    if ls.config_snapshot:
        try:
            parsed = json.loads(ls.config_snapshot)
            if isinstance(parsed, dict):
                extra.update(parsed)
        except json.JSONDecodeError:
            pass
    return {
        "id": str(ls.id),
        "agent_name": ls.channel_name or "",
        "source_type": ls.session_type,
        "source_url": extra.get("source_url", ""),
        "status": ls.status,
        "progress": int(extra.get("progress", 0)),
        "target_role": ls.model_type or "",
        "learning_depth": extra.get("learning_depth", "standard"),
        "auto_deploy": bool(extra.get("auto_deploy", False)),
        "behavior_profile": extra.get("behavior_profile"),
        "key_concepts": extra.get("key_concepts") or [],
        "created_at": ls.started_at.isoformat() if ls.started_at else "",
    }


def _merge_snapshot(ls: LearningSession, updates: dict[str, Any]) -> None:
    base = _snapshot_defaults()
    if ls.config_snapshot:
        try:
            parsed = json.loads(ls.config_snapshot)
            if isinstance(parsed, dict):
                base.update(parsed)
        except json.JSONDecodeError:
            pass
    base.update(updates)
    ls.config_snapshot = json.dumps(base)


class SessionCreate(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=120)
    source_type: str = Field(..., pattern="^(youtube_channel|youtube_playlist|discord_channel|trade_log)$")
    source_url: str = Field(..., min_length=1)
    target_role: str = Field(..., pattern="^(day_trader|swing_trader|options_specialist|scalper)$")
    learning_depth: str = Field(default="standard", pattern="^(quick|standard|deep)$")
    auto_deploy: bool = False


@router.get("/sessions")
async def list_sessions(session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(LearningSession).order_by(LearningSession.started_at.desc()))
    rows = result.scalars().all()
    return [_row_to_api(ls) for ls in rows]


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    session: AsyncSession = Depends(get_db_session),
):
    row = LearningSession(
        agent_id=_STANDALONE_AGENT_ID,
        session_type=payload.source_type,
        status="INGESTING",
        channel_name=payload.agent_name,
        model_type=payload.target_role,
        started_at=datetime.now(timezone.utc),
    )
    _merge_snapshot(
        row,
        {
            "source_url": payload.source_url,
            "learning_depth": payload.learning_depth,
            "auto_deploy": payload.auto_deploy,
            "behavior_profile": None,
            "key_concepts": [],
            "progress": 0,
        },
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_api(row)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, session: AsyncSession = Depends(get_db_session)):
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    result = await session.execute(select(LearningSession).where(LearningSession.id == sid))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return _row_to_api(row)


@router.post("/sessions/{session_id}/deploy")
async def deploy_session(session_id: str, session: AsyncSession = Depends(get_db_session)):
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    result = await session.execute(select(LearningSession).where(LearningSession.id == sid))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if row.status != "READY":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session must be in READY state to deploy")
    row.status = "DEPLOYED"
    return {"id": session_id, "status": "DEPLOYED"}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, session: AsyncSession = Depends(get_db_session)):
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    result = await session.execute(select(LearningSession).where(LearningSession.id == sid))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await session.delete(row)
