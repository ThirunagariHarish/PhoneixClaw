"""Redis Stream consumers for Phoenix v2 event bus."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable

import redis.asyncio as aioredis

from shared.events.envelope import Envelope, EventType

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


class BaseConsumer:
    """Base class for Redis Stream consumer group workers."""

    def __init__(self, stream: str, group: str, consumer_name: str):
        self.stream = stream
        self.group = group
        self.consumer_name = consumer_name
        self._running = False
        self._redis: aioredis.Redis | None = None
        self._logger = logging.getLogger(f"phoenix.consumer.{stream}")

    async def start(self):
        self._redis = aioredis.from_url(REDIS_URL)
        try:
            await self._redis.xgroup_create(
                self.stream, self.group, id="0", mkstream=True
            )
        except Exception:
            pass
        self._running = True
        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    self.group,
                    self.consumer_name,
                    {self.stream: ">"},
                    count=10,
                    block=5000,
                )
                for _, entries in messages:
                    for msg_id, data in entries:
                        envelope = Envelope.from_redis(data)
                        await self.handle(envelope)
                        await self._redis.xack(self.stream, self.group, msg_id)
            except Exception as e:
                self._logger.error(f"Consumer error: {e}")
                await asyncio.sleep(1)

    async def stop(self):
        self._running = False
        if self._redis:
            await self._redis.close()

    async def handle(self, envelope: Envelope):
        raise NotImplementedError


class ConnectorEventConsumer(BaseConsumer):
    """Processes connector status changes (connect, disconnect, error)."""

    STREAM = "stream:connector-events"
    GROUP = "connector-event-workers"

    def __init__(self, consumer_name: str = "connector-worker-1"):
        super().__init__(self.STREAM, self.GROUP, consumer_name)
        self._status_handlers: dict[str, Callable] = {}

    def on_status(self, status: str, handler: Callable):
        self._status_handlers[status] = handler

    async def handle(self, envelope: Envelope):
        status = envelope.data.get("status", "unknown")
        connector_id = envelope.data.get("connector_id", "unknown")
        self._logger.info(
            f"Connector {connector_id} status: {status} "
            f"(correlation={envelope.correlation_id})"
        )
        handler = self._status_handlers.get(status)
        if handler:
            await handler(envelope)


class BacktestProgressConsumer(BaseConsumer):
    """Processes backtest completion events and status updates."""

    STREAM = "stream:backtest-progress"
    GROUP = "backtest-progress-workers"

    def __init__(
        self,
        consumer_name: str = "backtest-worker-1",
        on_complete: Callable | None = None,
    ):
        super().__init__(self.STREAM, self.GROUP, consumer_name)
        self._on_complete = on_complete

    async def handle(self, envelope: Envelope):
        backtest_id = envelope.data.get("backtest_id", "unknown")
        status = envelope.data.get("status", "unknown")
        self._logger.info(
            f"Backtest {backtest_id} status: {status} "
            f"(correlation={envelope.correlation_id})"
        )
        if (
            envelope.event_type == EventType.BACKTEST_COMPLETED
            and self._on_complete
        ):
            await self._on_complete(envelope)


class AgentMessageConsumer(BaseConsumer):
    """Routes inter-agent messages to the appropriate handler."""

    STREAM = "stream:agent-messages"
    GROUP = "agent-message-workers"

    def __init__(self, consumer_name: str = "agent-msg-worker-1"):
        super().__init__(self.STREAM, self.GROUP, consumer_name)
        self._handlers: dict[str, Callable] = {}

    def register_handler(self, target_agent: str, handler: Callable):
        self._handlers[target_agent] = handler

    async def handle(self, envelope: Envelope):
        target = envelope.data.get("target_agent", "")
        sender = envelope.data.get("sender_agent", envelope.source)
        self._logger.info(
            f"Agent message from {sender} -> {target} "
            f"(correlation={envelope.correlation_id})"
        )
        handler = self._handlers.get(target)
        if handler:
            await handler(envelope)
        else:
            self._logger.warning(f"No handler registered for agent: {target}")


class DevAgentEventConsumer(BaseConsumer):
    """Processes dev agent incidents (errors, deployments, alerts)."""

    STREAM = "stream:dev-agent-events"
    GROUP = "dev-agent-workers"

    def __init__(
        self,
        consumer_name: str = "dev-agent-worker-1",
        on_incident: Callable | None = None,
    ):
        super().__init__(self.STREAM, self.GROUP, consumer_name)
        self._on_incident = on_incident

    async def handle(self, envelope: Envelope):
        incident_type = envelope.data.get("incident_type", "unknown")
        severity = envelope.data.get("severity", "info")
        self._logger.info(
            f"Dev incident: type={incident_type} severity={severity} "
            f"(correlation={envelope.correlation_id})"
        )
        if self._on_incident:
            await self._on_incident(envelope)


class AutomationTriggerConsumer(BaseConsumer):
    """Processes automation execution events."""

    STREAM = "stream:automation-triggers"
    GROUP = "automation-trigger-workers"

    def __init__(
        self,
        consumer_name: str = "automation-worker-1",
        on_trigger: Callable | None = None,
    ):
        super().__init__(self.STREAM, self.GROUP, consumer_name)
        self._on_trigger = on_trigger

    async def handle(self, envelope: Envelope):
        automation_id = envelope.data.get("automation_id", "unknown")
        action = envelope.data.get("action", "unknown")
        self._logger.info(
            f"Automation triggered: id={automation_id} action={action} "
            f"(correlation={envelope.correlation_id})"
        )
        if self._on_trigger:
            await self._on_trigger(envelope)
