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
    """Append a user message and forward it to the agent's running Claude session via send_task."""
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

    # Forward to running agent: trigger-bus (P9) + legacy send_task
    forwarded = None
    if agent_id != _TRADE_CHAT_AGENT_ID:
        try:
            from apps.api.src.services.agent_gateway import gateway
            forwarded = await gateway.send_task(agent_id, msg)
        except Exception as exc:
            forwarded = {"status": "error", "error": str(exc)[:200]}
        # Publish wake trigger — reaches the agent even if send_task failed
        try:
            from shared.triggers import get_bus, Trigger, TriggerType
            await get_bus().publish(Trigger(
                agent_id=str(agent_id),
                type=TriggerType.CHAT_MESSAGE,
                payload={"message": msg, "message_id": str(row.id)},
            ))
        except Exception:
            pass
        # Fire-and-forget: one-shot Haiku responder writes back an agent reply
        try:
            from apps.api.src.services.chat_responder import schedule_reply
            schedule_reply(agent_id, msg)
        except Exception:
            pass

    await session.commit()
    return {"ok": True, "id": str(row.id), "forwarded": forwarded}


@router.post("/agent-reply")
async def post_agent_reply(
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    """Callback used by the chat-responder Claude session's reply_chat.py tool.

    Persists the generated reply as an AgentChatMessage with role='agent'.
    Auth: agent-to-API callback using the agent's PHOENIX_API_KEY (X-Agent-Key).
    """
    agent_id_raw = body.get("agent_id")
    content = body.get("content", "")
    if not agent_id_raw or not content:
        return {"ok": False, "detail": "agent_id and content required"}
    try:
        agent_uuid = uuid.UUID(str(agent_id_raw))
    except (ValueError, TypeError):
        return {"ok": False, "detail": "invalid agent_id"}

    row = AgentChatMessage(
        agent_id=agent_uuid,
        role="agent",
        content=str(content)[:4000],
    )
    session.add(row)
    await session.commit()
    return {"ok": True, "id": str(row.id)}
