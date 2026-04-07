"""Chat Responder — one-shot Claude Haiku calls that produce agent chat replies.

When a user types into the agent chat, we don't try to wake the long-running
Claude Code session (it's not designed to re-enter). Instead we fire a tiny
Haiku call that:
    1. Loads the agent's manifest (character, rules, recent trades, positions)
    2. Builds a short prompt with the last N chat turns
    3. Gets a plain-text reply from Haiku
    4. Writes the reply back to `agent_chat_messages` with role='agent'

Cheap: ~1-2k input + 200 output tokens per reply, ~$0.0005 each.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, desc

logger = logging.getLogger(__name__)

RESPONDER_MODEL = os.environ.get("CHAT_RESPONDER_MODEL", "claude-haiku-4-5-20251001")
RECENT_TURN_LIMIT = 12


async def _load_context(agent_id: uuid.UUID) -> dict:
    """Fetch the agent, its last trades, positions, and chat history."""
    from shared.db.engine import get_session
    from shared.db.models.agent import Agent
    from shared.db.models.agent_chat import AgentChatMessage

    ctx: dict = {"agent": None, "chat": [], "trades": []}
    async for sess in get_session():
        # Agent row
        res = await sess.execute(select(Agent).where(Agent.id == agent_id))
        agent = res.scalar_one_or_none()
        if not agent:
            return ctx
        ctx["agent"] = {
            "name": agent.name,
            "type": agent.type,
            "status": agent.status,
            "character": (agent.manifest or {}).get("identity", {}).get("character", ""),
            "rules": (agent.manifest or {}).get("rules", {}),
            "win_rate": agent.win_rate,
            "total_trades": agent.total_trades,
            "daily_pnl": agent.daily_pnl,
            "total_pnl": agent.total_pnl,
        }

        # Recent chat turns
        res = await sess.execute(
            select(AgentChatMessage)
            .where(AgentChatMessage.agent_id == agent_id)
            .order_by(desc(AgentChatMessage.created_at))
            .limit(RECENT_TURN_LIMIT)
        )
        rows = list(res.scalars().all())
        rows.reverse()
        ctx["chat"] = [
            {"role": m.role, "content": m.content[:500]} for m in rows
        ]

        # Recent trades (best effort, table may not exist)
        try:
            from shared.db.models.agent_trade import AgentTrade
            since = datetime.now(timezone.utc) - timedelta(days=7)
            res = await sess.execute(
                select(AgentTrade)
                .where(AgentTrade.agent_id == agent_id, AgentTrade.created_at >= since)
                .order_by(desc(AgentTrade.created_at))
                .limit(8)
            )
            ctx["trades"] = [
                {
                    "symbol": t.symbol,
                    "side": getattr(t, "side", None),
                    "pnl": float(getattr(t, "pnl_dollar", 0) or 0),
                    "at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in res.scalars().all()
            ]
        except Exception:
            pass
        break
    return ctx


def _build_prompt(ctx: dict, user_message: str) -> str:
    agent = ctx.get("agent") or {}
    chat = ctx.get("chat") or []
    trades = ctx.get("trades") or []

    chat_lines = "\n".join(
        f"{'User' if m['role'] == 'user' else agent.get('name', 'Agent')}: {m['content']}"
        for m in chat[-RECENT_TURN_LIMIT:]
    )
    trades_lines = "\n".join(
        f"- {t['symbol']} {t.get('side', '')}: ${t.get('pnl', 0):+.2f} at {t.get('at', '')}"
        for t in trades
    ) or "(no recent trades)"

    return f"""You are {agent.get('name', 'a Phoenix trading agent')}. Reply in character.

## Your profile
- Character: {agent.get('character', 'unknown')}
- Status: {agent.get('status', 'unknown')}
- Win rate: {(agent.get('win_rate') or 0) * 100:.1f}%
- Total trades: {agent.get('total_trades', 0)}
- Total PnL: ${agent.get('total_pnl', 0):.2f}
- Today PnL: ${agent.get('daily_pnl', 0):.2f}

## Recent trades (last 7 days)
{trades_lines}

## Recent chat
{chat_lines}

## New user message
{user_message}

Reply in 1-3 short sentences. Plain text only, no markdown headers. Be direct and trader-friendly."""


async def _call_haiku(prompt: str) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        # Use the async client so we don't block the event loop
        client = anthropic.AsyncAnthropic(api_key=key)
        resp = await client.messages.create(
            model=RESPONDER_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.content and hasattr(resp.content[0], "text"):
            return resp.content[0].text.strip()
    except Exception as exc:
        logger.warning("[chat_responder] Haiku call failed: %s", exc)
    return None


async def respond_to_chat(agent_id: uuid.UUID, user_message: str) -> str | None:
    """Fire-and-forget responder. Writes the reply to agent_chat_messages."""
    try:
        ctx = await _load_context(agent_id)
        if not ctx.get("agent"):
            logger.debug("[chat_responder] agent %s not found", agent_id)
            return None

        prompt = _build_prompt(ctx, user_message)
        reply = await _call_haiku(prompt)
        if not reply:
            reply = (
                f"(I'm {ctx['agent'].get('name','the agent')} — I'm running but "
                "my responder is offline. Your message has been logged.)"
            )

        from shared.db.engine import get_session
        from shared.db.models.agent_chat import AgentChatMessage

        async for sess in get_session():
            row = AgentChatMessage(
                id=uuid.uuid4(),
                agent_id=agent_id,
                role="agent",
                content=reply,
                message_type="text",
                extra_data={"model": RESPONDER_MODEL},
            )
            sess.add(row)
            await sess.commit()
            break
        logger.info("[chat_responder] replied to %s (%d chars)", agent_id, len(reply))
        return reply
    except Exception as exc:
        logger.exception("[chat_responder] crashed: %s", exc)
        return None


def schedule_reply(agent_id: uuid.UUID, user_message: str) -> None:
    """Synchronous fire-and-forget — safe to call from FastAPI route handlers."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(respond_to_chat(agent_id, user_message))
    except RuntimeError:
        # No running loop (shouldn't happen in FastAPI but be safe)
        asyncio.run(respond_to_chat(agent_id, user_message))
