import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import RawMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/messages", tags=["messages"])


@router.get("")
async def list_messages(
    request: Request,
    source_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    is_admin = getattr(request.state, "is_admin", False)

    filters = []
    if not is_admin:
        try:
            filters.append(RawMessage.user_id == uuid.UUID(user_id))
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid user ID format")

    if source_id:
        try:
            filters.append(RawMessage.data_source_id == uuid.UUID(source_id))
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid source_id format")

    stmt = (
        select(RawMessage)
        .where(*filters)
        .order_by(desc(RawMessage.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    count_stmt = select(func.count(RawMessage.id)).where(*filters)
    total = (await session.execute(count_stmt)).scalar() or 0

    return {
        "total": total,
        "has_more": offset + limit < total,
        "messages": [
            {
                "id": str(m.id),
                "data_source_id": str(m.data_source_id) if m.data_source_id else None,
                "source_type": m.source_type,
                "channel_name": m.channel_name,
                "author": m.author,
                "content": m.content,
                "source_message_id": m.source_message_id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ],
    }
