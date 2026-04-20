"""
Inter-agent communication protocol — defines message types, envelopes,
and handler methods for each communication pattern.

M2.10: Agent communication protocol.
Reference: ArchitecturePlan §5.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    BROADCAST = "BROADCAST"
    SUBSCRIBE = "SUBSCRIBE"
    CONSENSUS = "CONSENSUS"


class KnowledgeIntent(str, Enum):
    """Standard intents for inter-agent knowledge sharing.

    Used as the `intent` field on AgentMessage for type-safe filtering.
    """
    MARKET_BRIEFING = "market_briefing"
    POSITION_UPDATE = "position_update"
    RISK_ALERT = "risk_alert"
    EXIT_SIGNAL = "exit_signal"
    STRATEGY_INSIGHT = "strategy_insight"
    HEADLINE_ALERT = "headline_alert"
    UNUSUAL_FLOW = "unusual_flow"
    SELL_SIGNAL = "sell_signal"
    MORNING_RESEARCH = "morning_research"
    PATTERN_ALERT = "pattern_alert"
    MARKET_REGIME = "market_regime"


@dataclass
class MessageEnvelope:
    from_agent: str
    to_agent: str | None
    msg_type: MessageType
    intent: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "msg_type": self.msg_type.value,
            "intent": self.intent,
            "data": self.data,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MessageEnvelope":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            from_agent=d["from_agent"],
            to_agent=d.get("to_agent"),
            msg_type=MessageType(d["msg_type"]),
            intent=d["intent"],
            data=d.get("data", {}),
            correlation_id=d.get("correlation_id", ""),
            timestamp=d.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


class ProtocolHandler:
    """Implements the five inter-agent messaging patterns."""

    def __init__(self, agent_id: str, send_fn: Callable[[MessageEnvelope], Awaitable[None]]):
        self._agent_id = agent_id
        self._send = send_fn
        self._pending_responses: dict[str, asyncio.Future[MessageEnvelope]] = {}
        self._subscriptions: dict[str, list[Callable[[MessageEnvelope], Awaitable[None]]]] = {}
        self._consensus_votes: dict[str, list[dict[str, Any]]] = {}

    async def request_response(
        self, target: str, intent: str, data: dict[str, Any], timeout: float = 10.0
    ) -> MessageEnvelope:
        """Send a request and await a correlated response."""
        envelope = MessageEnvelope(
            from_agent=self._agent_id,
            to_agent=target,
            msg_type=MessageType.REQUEST,
            intent=intent,
            data=data,
        )
        envelope.correlation_id = envelope.id

        future: asyncio.Future[MessageEnvelope] = asyncio.get_event_loop().create_future()
        self._pending_responses[envelope.correlation_id] = future

        await self._send(envelope)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending_responses.pop(envelope.correlation_id, None)

    async def send_response(
        self, original: MessageEnvelope, data: dict[str, Any]
    ) -> None:
        """Reply to a request message."""
        resp = MessageEnvelope(
            from_agent=self._agent_id,
            to_agent=original.from_agent,
            msg_type=MessageType.RESPONSE,
            intent=original.intent,
            data=data,
            correlation_id=original.correlation_id,
        )
        await self._send(resp)

    async def broadcast(self, intent: str, data: dict[str, Any]) -> None:
        """Broadcast a message to all agents (to_agent=None)."""
        envelope = MessageEnvelope(
            from_agent=self._agent_id,
            to_agent=None,
            msg_type=MessageType.BROADCAST,
            intent=intent,
            data=data,
        )
        await self._send(envelope)

    def subscribe(
        self, intent: str, callback: Callable[[MessageEnvelope], Awaitable[None]]
    ) -> None:
        """Register a handler for a specific intent via pub/sub."""
        self._subscriptions.setdefault(intent, []).append(callback)

    async def publish(self, intent: str, data: dict[str, Any]) -> None:
        """Publish to subscribed handlers for an intent."""
        envelope = MessageEnvelope(
            from_agent=self._agent_id,
            to_agent=None,
            msg_type=MessageType.SUBSCRIBE,
            intent=intent,
            data=data,
        )
        handlers = self._subscriptions.get(intent, [])
        for handler in handlers:
            try:
                await handler(envelope)
            except Exception:
                logger.exception("Subscription handler error for %s", intent)

    async def consensus(
        self, topic: str, vote: dict[str, Any], required_votes: int, timeout: float = 30.0
    ) -> dict[str, Any]:
        """Submit a vote and wait for quorum on a consensus topic."""
        self._consensus_votes.setdefault(topic, []).append({
            "agent_id": self._agent_id,
            "vote": vote,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        envelope = MessageEnvelope(
            from_agent=self._agent_id,
            to_agent=None,
            msg_type=MessageType.CONSENSUS,
            intent=topic,
            data={"vote": vote, "required": required_votes},
        )
        await self._send(envelope)

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            votes = self._consensus_votes.get(topic, [])
            if len(votes) >= required_votes:
                return {"topic": topic, "votes": votes, "reached_quorum": True}
            await asyncio.sleep(0.5)

        return {
            "topic": topic,
            "votes": self._consensus_votes.get(topic, []),
            "reached_quorum": False,
        }

    async def handle_incoming(self, envelope: MessageEnvelope) -> None:
        """Route an incoming message to the appropriate handler."""
        if envelope.msg_type == MessageType.RESPONSE:
            future = self._pending_responses.get(envelope.correlation_id)
            if future and not future.done():
                future.set_result(envelope)

        elif envelope.msg_type == MessageType.SUBSCRIBE:
            handlers = self._subscriptions.get(envelope.intent, [])
            for handler in handlers:
                await handler(envelope)

        elif envelope.msg_type == MessageType.CONSENSUS:
            self._consensus_votes.setdefault(envelope.intent, []).append({
                "agent_id": envelope.from_agent,
                "vote": envelope.data.get("vote"),
                "timestamp": envelope.timestamp,
            })
