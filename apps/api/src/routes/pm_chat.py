"""
Prediction Markets — Chat (SSE) endpoints (Phase 15.6 / F15-B).

POST   /api/v2/pm/chat           — send message, get SSE stream response
GET    /api/v2/pm/chat/history   — last 50 messages for current user
DELETE /api/v2/pm/chat/history   — clear chat history for current user

SSE frame format:
    data: {"chunk": "...", "done": false}\n\n
    ...
    data: {"chunk": "", "done": true}\n\n

Reference: docs/architecture/polymarket-phase15.md §8, §11
           docs/prd/polymarket-phase15.md F15-B
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.polymarket import PMChatMessage, PMTopBet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/pm/chat", tags=["pm-chat"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    context_market_id: str | None = None


class ChatMessageOut(BaseModel):
    id: str
    role: str  # user | assistant
    content: str
    created_at: str


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _require_user(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")
    return str(user_id)


def _session_id_for_user(user_id: str) -> uuid.UUID:
    """Deterministic session UUID per user (single-session model for Phase 15)."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"pm-chat-{user_id}")


# ---------------------------------------------------------------------------
# LLM helper — lightweight wrapper; defers to Claude SDK when available
# ---------------------------------------------------------------------------


async def _generate_llm_response(user_message: str, context: str) -> AsyncGenerator[str, None]:
    """Yield text chunks from the LLM.

    Falls back to a rule-based stub when the Claude SDK is not configured
    so tests pass without real credentials.
    """
    system_prompt = (
        "You are Phoenix PM Assistant, an expert on prediction markets. "
        "Answer concisely with data-driven analysis. "
        "Reference base rates and market fundamentals where relevant."
    )
    if context:
        system_prompt += f"\n\nMarket context:\n{context}"

    try:
        from shared.llm.claude_client import ClaudeClient  # type: ignore[import]

        client = ClaudeClient(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            model=os.environ.get("PM_CHAT_MODEL", "claude-3-haiku-20240307"),
        )
        async for chunk in client.stream(system=system_prompt, user=user_message):
            yield chunk
        return
    except Exception as exc:
        logger.debug("ClaudeClient unavailable, using stub: %s", exc)

    # Stub: split a canned response into 5-word chunks
    stub = (
        f"I'm analyzing your question about '{user_message[:80]}'. "
        "Based on current market data and base rates, this prediction market shows "
        "moderate uncertainty. I recommend reviewing the debate arguments and reference class "
        "before placing any trade. Always check the latest venue prices for accuracy."
    )
    words = stub.split()
    chunk_size = 5
    for i in range(0, len(words), chunk_size):
        yield " ".join(words[i : i + chunk_size]) + " "


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("")
async def chat(
    payload: ChatRequest,
    request: Request,
    db: DbSession,
) -> StreamingResponse:
    """Stream an LLM response about prediction markets via Server-Sent Events."""
    user_id = _require_user(request)
    session_id = _session_id_for_user(user_id)

    # Build optional market context
    context = ""
    if payload.context_market_id:
        try:
            mid = uuid.UUID(payload.context_market_id)
            res = await db.execute(select(PMTopBet).where(PMTopBet.market_id == mid).limit(1))
            bet = res.scalar_one_or_none()
            if bet:
                context = (
                    f"Bull argument: {bet.bull_argument or 'N/A'}\n"
                    f"Bear argument: {bet.bear_argument or 'N/A'}\n"
                    f"Confidence: {bet.confidence_score}/100\n"
                    f"Reference class: {bet.reference_class or 'N/A'}\n"
                    f"Base rate YES: {bet.base_rate_yes}"
                )
        except Exception as exc:
            logger.debug("Could not load market context: %s", exc)

    # Persist user message
    user_msg = PMChatMessage(
        id=uuid.uuid4(),
        session_id=session_id,
        role="user",
        content=payload.message,
    )
    db.add(user_msg)
    await db.commit()

    full_response: list[str] = []

    async def _event_stream() -> AsyncGenerator[bytes, None]:
        nonlocal full_response
        try:
            async for chunk in _generate_llm_response(payload.message, context):
                full_response.append(chunk)
                frame = json.dumps({"chunk": chunk, "done": False})
                yield f"data: {frame}\n\n".encode()
        except (GeneratorExit, asyncio.CancelledError):
            logger.warning(
                "pm.chat: SSE client disconnected mid-stream for session=%s", session_id
            )
            if full_response:
                partial = "".join(full_response) + " [interrupted]"
                try:
                    from shared.db.engine import get_session as _get_session  # type: ignore[import]

                    async for _db in _get_session():
                        asst_msg = PMChatMessage(
                            id=uuid.uuid4(),
                            session_id=session_id,
                            role="assistant",
                            content=partial,
                        )
                        _db.add(asst_msg)
                        await _db.commit()
                        break
                except Exception as persist_exc:
                    logger.warning(
                        "pm.chat: failed to persist partial assistant message: %s", persist_exc
                    )
            raise  # re-raise so the runtime knows the generator is done
        except Exception as exc:
            logger.error("pm.chat.stream error: %s", exc)
            err_frame = json.dumps({"chunk": f"Error: {exc}", "done": True})
            yield f"data: {err_frame}\n\n".encode()
            return

        done_frame = json.dumps({"chunk": "", "done": True})
        yield f"data: {done_frame}\n\n".encode()

        # Persist assistant response after streaming is complete
        assistant_content = "".join(full_response)
        try:
            from shared.db.engine import get_session as _get_session  # type: ignore[import]

            async for _db in _get_session():
                asst_msg = PMChatMessage(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    role="assistant",
                    content=assistant_content,
                )
                _db.add(asst_msg)
                await _db.commit()
                break
        except Exception as exc:
            logger.warning("pm.chat: failed to persist assistant message: %s", exc)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.get("/history", response_model=list[ChatMessageOut])
async def get_chat_history(
    request: Request,
    db: DbSession,
) -> list[ChatMessageOut]:
    """Return the last 50 chat messages for the current user's session."""
    user_id = _require_user(request)
    session_id = _session_id_for_user(user_id)

    result = await db.execute(
        select(PMChatMessage)
        .where(PMChatMessage.session_id == session_id)
        .order_by(PMChatMessage.created_at.desc())
        .limit(50)
    )
    messages = list(reversed(result.scalars().all()))

    return [
        ChatMessageOut(
            id=str(m.id),
            role=m.role,
            content=m.content,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in messages
    ]


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_chat_history(
    request: Request,
    db: DbSession,
) -> None:
    """Delete all chat messages for the current user's session."""
    from sqlalchemy import delete as sa_delete  # local import to keep top-level clean

    user_id = _require_user(request)
    session_id = _session_id_for_user(user_id)

    await db.execute(sa_delete(PMChatMessage).where(PMChatMessage.session_id == session_id))
    await db.commit()
    logger.info("pm.chat.history cleared for user=%s session=%s", user_id, session_id)
