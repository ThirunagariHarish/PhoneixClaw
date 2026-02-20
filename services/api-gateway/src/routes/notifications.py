import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import NotificationLog

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    request: Request,
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    stmt = (
        select(NotificationLog)
        .where(NotificationLog.user_id == uuid.UUID(user_id))
        .order_by(desc(NotificationLog.created_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": n.id,
            "type": n.notification_type,
            "title": n.title,
            "body": n.body,
            "read": n.read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in rows
    ]


@router.get("/unread-count")
async def unread_count(request: Request, session: AsyncSession = Depends(get_session)):
    user_id = request.state.user_id
    result = await session.execute(
        select(func.count(NotificationLog.id)).where(
            NotificationLog.user_id == uuid.UUID(user_id),
            NotificationLog.read.is_(False),
        )
    )
    return {"unread_count": result.scalar() or 0}
