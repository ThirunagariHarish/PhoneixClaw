"""
Error logs API — create, list, update, stats. For Dev Sprint Board and error logging framework.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.error_log import ErrorLog

router = APIRouter(prefix="/api/v2/error-logs", tags=["error-logs"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return dt.isoformat().replace("+00:00", "Z")


def _ctx_json_expr():
    return cast(func.coalesce(ErrorLog.context, literal("{}")), JSONB)


def _effective_status_expr():
    return func.coalesce(_ctx_json_expr()["status"].astext, literal("open"))


def _parse_ctx(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


def _default_ctx(body: dict, overrides: dict | None = None) -> dict[str, Any]:
    base = {
        "url": body.get("url", ""),
        "source": body.get("source", "global_handler"),
        "user_id": body.get("user_id"),
        "user_agent": body.get("user_agent"),
        "fingerprint": body.get("fingerprint", ""),
        "status": body.get("status", "open"),
        "fix_attempt_count": body.get("fix_attempt_count", 0),
        "fix_notes": body.get("fix_notes"),
    }
    if overrides:
        base.update(overrides)
    return base


def _serialize_error_log(e: ErrorLog) -> dict:
    ctx = _parse_ctx(e.context)
    return {
        "id": str(e.id),
        "component": e.service,
        "message": e.message,
        "stack": e.stack_trace,
        "url": ctx.get("url", ""),
        "source": ctx.get("source", "global_handler"),
        "user_id": ctx.get("user_id"),
        "user_agent": ctx.get("user_agent"),
        "fingerprint": ctx.get("fingerprint", ""),
        "severity": e.severity,
        "status": ctx.get("status", "open"),
        "fix_attempt_count": ctx.get("fix_attempt_count", 0),
        "fix_notes": ctx.get("fix_notes"),
        "created_at": _iso_z(e.first_seen) or "",
        "updated_at": _iso_z(e.last_seen) or "",
        "resolved_at": _iso_z(e.resolved_at),
    }


def _parse_uuid(val: str | None) -> uuid.UUID | None:
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None


@router.post("")
async def create_error_log(
    body: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create an error log entry from frontend (historical: openclaw_agent source deprecated)."""
    log_id = uuid.uuid4()
    now = _now_utc()
    ctx = _default_ctx(body)
    entry = ErrorLog(
        id=log_id,
        service=body.get("component", "global"),
        agent_id=_parse_uuid(body.get("agent_id")),
        error_type=body.get("error_type") or "application_error",
        message=body.get("message", ""),
        stack_trace=body.get("stack"),
        severity=body.get("severity", "error"),
        context=json.dumps(ctx),
        resolved=False,
        occurrence_count=1,
        first_seen=now,
        last_seen=now,
        resolved_at=None,
    )
    session.add(entry)
    await session.flush()
    return {"id": str(log_id), "ok": True}


@router.post("/ingest-agent-activity")
async def ingest_agent_activity(
    body: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ingest logs from agents (historical endpoint, deprecated). Creates error_log entries with source=openclaw_agent."""
    logs = body.get("logs", [])
    if not isinstance(logs, list):
        return {"ok": False, "detail": "logs must be an array"}
    instance_id = body.get("instance_id", "unknown")
    created = 0
    for item in logs:
        if not isinstance(item, dict):
            item = {}
        log_id = uuid.uuid4()
        now = _now_utc()
        message = item.get("message", str(item))[:500]
        msg_hash = str(hash(message))
        ctx = _default_ctx(
            {
                "url": item.get("url", ""),
                "source": "openclaw_agent",
                "fingerprint": item.get("fingerprint", msg_hash),
                "severity": item.get("severity", "error"),
            }
        )
        comp = item.get("component") or item.get("agent_id") or instance_id
        entry = ErrorLog(
            id=log_id,
            service=str(comp),
            agent_id=_parse_uuid(item.get("agent_id")),
            error_type=item.get("error_type") or "agent_activity",
            message=message,
            stack_trace=item.get("stack"),
            severity=item.get("severity", "error"),
            context=json.dumps(ctx),
            resolved=False,
            occurrence_count=1,
            first_seen=now,
            last_seen=now,
            resolved_at=None,
        )
        session.add(entry)
        created += 1
    await session.flush()
    return {"ok": True, "created": created}


@router.get("")
async def list_error_logs(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    component: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    session: AsyncSession = Depends(get_session),
) -> list:
    """List error logs with optional filters."""
    stmt = select(ErrorLog)
    if status:
        stmt = stmt.where(_effective_status_expr() == status)
    if severity:
        parts = [s.strip() for s in severity.split(",") if s.strip()]
        if parts:
            stmt = stmt.where(ErrorLog.severity.in_(parts))
    if component:
        stmt = stmt.where(ErrorLog.service == component)
    stmt = stmt.order_by(ErrorLog.last_seen.desc()).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_serialize_error_log(e) for e in rows]


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)) -> dict:
    """Aggregate stats for Dev Sprint Board."""
    total_r = await session.execute(select(func.count(ErrorLog.id)))
    total = total_r.scalar() or 0

    status_col = _effective_status_expr()
    status_rows = await session.execute(
        select(status_col, func.count(ErrorLog.id)).group_by(status_col)
    )
    by_status: dict[str, int] = {row[0] or "open": row[1] for row in status_rows.all()}

    comp_rows = await session.execute(
        select(ErrorLog.service, func.count(ErrorLog.id)).group_by(ErrorLog.service)
    )
    by_component: dict[str, int] = {row[0]: row[1] for row in comp_rows.all()}

    open_count = by_status.get("open", 0)
    fixed_agent = by_status.get("fixed_by_agent", 0)
    fixed_admin = by_status.get("fixed_by_admin", 0)
    needs_admin = by_status.get("needs_admin", 0)
    resolved = fixed_agent + fixed_admin + by_status.get("wont_fix", 0)
    fix_rate = (resolved / total * 100) if total else 0
    return {
        "total": total,
        "open": open_count,
        "fixed_by_agent": fixed_agent,
        "fixed_by_admin": fixed_admin,
        "needs_admin": needs_admin,
        "fix_rate_pct": round(fix_rate, 1),
        "by_status": by_status,
        "by_component": by_component,
    }


@router.get("/{log_id}")
async def get_error_log(
    log_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get a single error log by id."""
    uid = _parse_uuid(log_id)
    if uid is None:
        return {"detail": "Not found"}
    result = await session.execute(select(ErrorLog).where(ErrorLog.id == uid))
    row = result.scalar_one_or_none()
    if row is None:
        return {"detail": "Not found"}
    return _serialize_error_log(row)


@router.patch("/{log_id}")
async def update_error_log(
    log_id: str,
    body: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Update status and optional fix_notes."""
    uid = _parse_uuid(log_id)
    if uid is None:
        return {"detail": "Not found"}
    result = await session.execute(select(ErrorLog).where(ErrorLog.id == uid))
    e = result.scalar_one_or_none()
    if e is None:
        return {"detail": "Not found"}
    ctx = _parse_ctx(e.context)
    now = _now_utc()
    if "status" in body:
        ctx["status"] = body["status"]
    if "fix_notes" in body:
        ctx["fix_notes"] = body["fix_notes"]
    if body.get("status") in ("fixed_by_agent", "fixed_by_admin", "wont_fix"):
        e.resolved_at = now
        e.resolved = True
    if "fix_attempt_count" in body:
        ctx["fix_attempt_count"] = body["fix_attempt_count"]
    e.context = json.dumps(ctx)
    e.last_seen = now
    await session.flush()
    return _serialize_error_log(e)


@router.post("/trigger-agent-review")
async def trigger_agent_review(session: AsyncSession = Depends(get_session)) -> dict:
    """Simulate daily agent review: group open errors by component and return summary."""
    stmt = (
        select(ErrorLog)
        .where(_effective_status_expr() == literal("open"))
        .order_by(ErrorLog.last_seen.desc())
    )
    result = await session.execute(stmt)
    open_errors = result.scalars().all()
    by_component: dict[str, list[dict]] = {}
    for e in open_errors:
        d = _serialize_error_log(e)
        c = d["component"]
        if c not in by_component:
            by_component[c] = []
        by_component[c].append(
            {"id": d["id"], "message": (d.get("message") or "")[:200], "severity": d.get("severity")}
        )
    return {
        "ok": True,
        "open_count": len(open_errors),
        "by_component": {k: len(v) for k, v in by_component.items()},
        "summary": [
            {"component": k, "count": len(v), "samples": v[:3]}
            for k, v in by_component.items()
        ],
    }
