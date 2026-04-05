"""
Notifications API — unread count, list, mark read.
Stub for sidebar bell popover.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
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
        "user_id": str(n.user_id),
        "title": n.title,
        "body": n.body,
        "category": n.category,
        "severity": n.severity,
        "source": n.source,
        "agent_id": str(n.agent_id) if n.agent_id else None,
        "read": n.read,
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
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> list:
    """Return recent notifications."""
    result = await session.execute(
        select(Notification)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [_notification_to_dict(n) for n in rows]


@router.patch("/mark-read")
async def mark_read(session: AsyncSession = Depends(get_session)) -> dict:
    """Mark all current notifications as read."""
    await session.execute(
        update(Notification)
        .where(Notification.read.is_(False))
        .values(read=True, read_at=datetime.now(timezone.utc))
    )
    return {"ok": True}
