"""
Chat API — trade chat history and send message stubs.
Ported from v1; used by ChatWidget.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.agent_chat import AgentChatMessage

router = APIRouter(prefix="/api/v2/chat", tags=["chat"])

# Global trade-chat stream (no per-agent id in legacy widget payload).
_TRADE_CHAT_AGENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _resolve_agent_id(body: dict) -> uuid.UUID:
    raw = body.get("agent_id")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except (ValueError, TypeError):
            pass
    return _TRADE_CHAT_AGENT_ID


@router.get("/history")
async def get_chat_history(
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    """Return the last ``limit`` chat messages in chronological order (oldest first)."""
    result = await session.execute(
        select(AgentChatMessage)
        .order_by(AgentChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    out = []
    for m in rows:
        out.append(
            {
                "id": str(m.id),
                "content": m.content,
                "role": m.role,
                "trade_id": None,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
        )
    return out


@router.post("/send")
async def send_message(
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    """Append a user message and return success. In production, would enqueue for trade pipeline."""
    msg = body.get("message", "")
    if not msg:
        return {"ok": False, "detail": "message required"}
    agent_id = _resolve_agent_id(body)
    row = AgentChatMessage(
        agent_id=agent_id,
        role="user",
        content=msg,
    )
    session.add(row)
    await session.flush()
    return {"ok": True, "id": str(row.id)}
