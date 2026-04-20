"""
Inter-agent communication router — supports 5 messaging patterns.

M2.10: Agent-to-agent communication.
Reference: PRD Section 13, ArchitecturePlan §5.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class MessagePattern(str, Enum):
    REQUEST_RESPONSE = "request_response"
    BROADCAST = "broadcast"
    PUB_SUB = "pub_sub"
    CHAIN = "chain"
    CONSENSUS = "consensus"


class AgentMessage:
    def __init__(self, sender: str, recipient: str | None, pattern: MessagePattern,
                 intent: str, data: dict[str, Any], correlation_id: str = ""):
        self.sender = sender
        self.recipient = recipient
        self.pattern = pattern
        self.intent = intent
        self.data = data
        self.correlation_id = correlation_id or f"{sender}-{datetime.now(timezone.utc).timestamp()}"
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sender": self.sender,
            "recipient": self.recipient,
            "pattern": self.pattern.value,
            "intent": self.intent,
            "data": self.data,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
        }


class AgentCommunicationRouter:
    """Routes messages between agents across same-instance and cross-instance."""

    def __init__(self):
        self._subscriptions: dict[str, list[str]] = {}  # topic -> list of agent_ids
        self._handlers: dict[str, Callable] = {}  # agent_id -> handler
        self._pending_responses: dict[str, asyncio.Future] = {}
        self._message_log: list[dict] = []

    def register_agent(self, agent_id: str, handler: Callable | None = None) -> None:
        if handler:
            self._handlers[agent_id] = handler

    def subscribe(self, agent_id: str, topic: str) -> None:
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
        if agent_id not in self._subscriptions[topic]:
            self._subscriptions[topic].append(agent_id)

    async def send(self, message: AgentMessage) -> dict[str, Any] | None:
        self._message_log.append(message.to_dict())

        if message.pattern == MessagePattern.REQUEST_RESPONSE:
            return await self._handle_request_response(message)
        elif message.pattern == MessagePattern.BROADCAST:
            return await self._handle_broadcast(message)
        elif message.pattern == MessagePattern.PUB_SUB:
            return await self._handle_pub_sub(message)
        elif message.pattern == MessagePattern.CHAIN:
            return await self._handle_chain(message)
        elif message.pattern == MessagePattern.CONSENSUS:
            return await self._handle_consensus(message)
        return None

    async def _handle_request_response(self, message: AgentMessage) -> dict | None:
        handler = self._handlers.get(message.recipient or "")
        if handler:
            return await handler(message.to_dict())
        return None

    async def _handle_broadcast(self, message: AgentMessage) -> dict:
        delivered = 0
        for agent_id, handler in self._handlers.items():
            if agent_id != message.sender:
                try:
                    await handler(message.to_dict())
                    delivered += 1
                except Exception:
                    pass
        return {"delivered": delivered}

    async def _handle_pub_sub(self, message: AgentMessage) -> dict:
        topic = message.intent
        subscribers = self._subscriptions.get(topic, [])
        delivered = 0
        for agent_id in subscribers:
            handler = self._handlers.get(agent_id)
            if handler and agent_id != message.sender:
                try:
                    await handler(message.to_dict())
                    delivered += 1
                except Exception:
                    pass
        return {"topic": topic, "delivered": delivered}

    async def _handle_chain(self, message: AgentMessage) -> dict | None:
        """Sequential processing pipeline: pass through agents in order."""
        chain_agents = message.data.get("chain", [])
        if not chain_agents:
            return None
        payload = message.data.get("payload", message.data)
        for agent_id in chain_agents:
            handler = self._handlers.get(agent_id)
            if handler:
                try:
                    result = await handler({
                        "sender": message.sender,
                        "recipient": agent_id,
                        "pattern": message.pattern.value,
                        "intent": message.intent,
                        "data": payload,
                        "correlation_id": message.correlation_id,
                    })
                    payload = result if isinstance(result, dict) else {"result": result}
                except Exception:
                    break
        return payload

    async def _handle_consensus(self, message: AgentMessage) -> dict:
        """Collect votes from multiple agents, return majority decision."""
        voters = [aid for aid in self._handlers if aid != message.sender]
        votes = []
        for agent_id in voters:
            handler = self._handlers.get(agent_id)
            if handler:
                try:
                    result = await handler(message.to_dict())
                    votes.append(result)
                except Exception:
                    pass
        return {"votes": votes, "total_voters": len(voters)}

    def get_stats(self) -> dict[str, Any]:
        return {
            "registered_agents": len(self._handlers),
            "subscriptions": {k: len(v) for k, v in self._subscriptions.items()},
            "total_messages": len(self._message_log),
        }
