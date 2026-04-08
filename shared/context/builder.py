"""Smart Context Builder — priority-tiered, token-budgeted context assembly.

Replaces static context loading with dynamic, relevance-ranked context injection.
Respects WIKI_CONTEXT_TOKEN_BUDGET (default 8000 tokens).
Enabled only when ENABLE_SMART_CONTEXT=true.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

logger = logging.getLogger(__name__)

ENABLE_SMART_CONTEXT = os.environ.get("ENABLE_SMART_CONTEXT", "false").lower() == "true"
DEFAULT_TOKEN_BUDGET = int(os.environ.get("WIKI_CONTEXT_TOKEN_BUDGET", "8000"))

# Approximate token counts for budget estimation.
# Real tokenization is expensive; we use character-based approximation:
# ~4 characters per token (Claude tokenizer approximation).
CHARS_PER_TOKEN = 4

TIER_BUDGETS: dict[str, int] = {
    "signal": 500,  # Tier 1: always included
    "wiki": 2000,  # Tier 2: relevant wiki entries
    "similar_trades": 1500,  # Tier 3: past winning trades
    "manifest": 1500,  # Tier 4: manifest sections
    "recent_trades": 1500,  # Tier 5: last 5 days
    "chat_history": 1000,  # Tier 6: last 8 turns
}


@dataclass
class ContextTier:
    name: str
    content: str
    tokens_estimated: int
    items_count: int
    metadata: dict = field(default_factory=dict)


@dataclass
class ContextPayload:
    agent_id: str
    session_type: str
    signal_symbol: str | None
    token_budget: int
    tiers: list[ContextTier] = field(default_factory=list)
    total_tokens_estimated: int = 0
    wiki_entries_injected: int = 0
    trades_injected: int = 0
    manifest_sections_injected: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    built_at: str = ""

    def to_context_string(self) -> str:
        """Render all tiers into a single context string for LLM injection."""
        parts = []
        for tier in self.tiers:
            if tier.content:
                parts.append(tier.content)
        return "\n\n".join(parts)

    def to_audit_dict(self) -> dict:
        """Convert to dict for context_sessions DB record."""
        return {
            "agent_id": self.agent_id,
            "session_type": self.session_type,
            "signal_symbol": self.signal_symbol,
            "token_budget": self.token_budget,
            "tokens_used": self.total_tokens_estimated,
            "wiki_entries_injected": self.wiki_entries_injected,
            "trades_injected": self.trades_injected,
            "manifest_sections_injected": self.manifest_sections_injected,
            "quality_score": self.quality_score,
            "built_at": self.built_at,
        }


class ContextBuilderService:
    """Priority-tiered, token-budgeted context assembly service.

    Usage::

        builder = ContextBuilderService(session)
        payload = await builder.build(
            agent_id=agent_id,
            session_type="chat",
            signal={"symbol": "AAPL", "direction": "LONG"},
            token_budget=8000,
        )
        context_str = payload.to_context_string()
    """

    def __init__(self, session) -> None:  # AsyncSession
        self.session = session

    async def build(
        self,
        agent_id: UUID,
        session_type: str = "chat",
        signal: dict | None = None,
        token_budget: int | None = None,
        requesting_user_id: UUID | None = None,
    ) -> ContextPayload:
        """Build context payload with priority tiers.

        Returns :class:`ContextPayload` even when ``ENABLE_SMART_CONTEXT`` is
        ``False`` — in that case an *empty* payload is returned and the caller
        must handle the fallback path.
        """
        if not ENABLE_SMART_CONTEXT:
            return ContextPayload(
                agent_id=str(agent_id),
                session_type=session_type,
                signal_symbol=signal.get("symbol") if signal else None,
                token_budget=token_budget or DEFAULT_TOKEN_BUDGET,
                built_at=datetime.now(timezone.utc).isoformat(),
            )

        budget = token_budget or DEFAULT_TOKEN_BUDGET
        symbol = signal.get("symbol") if signal else None

        payload = ContextPayload(
            agent_id=str(agent_id),
            session_type=session_type,
            signal_symbol=symbol,
            token_budget=budget,
            built_at=datetime.now(timezone.utc).isoformat(),
        )

        remaining_budget = budget

        # Tier 1: Signal + task description (always included)
        tier1 = await self._build_signal_tier(signal, session_type)
        payload.tiers.append(tier1)
        remaining_budget -= tier1.tokens_estimated

        # Tier 2: Relevant wiki entries
        if remaining_budget > 0:
            tier2 = await self._build_wiki_tier(
                agent_id,
                symbol,
                session_type,
                budget=min(TIER_BUDGETS["wiki"], remaining_budget),
                requesting_user_id=requesting_user_id,
            )
            payload.tiers.append(tier2)
            remaining_budget -= tier2.tokens_estimated
            payload.wiki_entries_injected = tier2.items_count

        # Tier 3: Similar past winning trades
        if remaining_budget > 0:
            tier3 = await self._build_similar_trades_tier(
                agent_id,
                symbol,
                budget=min(TIER_BUDGETS["similar_trades"], remaining_budget),
            )
            payload.tiers.append(tier3)
            remaining_budget -= tier3.tokens_estimated
            payload.trades_injected += tier3.items_count

        # Tier 4: Relevant manifest sections
        if remaining_budget > 0:
            tier4 = await self._build_manifest_tier(
                agent_id,
                budget=min(TIER_BUDGETS["manifest"], remaining_budget),
            )
            payload.tiers.append(tier4)
            remaining_budget -= tier4.tokens_estimated
            payload.manifest_sections_injected = tier4.metadata.get("sections", [])

        # Tier 5: Recent trades (last 5 days)
        if remaining_budget > 0:
            tier5 = await self._build_recent_trades_tier(
                agent_id,
                budget=min(TIER_BUDGETS["recent_trades"], remaining_budget),
            )
            payload.tiers.append(tier5)
            remaining_budget -= tier5.tokens_estimated
            payload.trades_injected += tier5.items_count

        # Tier 6: Chat history (last 8 turns)
        if remaining_budget > 0:
            tier6 = await self._build_chat_history_tier(
                agent_id,
                budget=min(TIER_BUDGETS["chat_history"], remaining_budget),
            )
            payload.tiers.append(tier6)
            remaining_budget -= tier6.tokens_estimated

        payload.total_tokens_estimated = budget - remaining_budget
        payload.quality_score = (
            payload.wiki_entries_injected / max(payload.token_budget / 2000, 1)
            if payload.wiki_entries_injected > 0
            else 0.0
        )

        return payload

    async def _build_signal_tier(self, signal: dict | None, session_type: str) -> ContextTier:
        if not signal:
            content = f"Session type: {session_type}"
        else:
            content = (
                f"Current Signal:\n"
                f"- Symbol: {signal.get('symbol', 'N/A')}\n"
                f"- Direction: {signal.get('direction', 'N/A')}\n"
                f"- Session: {session_type}"
            )
        return ContextTier(
            name="signal",
            content=content,
            tokens_estimated=self._estimate_tokens(content),
            items_count=1,
        )

    async def _build_wiki_tier(
        self,
        agent_id: UUID,
        symbol: str | None,
        session_type: str,
        budget: int,
        requesting_user_id: UUID | None = None,
    ) -> ContextTier:
        """Query wiki for relevant entries. Uses WikiRepository."""
        try:
            from apps.api.src.repositories.wiki_repo import WikiRepository  # noqa: PLC0415

            wiki_repo = WikiRepository(self.session)

            query_text = symbol or session_type
            entries = await wiki_repo.query_entries(
                agent_id=agent_id,
                query_text=query_text,
                top_k=10,
                include_shared=True,
                requesting_user_id=requesting_user_id,
            )

            formatted = []
            total_chars = 0
            max_chars = budget * CHARS_PER_TOKEN

            for entry in entries:
                entry_text = (
                    f"[{entry.category}] {entry.title}"
                    f" (confidence: {entry.confidence_score:.2f})\n{entry.content}\n"
                )
                if total_chars + len(entry_text) > max_chars:
                    break
                formatted.append(entry_text)
                total_chars += len(entry_text)

            content = "## Relevant Knowledge:\n" + "\n---\n".join(formatted) if formatted else ""
            return ContextTier(
                name="wiki",
                content=content,
                tokens_estimated=self._estimate_tokens(content),
                items_count=len(formatted),
                metadata={"entry_ids": [str(e.id) for e in entries[: len(formatted)]]},
            )
        except Exception as exc:
            logger.warning("Wiki tier failed: %s", exc)
            return ContextTier(name="wiki", content="", tokens_estimated=0, items_count=0)

    async def _build_similar_trades_tier(
        self, agent_id: UUID, symbol: str | None, budget: int
    ) -> ContextTier:
        """Query recent profitable trades for the same symbol."""
        try:
            from sqlalchemy import desc, select  # noqa: PLC0415

            from shared.db.models.agent_trade import AgentTrade  # noqa: PLC0415

            stmt = (
                select(AgentTrade)
                .where(
                    AgentTrade.agent_id == agent_id,
                    AgentTrade.pnl_dollar > 0,  # profitable only
                )
                .order_by(desc(AgentTrade.pnl_dollar))
                .limit(5)
            )

            if symbol:
                stmt = stmt.where(AgentTrade.ticker == symbol)

            result = await self.session.execute(stmt)
            trades = list(result.scalars().all())

            if not trades:
                return ContextTier(name="similar_trades", content="", tokens_estimated=0, items_count=0)

            formatted = []
            total_chars = 0
            max_chars = budget * CHARS_PER_TOKEN

            for t in trades:
                trade_text = (
                    f"Trade: {t.ticker} {t.side} | PnL: ${t.pnl_dollar:.2f}"
                    f" | Entry: {t.entry_price}\n"
                )
                if total_chars + len(trade_text) > max_chars:
                    break
                formatted.append(trade_text)
                total_chars += len(trade_text)

            content = "## Similar Winning Trades:\n" + "".join(formatted)
            return ContextTier(
                name="similar_trades",
                content=content,
                tokens_estimated=self._estimate_tokens(content),
                items_count=len(formatted),
            )
        except Exception as exc:
            logger.warning("Similar trades tier failed: %s", exc)
            return ContextTier(name="similar_trades", content="", tokens_estimated=0, items_count=0)

    async def _build_manifest_tier(self, agent_id: UUID, budget: int) -> ContextTier:
        """Extract relevant manifest sections (identity, risk, modes, rules)."""
        try:
            import sqlalchemy  # noqa: PLC0415

            from shared.db.models.agent import Agent  # noqa: PLC0415

            result = await self.session.execute(
                sqlalchemy.select(Agent).where(Agent.id == agent_id)
            )
            agent = result.scalar_one_or_none()
            if not agent or not agent.manifest:
                return ContextTier(name="manifest", content="", tokens_estimated=0, items_count=0)

            manifest = agent.manifest
            sections: list[str] = []
            content_parts: list[str] = []
            max_chars = budget * CHARS_PER_TOKEN
            total_chars = 0

            # Priority sections — exclude 'knowledge' blob (replaced by wiki tier)
            for section_key in ["identity", "risk", "modes", "rules"]:
                if section_key in manifest:
                    section_text = f"## Agent {section_key.title()}:\n{str(manifest[section_key])[:500]}\n"
                    if total_chars + len(section_text) <= max_chars:
                        content_parts.append(section_text)
                        sections.append(section_key)
                        total_chars += len(section_text)

            content = "\n".join(content_parts)
            return ContextTier(
                name="manifest",
                content=content,
                tokens_estimated=self._estimate_tokens(content),
                items_count=len(sections),
                metadata={"sections": sections},
            )
        except Exception as exc:
            logger.warning("Manifest tier failed: %s", exc)
            return ContextTier(name="manifest", content="", tokens_estimated=0, items_count=0)

    async def _build_recent_trades_tier(self, agent_id: UUID, budget: int) -> ContextTier:
        """Last 5 days of trades."""
        try:
            from sqlalchemy import desc, select  # noqa: PLC0415

            from shared.db.models.agent_trade import AgentTrade  # noqa: PLC0415

            since = datetime.now(timezone.utc) - timedelta(days=5)
            stmt = (
                select(AgentTrade)
                .where(
                    AgentTrade.agent_id == agent_id,
                    AgentTrade.created_at >= since,
                )
                .order_by(desc(AgentTrade.created_at))
                .limit(20)
            )

            result = await self.session.execute(stmt)
            trades = list(result.scalars().all())

            if not trades:
                return ContextTier(name="recent_trades", content="", tokens_estimated=0, items_count=0)

            formatted = []
            total_chars = 0
            max_chars = budget * CHARS_PER_TOKEN

            for t in trades:
                pnl_str = f"${t.pnl_dollar:.2f}" if t.pnl_dollar is not None else "open"
                trade_text = f"{t.ticker}: PnL={pnl_str}\n"
                if total_chars + len(trade_text) > max_chars:
                    break
                formatted.append(trade_text)
                total_chars += len(trade_text)

            content = "## Recent Trades (last 5 days):\n" + "".join(formatted)
            return ContextTier(
                name="recent_trades",
                content=content,
                tokens_estimated=self._estimate_tokens(content),
                items_count=len(formatted),
            )
        except Exception as exc:
            logger.warning("Recent trades tier failed: %s", exc)
            return ContextTier(name="recent_trades", content="", tokens_estimated=0, items_count=0)

    async def _build_chat_history_tier(self, agent_id: UUID, budget: int) -> ContextTier:
        """Last 8 chat turns (16 messages: user + assistant)."""
        try:
            from sqlalchemy import desc, select  # noqa: PLC0415

            from shared.db.models.agent_chat import AgentChatMessage  # noqa: PLC0415

            stmt = (
                select(AgentChatMessage)
                .where(AgentChatMessage.agent_id == agent_id)
                .order_by(desc(AgentChatMessage.created_at))
                .limit(16)
            )

            result = await self.session.execute(stmt)
            messages = list(result.scalars().all())
            messages.reverse()  # chronological order

            if not messages:
                return ContextTier(name="chat_history", content="", tokens_estimated=0, items_count=0)

            formatted = []
            total_chars = 0
            max_chars = budget * CHARS_PER_TOKEN

            for msg in messages:
                role = getattr(msg, "role", "unknown")
                content_preview = str(getattr(msg, "content", ""))[:200]
                msg_text = f"{role}: {content_preview}\n"
                if total_chars + len(msg_text) > max_chars:
                    break
                formatted.append(msg_text)
                total_chars += len(msg_text)

            content = "## Recent Chat:\n" + "".join(formatted)
            return ContextTier(
                name="chat_history",
                content=content,
                tokens_estimated=self._estimate_tokens(content),
                items_count=len(formatted),
            )
        except Exception as exc:
            logger.warning("Chat history tier failed: %s", exc)
            return ContextTier(name="chat_history", content="", tokens_estimated=0, items_count=0)

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count: ~4 chars per token."""
        return max(1, len(text) // CHARS_PER_TOKEN)

    async def save_audit(self, payload: ContextPayload) -> None:
        """Save context session to DB for audit/quality tracking (best-effort)."""
        try:
            from shared.db.models.context_session import ContextSession  # noqa: PLC0415

            record = ContextSession(
                agent_id=UUID(payload.agent_id),
                session_type=payload.session_type,
                signal_symbol=payload.signal_symbol,
                token_budget=payload.token_budget,
                tokens_used=payload.total_tokens_estimated,
                wiki_entries_injected=payload.wiki_entries_injected,
                trades_injected=payload.trades_injected,
                manifest_sections_injected=payload.manifest_sections_injected,
                quality_score=payload.quality_score,
            )
            self.session.add(record)
            await self.session.commit()
        except Exception as exc:
            logger.warning("Failed to save context audit: %s", exc)
