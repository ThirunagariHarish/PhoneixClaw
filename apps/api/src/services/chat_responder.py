"""Chat Responder — answers agent chat messages using Anthropic Messages API.

Primary path: direct anthropic SDK call (~2s latency, no CLI dependency).
Optional enhancement: Claude Code SDK session with MCP tools for live agents
that need real-time Robinhood data (falls back to primary on any failure).

The agent's reply is written directly to agent_chat_messages. The frontend
chat tab polls every few seconds and picks it up automatically.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import desc, select

from shared.context.builder import ENABLE_SMART_CONTEXT, ContextBuilderService

# Resolve repo root so we can copy the robinhood MCP tool into chat workdirs
_REPO_ROOT = Path(__file__).resolve().parents[4]
_ROBINHOOD_MCP_SOURCE = (
    _REPO_ROOT / "agents" / "templates" / "live-trader-v1" / "tools" / "robinhood_mcp.py"
)

# Agent statuses that qualify for live portfolio context injection + MCP access
_LIVE_AGENT_STATUSES: frozenset[str] = frozenset({"RUNNING", "APPROVED"})

# Read-only Robinhood MCP tools exposed in chat (no order-placement tools)
_ROBINHOOD_CHAT_TOOLS: list[str] = [
    "mcp__robinhood__robinhood_login",
    "mcp__robinhood__get_positions",
    "mcp__robinhood__get_account",
    "mcp__robinhood__get_quote",
    "mcp__robinhood__get_account_snapshot",
    "mcp__robinhood__get_nbbo",
    "mcp__robinhood__get_watchlist",
    "mcp__robinhood__get_order_status",
]

logger = logging.getLogger(__name__)

# Where per-message workdirs live
CHAT_SESSIONS_DIR = Path(
    os.environ.get("PHOENIX_CHAT_SESSIONS_DIR", "/app/data/chat-sessions")
)
RECENT_TURN_LIMIT = 12
REPLY_TIMEOUT_SECONDS = int(os.environ.get("CHAT_REPLY_TIMEOUT_SECONDS", "120"))


REPLY_TOOL_TEMPLATE = '''"""Writer tool — the Claude session calls this to persist its reply."""
import argparse
import os
import sys

import httpx


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    args = p.parse_args()

    base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
    key = os.environ.get("PHOENIX_API_KEY", "")
    agent_id = os.environ.get("PHOENIX_TARGET_AGENT_ID", "")
    if not agent_id:
        print("[reply_chat] PHOENIX_TARGET_AGENT_ID not set", file=sys.stderr)
        sys.exit(1)

    try:
        r = httpx.post(
            f"{base}/api/v2/chat/agent-reply",
            headers={"X-Agent-Key": key, "Content-Type": "application/json"},
            json={"agent_id": agent_id, "content": args.text},
            timeout=15,
        )
        if r.status_code in (200, 201):
            print(f"[reply_chat] posted reply ({len(args.text)} chars)")
        else:
            print(f"[reply_chat] post returned {r.status_code}: {r.text[:200]}",
                  file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"[reply_chat] post failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
'''


async def _load_context(agent_id: uuid.UUID) -> dict:
    """Fetch the agent, its last trades, and chat history."""
    from shared.db.engine import get_session
    from shared.db.models.agent import Agent
    from shared.db.models.agent_chat import AgentChatMessage

    ctx: dict = {"agent": None, "chat": [], "trades": []}
    async for sess in get_session():
        res = await sess.execute(select(Agent).where(Agent.id == agent_id))
        agent = res.scalar_one_or_none()
        if not agent:
            return ctx
        ctx["agent"] = {
            "id": str(agent.id),
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
        # Private key — credentials for MCP wiring; never written to disk
        ctx["_rh_creds"] = (agent.config or {}).get("robinhood_credentials") or {}

        res = await sess.execute(
            select(AgentChatMessage)
            .where(AgentChatMessage.agent_id == agent_id)
            .order_by(desc(AgentChatMessage.created_at))
            .limit(RECENT_TURN_LIMIT)
        )
        rows = list(res.scalars().all())
        rows.reverse()
        ctx["chat"] = [{"role": m.role, "content": m.content[:500]} for m in rows]

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


def _prepare_workdir(
    agent_id: uuid.UUID,
    ctx: dict,
    user_message: str,
    live_portfolio: dict | None = None,
    rh_creds: dict | None = None,
) -> Path:
    """Create a per-message workdir with context files + the reply tool.

    For live agents, ``live_portfolio`` is merged into agent_context.json and
    ``.claude/settings.json`` is written with the Robinhood MCP server wired in.
    ``robinhood_mcp.py`` is also copied into ``tools/`` so the MCP server can start.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    work_dir = CHAT_SESSIONS_DIR / str(agent_id) / stamp
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "tools").mkdir(exist_ok=True)

    # Build agent_context dict; merge live_portfolio when available
    agent_ctx: dict = dict(ctx.get("agent") or {})
    if live_portfolio is not None:
        agent_ctx["live_portfolio"] = live_portfolio

    (work_dir / "agent_context.json").write_text(
        json.dumps(agent_ctx, indent=2, default=str)
    )
    (work_dir / "chat_history.json").write_text(
        json.dumps(ctx.get("chat") or [], indent=2, default=str)
    )
    (work_dir / "recent_trades.json").write_text(
        json.dumps(ctx.get("trades") or [], indent=2, default=str)
    )
    (work_dir / "user_message.txt").write_text(user_message)
    (work_dir / "tools" / "reply_chat.py").write_text(REPLY_TOOL_TEMPLATE)

    # Phase 2 — wire up Robinhood MCP for live agents
    if rh_creds and rh_creds.get("username") and rh_creds.get("password"):
        try:
            from apps.api.src.services.agent_gateway import _write_claude_settings  # noqa: PLC0415

            _write_claude_settings(work_dir, rh_creds, paper_mode=False)
        except Exception as mcp_exc:
            logger.warning("[chat_responder] failed to write MCP settings: %s", mcp_exc)

        # Copy robinhood_mcp.py from the live-trader template
        if _ROBINHOOD_MCP_SOURCE.exists():
            try:
                shutil.copy2(_ROBINHOOD_MCP_SOURCE, work_dir / "tools" / "robinhood_mcp.py")
            except Exception as copy_exc:
                logger.warning("[chat_responder] failed to copy robinhood_mcp.py: %s", copy_exc)

    return work_dir


def _build_prompt(
    ctx: dict,
    user_message: str,
    smart_context_str: str = "",
    has_live_portfolio: bool = False,
    has_mcp_tools: bool = False,
) -> str:
    agent = ctx.get("agent") or {}
    smart_ctx_section = ""
    if smart_context_str:
        smart_ctx_section = f"\n\n## Smart Context (dynamic knowledge injection):\n{smart_context_str}\n"

    live_portfolio_section = ""
    if has_live_portfolio:
        live_portfolio_section = """
## LIVE Portfolio Data
The `agent_context.json` file contains a `"live_portfolio"` key with REAL-TIME data
fetched from Robinhood seconds ago. Use it to answer questions about current positions,
account balance, and buying power. Do NOT say you lack a Robinhood connection.
If `live_portfolio.error` is set, tell the user you tried but got that error — never
claim there is no connection.
"""

    mcp_section = ""
    if has_mcp_tools:
        mcp_section = """
## Robinhood MCP Tools Available
You have live Robinhood MCP tools. Your FIRST action when answering any question about
positions, quotes, or account data must be to call `mcp__robinhood__robinhood_login`
to authenticate, then call the relevant read-only tool. Do NOT place orders via chat.
"""

    return f"""You are {agent.get('name', 'a Phoenix trading agent')} — stay in character.

Your character: {agent.get('character', 'unknown')}
{smart_ctx_section}{live_portfolio_section}{mcp_section}
Read the following files in the current working directory for context:
- `agent_context.json` — your profile, rules, recent win rate and PnL\
{"  (live_portfolio key has REAL-TIME data)" if has_live_portfolio else ""}
- `chat_history.json` — the last 12 turns of conversation with the user
- `recent_trades.json` — your last 7 days of closed trades
- `user_message.txt` — the new message you need to respond to

The user just said: "{user_message}"

Compose a reply in your voice — 1 to 3 short sentences. Plain text, no markdown.
Be direct and trader-friendly. Reference specific trades/positions if relevant.

When you have your reply ready, call:
    python tools/reply_chat.py --text "<your reply here>"

Then exit immediately. Do NOT read files you don't need. This is a one-shot
response — get in, get out."""


async def _fast_anthropic_reply(
    agent_id: uuid.UUID,
    ctx: dict,
    user_message: str,
) -> bool:
    """Direct Anthropic Messages API call — no Claude Code CLI needed.

    Returns True if a reply was successfully written to the DB.
    """
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        logger.error("[chat_responder] anthropic SDK not installed")
        return False

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("[chat_responder] ANTHROPIC_API_KEY not set")
        return False

    agent = ctx.get("agent") or {}
    chat_history = ctx.get("chat") or []
    trades = ctx.get("trades") or []

    system_parts = [
        f"You are {agent.get('name', 'a Phoenix trading agent')}.",
        f"Character: {agent.get('character', 'a professional trader')}.",
        f"Win rate: {agent.get('win_rate', 'N/A')}, Total trades: {agent.get('total_trades', 0)},",
        f"Total P&L: {agent.get('total_pnl', 0)}, Today P&L: {agent.get('daily_pnl', 0)}.",
        "Reply in 1-3 short sentences. Be direct and trader-friendly. Stay in character.",
    ]
    if trades:
        trade_strs = [f"  {t.get('symbol','?')} {t.get('side','?')} pnl=${t.get('pnl',0)}" for t in trades[:5]]
        system_parts.append("Recent trades:\n" + "\n".join(trade_strs))

    system_prompt = "\n".join(system_parts)

    messages: list[dict] = []
    for turn in chat_history[-8:]:
        role = "assistant" if turn.get("role") == "agent" else "user"
        messages.append({"role": role, "content": turn.get("content", "")[:500]})
    messages.append({"role": "user", "content": user_message})

    if len(messages) >= 2 and messages[-1]["role"] == messages[-2]["role"]:
        messages = [messages[-1]]

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            system=system_prompt,
            messages=messages,
        )
        reply_text = resp.content[0].text if resp.content else "(No response generated)"
        await _write_fallback_reply(agent_id, reply_text)
        logger.info("[chat_responder] fast reply written for %s (%d chars)", agent_id, len(reply_text))
        return True
    except Exception as exc:
        logger.error("[chat_responder] anthropic API call failed: %s", exc)
        return False


async def respond_to_chat(agent_id: uuid.UUID, user_message: str) -> str | None:
    """Generate a reply for an agent chat message.

    Strategy:
    1. Try the direct Anthropic SDK (fast, ~2s, no CLI dependency)
    2. If that fails, try Claude Code SDK with MCP tools (for live agents)
    3. If everything fails, write a visible error to the chat
    """
    try:
        ctx = await _load_context(agent_id)
        if not ctx.get("agent"):
            logger.debug("[chat_responder] agent %s not found", agent_id)
            return None

        # ── Primary path: direct Anthropic SDK ────────────────────────────────
        if await _fast_anthropic_reply(agent_id, ctx, user_message):
            return None

        # ── Fallback: Claude Code SDK with MCP tools ──────────────────────────
        logger.warning("[chat_responder] fast reply failed for %s, trying Claude Code SDK", agent_id)

        agent_status: str = (ctx.get("agent") or {}).get("status", "")
        is_live = agent_status in _LIVE_AGENT_STATUSES
        rh_creds: dict = ctx.get("_rh_creds") or {}
        has_rh_creds = bool(rh_creds.get("username") and rh_creds.get("password"))

        live_portfolio_dict: dict | None = None
        if is_live and has_rh_creds:
            try:
                from apps.api.src.services.robinhood_context_fetcher import (  # noqa: PLC0415
                    RobinhoodContextFetcher,
                )
                from shared.db.engine import get_session  # noqa: PLC0415

                async for sess in get_session():
                    fetcher = RobinhoodContextFetcher(sess)
                    portfolio_ctx = await fetcher.fetch(agent_id)
                    live_portfolio_dict = portfolio_ctx.to_dict()
                    break
            except Exception as fetch_exc:
                logger.warning("[chat_responder] live portfolio fetch failed: %s", fetch_exc)

        workdir_rh_creds = rh_creds if (is_live and has_rh_creds) else None
        work_dir = _prepare_workdir(
            agent_id, ctx, user_message,
            live_portfolio=live_portfolio_dict,
            rh_creds=workdir_rh_creds,
        )

        try:
            try:
                from claude_agent_sdk import ClaudeAgentOptions, query  # noqa: PLC0415
            except ImportError as exc:
                logger.error("[chat_responder] claude_agent_sdk unavailable: %s", exc)
                await _write_fallback_reply(
                    agent_id,
                    "(Chat is temporarily unavailable. Please try again in a moment.)",
                )
                return None

            has_mcp = is_live and has_rh_creds and _ROBINHOOD_MCP_SOURCE.exists()
            prompt = _build_prompt(
                ctx, user_message,
                has_live_portfolio=live_portfolio_dict is not None,
                has_mcp_tools=has_mcp,
            )

            env_patch = {
                "PHOENIX_API_URL": os.environ.get("PHOENIX_API_URL", "http://localhost:8011"),
                "PHOENIX_API_KEY": os.environ.get("PHOENIX_API_KEY", ""),
                "PHOENIX_TARGET_AGENT_ID": str(agent_id),
            }
            for k, v in env_patch.items():
                os.environ[k] = v

            allowed_tools: list[str] = ["Bash", "Read"]
            if has_mcp:
                allowed_tools = ["Bash", "Read"] + _ROBINHOOD_CHAT_TOOLS

            options = ClaudeAgentOptions(
                cwd=str(work_dir),
                permission_mode="dontAsk",
                allowed_tools=allowed_tools,
            )

            async def _pump() -> None:
                async for _msg in query(prompt=prompt, options=options):
                    pass

            try:
                await asyncio.wait_for(_pump(), timeout=REPLY_TIMEOUT_SECONDS)
                logger.info("[chat_responder] SDK session completed for %s", agent_id)
            except asyncio.TimeoutError:
                logger.warning("[chat_responder] SDK session timed out for %s", agent_id)
                await _write_fallback_reply(
                    agent_id,
                    "(Sorry — the reply took too long. Try again in a moment.)",
                )
            return None
        finally:
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass
    except Exception as exc:
        logger.exception("[chat_responder] crashed: %s", exc)
        try:
            await _write_fallback_reply(
                agent_id,
                f"(Responder error: {str(exc)[:150]})",
            )
        except Exception:
            pass
        return None


async def _write_fallback_reply(agent_id: uuid.UUID, text: str) -> None:
    """Write a reply directly to the DB."""
    from shared.db.engine import get_session  # noqa: PLC0415
    from shared.db.models.agent_chat import AgentChatMessage  # noqa: PLC0415

    async for sess in get_session():
        row = AgentChatMessage(
            id=uuid.uuid4(),
            agent_id=agent_id,
            role="agent",
            content=text,
            message_type="text",
            extra_data={"fallback": True},
        )
        sess.add(row)
        await sess.commit()
        break


def schedule_reply(agent_id: uuid.UUID, user_message: str) -> None:
    """Fire-and-forget — safe to call from async FastAPI route handlers."""
    asyncio.ensure_future(respond_to_chat(agent_id, user_message))
