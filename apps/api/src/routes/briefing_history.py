"""Briefing History API — list and fetch past briefings.

Routes:
    GET  /api/v2/briefings               list with filters
    GET  /api/v2/briefings/{id}          single briefing detail
    POST /api/v2/briefings               create (called by morning-briefing agent)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from apps.api.src.deps import DbSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/briefings", tags=["briefings"])


class BriefingCreate(BaseModel):
    kind: str
    title: str
    body: str
    data: dict | None = None
    agents_woken: int = 0
    dispatched_to: list[str] | None = None
    agent_session_id: str | None = None


@router.get("")
async def list_briefings(
    kind: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    session: DbSession = None,
):
    where = []
    params: dict = {"lim": limit, "off": offset}
    if kind:
        where.append("kind = :kind")
        params["kind"] = kind
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = (await session.execute(
        text(
            f"SELECT id, kind, title, body, data, agents_woken, dispatched_to, "
            f"created_at FROM briefing_history {clause} "
            f"ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ),
        params,
    )).all()
    return {
        "briefings": [
            {
                "id": int(r[0]),
                "kind": r[1],
                "title": r[2],
                "body": r[3],
                "data": r[4] or {},
                "agents_woken": int(r[5] or 0),
                "dispatched_to": list(r[6] or []),
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/{briefing_id}")
async def get_briefing(briefing_id: int, session: DbSession = None):
    row = (await session.execute(
        text(
            "SELECT id, kind, title, body, data, agents_woken, dispatched_to, "
            "created_at FROM briefing_history WHERE id = :id"
        ),
        {"id": briefing_id},
    )).first()
    if not row:
        raise HTTPException(404, "not found")
    return {
        "id": int(row[0]),
        "kind": row[1],
        "title": row[2],
        "body": row[3],
        "data": row[4] or {},
        "agents_woken": int(row[5] or 0),
        "dispatched_to": list(row[6] or []),
        "created_at": row[7].isoformat() if row[7] else None,
    }


@router.post("")
async def create_briefing(body: BriefingCreate, session: DbSession = None):
    """Called by the morning-briefing agent (Phase 4) to persist the run."""
    import json as _json
    try:
        res = await session.execute(
            text(
                "INSERT INTO briefing_history "
                "(kind, title, body, data, agents_woken, dispatched_to, agent_session_id) "
                "VALUES (:kind, :title, :body, CAST(:data AS JSONB), :woken, :dispatched, :session_id) "
                "RETURNING id, created_at"
            ),
            {
                "kind": body.kind,
                "title": body.title[:200],
                "body": body.body,
                "data": _json.dumps(body.data or {}),
                "woken": body.agents_woken,
                "dispatched": body.dispatched_to or [],
                "session_id": body.agent_session_id,
            },
        )
        row = res.first()
        await session.commit()

        # Also route through notification_dispatcher so the user sees it live
        try:
            from apps.api.src.services.notification_dispatcher import notification_dispatcher
            await notification_dispatcher.dispatch(
                event_type=f"{body.kind}_briefing",
                agent_id=None,
                title=body.title,
                body=body.body,
                channels=body.dispatched_to or ["ws", "db"],
            )
        except Exception as exc:
            logger.warning("[briefings] dispatch failed: %s", exc)

        return {
            "id": int(row[0]),
            "created_at": row[1].isoformat() if row[1] else None,
        }
    except Exception as exc:
        logger.exception("briefing persist failed")
        raise HTTPException(500, str(exc)[:400])
