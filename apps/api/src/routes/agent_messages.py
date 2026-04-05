"""
Agent Messages API — inter-agent communication log and messaging.

Reference: PRD Section 8 (Agent Communication), ArchitecturePlan §6.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.agent_message import AgentMessage

router = APIRouter(prefix="/api/v2/agent-messages", tags=["agent-messages"])


class MessageCreate(BaseModel):
    from_agent_id: str
    to_agent_id: str | None = None
    pattern: str = Field(default="request-response", pattern="^(request-response|broadcast|pub-sub|chain|consensus)$")
    intent: str = Field(..., min_length=1, max_length=100)
    data: dict = Field(default_factory=dict)
    topic: str | None = None
    body: str | None = None


class MessageResponse(BaseModel):
    id: str
    from_agent_id: str
    to_agent_id: str | None
    pattern: str
    intent: str
    data: dict
    topic: str | None
    body: str | None
    status: str
    created_at: str


def _to_response(m: AgentMessage) -> dict:
    return {
        "id": str(m.id),
        "from_agent_id": str(m.from_agent_id),
        "to_agent_id": str(m.to_agent_id) if m.to_agent_id else None,
        "pattern": m.pattern,
        "intent": m.intent,
        "data": m.data or {},
        "topic": m.topic,
        "body": m.body,
        "status": m.status,
        "created_at": m.created_at.isoformat() if m.created_at else "",
    }


@router.get("", response_model=list[MessageResponse])
async def list_messages(
    agent_id: str | None = None,
    topic: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List inter-agent messages with optional filters."""
    q = select(AgentMessage).order_by(AgentMessage.created_at.desc())
    if agent_id:
        try:
            aid = uuid.UUID(agent_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent_id")
        q = q.where(
            or_(
                AgentMessage.from_agent_id == aid,
                AgentMessage.to_agent_id == aid,
            )
        )
    if topic:
        q = q.where(AgentMessage.topic == topic)
    q = q.offset(offset).limit(limit)
    result = await session.execute(q)
    rows = result.scalars().all()
    return [_to_response(m) for m in rows]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MessageResponse)
async def send_message(
    payload: MessageCreate,
    session: AsyncSession = Depends(get_session),
):
    """Send an inter-agent message."""
    try:
        from_id = uuid.UUID(payload.from_agent_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid from_agent_id")
    to_id: uuid.UUID | None = None
    if payload.to_agent_id:
        try:
            to_id = uuid.UUID(payload.to_agent_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid to_agent_id")

    row = AgentMessage(
        from_agent_id=from_id,
        to_agent_id=to_id,
        pattern=payload.pattern,
        intent=payload.intent,
        data=payload.data,
        topic=payload.topic,
        body=payload.body,
        status="SENT",
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _to_response(row)


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a specific message by ID."""
    try:
        mid = uuid.UUID(message_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    result = await session.execute(select(AgentMessage).where(AgentMessage.id == mid))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return _to_response(row)
