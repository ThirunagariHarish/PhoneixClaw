"""
Notifications API — unread count, list (filterable), mark read, mark single read, delete old.
Supports the Notification Center bell popover and full /notifications page.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.notification import Notification

router = APIRouter(prefix="/api/v2/notifications", tags=["notifications"])


def _notification_to_dict(n: Notification) -> dict:
    def _iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return dt.isoformat().replace("+00:00", "Z")

    return {
        "id": str(n.id),
        "user_id": str(n.user_id) if n.user_id else None,
        "title": n.title,
        "body": n.body,
        "category": n.category,
        "severity": n.severity,
        "source": n.source,
        "event_type": n.event_type,
        "agent_id": str(n.agent_id) if n.agent_id else None,
        "read": n.read,
        "data": n.data if n.data else {},
        "created_at": _iso(n.created_at),
        "read_at": _iso(n.read_at),
    }


@router.get("/unread-count")
async def unread_count(session: AsyncSession = Depends(get_session)) -> dict:
    """Return count of unread notifications."""
    result = await session.execute(
        select(func.count(Notification.id)).where(Notification.read.is_(False))
    )
    count = result.scalar() or 0
    return {"count": count}


@router.get("")
async def list_notifications(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    type: Optional[str] = Query(default=None, description="Filter by event_type (e.g. TRADE_FILLED, RISK_BREACH)"),
    category: Optional[str] = Query(default=None, description="Filter by category (trades, risk, agents, system)"),
    read: Optional[bool] = Query(default=None, description="Filter by read status"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return recent notifications with filtering and pagination."""
    q = select(Notification)

    if type is not None:
        q = q.where(Notification.event_type == type)
    if category is not None:
        q = q.where(Notification.category == category)
    if read is not None:
        q = q.where(Notification.read.is_(read))

    # Get total count for pagination
    count_q = select(func.count()).select_from(q.subquery())
    total_result = await session.execute(count_q)
    total = total_result.scalar() or 0

    # Fetch items
    q = q.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(q)
    rows = result.scalars().all()

    return {
        "items": [_notification_to_dict(n) for n in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.put("/{notification_id}/read")
async def mark_one_read(
    notification_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Mark a single notification as read."""
    await session.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .values(read=True, read_at=datetime.now(timezone.utc))
    )
    return {"ok": True}


@router.patch("/mark-read")
async def mark_read(session: AsyncSession = Depends(get_session)) -> dict:
    """Mark all current notifications as read."""
    await session.execute(
        update(Notification)
        .where(Notification.read.is_(False))
        .values(read=True, read_at=datetime.now(timezone.utc))
    )
    return {"ok": True}


@router.put("/read-all")
async def mark_all_read(session: AsyncSession = Depends(get_session)) -> dict:
    """Mark all notifications as read (alias for PATCH /mark-read)."""
    await session.execute(
        update(Notification)
        .where(Notification.read.is_(False))
        .values(read=True, read_at=datetime.now(timezone.utc))
    )
    return {"ok": True}


@router.delete("/old")
async def delete_old(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete read notifications older than N days."""
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    cutoff = cutoff - timedelta(days=days)
    result = await session.execute(
        delete(Notification)
        .where(Notification.read.is_(True))
        .where(Notification.created_at < cutoff)
    )
    return {"deleted": result.rowcount}
