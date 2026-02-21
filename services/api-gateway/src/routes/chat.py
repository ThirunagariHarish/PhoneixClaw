import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import ChatMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_kafka_producer = None


def set_kafka_producer(producer):
    global _kafka_producer
    _kafka_producer = producer


class ChatSendRequest(BaseModel):
    message: str


class ChatMessageResponse(BaseModel):
    id: int
    content: str
    role: str
    trade_id: str | None
    created_at: str


@router.post("/send")
async def send_chat_message(
    body: ChatSendRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id

    msg = ChatMessage(
        user_id=uuid.UUID(user_id),
        content=body.message,
        role="user",
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)

    if _kafka_producer and _kafka_producer.is_started:
        try:
            await _kafka_producer.send(
                topic="raw-messages",
                value={
                    "content": body.message,
                    "user_id": user_id,
                    "author": user_id,
                    "source": "chat",
                    "source_type": "chat",
                    "channel_id": "chat-widget",
                    "channel_name": "chat-widget",
                    "message_id": str(msg.id),
                    "source_message_id": str(msg.id),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                key=user_id,
                headers=[
                    ("user_id", user_id.encode()),
                    ("source", b"chat"),
                ],
            )
        except Exception:
            logger.exception("Failed to publish chat message to Kafka")

    system_reply = ChatMessage(
        user_id=uuid.UUID(user_id),
        content=f"Signal received: \"{body.message}\". Routing to trade parser...",
        role="system",
    )
    session.add(system_reply)
    await session.commit()
    await session.refresh(system_reply)

    return {
        "status": "sent",
        "message_id": msg.id,
        "system_reply": {
            "id": system_reply.id,
            "content": system_reply.content,
            "role": system_reply.role,
            "created_at": system_reply.created_at.isoformat() if system_reply.created_at else None,
        },
    }


@router.get("/history")
async def get_chat_history(
    request: Request,
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.user_id == uuid.UUID(user_id))
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    messages = list(reversed(result.scalars().all()))

    return [
        {
            "id": m.id,
            "content": m.content,
            "role": m.role,
            "trade_id": str(m.trade_id) if m.trade_id else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]
