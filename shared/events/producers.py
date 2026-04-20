"""Redis Stream producers for Phoenix v2 event bus."""
from __future__ import annotations

import os

import redis.asyncio as aioredis

from shared.events.envelope import Envelope, EventType

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

STREAM_TRADE_INTENTS = "stream:trade-intents"
STREAM_CONNECTOR_EVENTS = "stream:connector-events"
STREAM_BACKTEST_PROGRESS = "stream:backtest-progress"
STREAM_AGENT_MESSAGES = "stream:agent-messages"
STREAM_DEV_AGENT_EVENTS = "stream:dev-agent-events"
STREAM_AUTOMATION_TRIGGERS = "stream:automation-triggers"


class EventProducer:
    """Publishes Envelope messages to Redis Streams."""

    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def connect(self):
        self._redis = aioredis.from_url(REDIS_URL)

    async def close(self):
        if self._redis:
            await self._redis.close()

    async def publish(self, stream: str, envelope: Envelope):
        if not self._redis:
            await self.connect()
        await self._redis.xadd(stream, envelope.to_redis())

    async def emit_trade_intent(self, data: dict, source: str = "unknown") -> None:
        envelope = Envelope(
            event_type=EventType.TRADE_INTENT_CREATED,
            data=data,
            source=source,
        )
        await self.publish(STREAM_TRADE_INTENTS, envelope)

    async def emit_connector_event(self, data: dict, source: str = "unknown") -> None:
        envelope = Envelope(
            event_type=EventType.CONNECTOR_STATUS,
            data=data,
            source=source,
        )
        await self.publish(STREAM_CONNECTOR_EVENTS, envelope)

    async def emit_backtest_progress(
        self, data: dict, source: str = "unknown", event_type: str | None = None
    ) -> None:
        envelope = Envelope(
            event_type=event_type or EventType.BACKTEST_COMPLETED,
            data=data,
            source=source,
        )
        await self.publish(STREAM_BACKTEST_PROGRESS, envelope)

    async def emit_agent_message(self, data: dict, source: str = "unknown") -> None:
        envelope = Envelope(
            event_type=EventType.AGENT_MESSAGE,
            data=data,
            source=source,
        )
        await self.publish(STREAM_AGENT_MESSAGES, envelope)

    async def emit_dev_incident(self, data: dict, source: str = "unknown") -> None:
        envelope = Envelope(
            event_type=EventType.DEV_INCIDENT,
            data=data,
            source=source,
        )
        await self.publish(STREAM_DEV_AGENT_EVENTS, envelope)

    async def emit_automation_trigger(
        self, data: dict, source: str = "unknown"
    ) -> None:
        envelope = Envelope(
            event_type=EventType.AUTOMATION_TRIGGERED,
            data=data,
            source=source,
        )
        await self.publish(STREAM_AUTOMATION_TRIGGERS, envelope)
