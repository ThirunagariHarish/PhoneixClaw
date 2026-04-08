"""Chat Responder — spawns a one-shot Claude Code SDK session per message.

Per the architectural rule that "anything background should be a Claude agent,
not Python code," this module does NOT use the raw anthropic SDK. Instead it
spawns a full Claude Code session in a per-message workdir that contains:
    - agent_context.json  — the agent's manifest, character, rules
    - recent_trades.json  — last 7 days of closed trades
    - chat_history.json   — the last 12 chat turns
    - reply_chat.py       — a tiny helper the Claude session calls to persist
                            its reply to agent_chat_messages via the API

The agent's reply appears in chat within ~10-15 seconds (cold SDK spawn). The
frontend chat tab polls every few seconds and picks it up automatically.
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


async def respond_to_chat(agent_id: uuid.UUID, user_message: str) -> str | None:
    """Fire-and-forget: spawn a Claude Code session that writes the reply."""
    try:
        ctx = await _load_context(agent_id)
        if not ctx.get("agent"):
            logger.debug("[chat_responder] agent %s not found", agent_id)
            return None

        agent_status: str = (ctx.get("agent") or {}).get("status", "")
        is_live = agent_status in _LIVE_AGENT_STATUSES
        rh_creds: dict = ctx.get("_rh_creds") or {}
        has_rh_creds = bool(rh_creds.get("username") and rh_creds.get("password"))

        # ── Phase 1: Fetch live portfolio context for live agents ────────────
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
                logger.warning(
                    "[chat_responder] live portfolio fetch failed for %s: %s",
                    agent_id,
                    fetch_exc,
                )
                from apps.api.src.services.robinhood_context_fetcher import (  # noqa: PLC0415
                    _sanitize_error,
                )

                live_portfolio_dict = {
                    "positions": [],
                    "account_value": None,
                    "buying_power": None,
                    "cash": None,
                    "last_updated_at": datetime.now(timezone.utc).isoformat(),
                    "error": _sanitize_error(fetch_exc),
                }

        # ── Phase 2: Only pass rh_creds to workdir when live + have creds ───
        workdir_rh_creds = rh_creds if (is_live and has_rh_creds) else None

        work_dir = _prepare_workdir(
            agent_id,
            ctx,
            user_message,
            live_portfolio=live_portfolio_dict,
            rh_creds=workdir_rh_creds,
        )

        try:
            # -------------------------------------------------------------------
            # Smart Context injection (opt-in via ENABLE_SMART_CONTEXT=true)
            # Falls back gracefully — never blocks existing chat path.
            # -------------------------------------------------------------------
            smart_context_str = ""
            if ENABLE_SMART_CONTEXT:
                try:
                    from shared.db.engine import get_session  # noqa: PLC0415

                    async for sess in get_session():
                        token_budget = int(
                            (ctx.get("agent") or {}).get("manifest", {}).get("wiki_context_token_budget", 8000)
                            if isinstance((ctx.get("agent") or {}).get("manifest"), dict)
                            else 8000
                        )
                        builder = ContextBuilderService(sess)
                        context_payload = await builder.build(
                            agent_id=agent_id,
                            session_type="chat",
                            signal=None,
                            token_budget=token_budget,
                        )
                        smart_context_str = context_payload.to_context_string()
                        asyncio.create_task(builder.save_audit(context_payload))
                        break
                except Exception as exc:
                    logger.warning("[chat_responder] smart context builder failed, falling back: %s", exc)
                    smart_context_str = ""

            try:
                from claude_agent_sdk import ClaudeAgentOptions, query
            except ImportError as exc:
                logger.error("[chat_responder] claude_agent_sdk unavailable: %s", exc)
                await _write_fallback_reply(
                    agent_id,
                    f"(Responder offline — claude_agent_sdk not available: {exc})",
                )
                return None

            has_mcp = is_live and has_rh_creds and _ROBINHOOD_MCP_SOURCE.exists()
            if is_live and has_rh_creds and not _ROBINHOOD_MCP_SOURCE.exists():
                logger.warning(
                    "[chat_responder] robinhood_mcp.py not found at %s — chat MCP disabled for agent %s",
                    _ROBINHOOD_MCP_SOURCE,
                    agent_id,
                )
            prompt = _build_prompt(
                ctx,
                user_message,
                smart_context_str=smart_context_str,
                has_live_portfolio=live_portfolio_dict is not None,
                has_mcp_tools=has_mcp,
            )

            # Environment variables the reply_chat.py tool will read
            env_patch = {
                "PHOENIX_API_URL": os.environ.get("PHOENIX_API_URL", "http://localhost:8011"),
                "PHOENIX_API_KEY": os.environ.get("PHOENIX_API_KEY", ""),
                "PHOENIX_TARGET_AGENT_ID": str(agent_id),
            }
            for k, v in env_patch.items():
                os.environ[k] = v  # inherited by the spawned claude subprocess

            # Live agents get read-only Robinhood MCP tools; others get base set
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
                    # We don't need to inspect messages — the session writes back
                    # to agent_chat_messages via the reply_chat.py tool
                    pass

            try:
                await asyncio.wait_for(_pump(), timeout=REPLY_TIMEOUT_SECONDS)
                logger.info("[chat_responder] session completed for %s", agent_id)
            except asyncio.TimeoutError:
                logger.warning("[chat_responder] session timed out for %s", agent_id)
                await _write_fallback_reply(
                    agent_id,
                    "(Sorry — the reply took too long. Try again in a moment.)",
                )
            return None
        finally:
            # Always scrub the workdir — it may contain .claude/settings.json
            # with plaintext credentials.  ignore_errors=True ensures a cleanup
            # failure can never break the caller.
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass  # never let cleanup failure break the response
    except Exception as exc:
        logger.exception("[chat_responder] crashed: %s", exc)
        try:
            await _write_fallback_reply(
                agent_id,
                f"(Responder crashed: {str(exc)[:150]})",
            )
        except Exception:
            pass
        return None


async def _write_fallback_reply(agent_id: uuid.UUID, text: str) -> None:
    """Write a plain reply directly to the DB when the Claude session is unusable."""
    from shared.db.engine import get_session
    from shared.db.models.agent_chat import AgentChatMessage

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
    """Synchronous fire-and-forget — safe to call from FastAPI route handlers."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(respond_to_chat(agent_id, user_message))
    except RuntimeError:
        asyncio.run(respond_to_chat(agent_id, user_message))
