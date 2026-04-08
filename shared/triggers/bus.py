"""Phoenix Trigger Bus — Redis-backed wake-up signals for agents.

Every source that should wake an agent publishes a typed Trigger here.
Agents run a consumer loop that reads from both the Redis stream and the
local `pending_tasks.json` file (fallback for Redis outages).

Trigger types:
    chat:message            — user said something in the dashboard chat
    channel:new_message     — new Discord/Reddit/Twitter message on a subscribed channel
    cron:fire               — scheduler fired a per-agent cron
    agent:knowledge_share   — another agent sent a knowledge_intent message
    api:instruct            — API POST /agents/{id}/instruct

Usage:
    from shared.triggers import get_bus, Trigger, TriggerType

    bus = get_bus()
    await bus.publish(Trigger(
        agent_id=agent_id,
        type=TriggerType.CHAT_MESSAGE,
        payload={"message": "hi", "user_id": "abc"},
    ))

    # Agent consumer loop
    async for trigger in bus.subscribe(agent_id):
        handle(trigger)
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class TriggerType(str, Enum):
    CHAT_MESSAGE = "chat:message"
    CHANNEL_NEW_MESSAGE = "channel:new_message"
    CRON_FIRE = "cron:fire"
    AGENT_KNOWLEDGE_SHARE = "agent:knowledge_share"
    API_INSTRUCT = "api:instruct"
    MORNING_BRIEFING = "cron:morning_briefing"


@dataclass
class Trigger:
    agent_id: str
    type: TriggerType
    payload: dict = field(default_factory=dict)
    trigger_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    def to_json(self) -> str:
        d = asdict(self)
        d["type"] = self.type.value if isinstance(self.type, TriggerType) else str(self.type)
        return json.dumps(d)

    @classmethod
    def from_json(cls, s: str) -> "Trigger":
        d = json.loads(s)
        return cls(
            agent_id=d["agent_id"],
            type=TriggerType(d["type"]),
            payload=d.get("payload") or {},
            trigger_id=d.get("trigger_id") or uuid.uuid4().hex,
            created_at=float(d.get("created_at") or time.time()),
        )


def _stream_key(agent_id: str) -> str:
    return f"phoenix:triggers:{agent_id}"


class TriggerBus:
    """Thin wrapper around Redis Streams with a graceful no-op fallback.

    Publishes to XADD stream per agent. Consumers XREAD blocking on their agent's
    stream. Falls back to writing to `pending_tasks.json` in the agent's workdir
    when Redis is unavailable.
    """

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._client = None

    async def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as redis_asyncio
            self._client = redis_asyncio.from_url(
                self.redis_url, encoding="utf-8", decode_responses=True
            )
            return self._client
        except Exception as exc:
            logger.debug("[trigger_bus] redis unavailable (%s) — fallback mode", exc)
            return None

    async def publish(self, trigger: Trigger, *, workdir: str | None = None) -> bool:
        """Publish a trigger. Returns True on success.

        Writes to Redis stream AND (if workdir given) appends to pending_tasks.json
        as a redundant local signal so agents without Redis connectivity still fire.
        """
        written = False
        client = await self._get_client()
        if client is not None:
            try:
                await client.xadd(
                    _stream_key(trigger.agent_id),
                    {"data": trigger.to_json()},
                    maxlen=1000,
                    approximate=True,
                )
                written = True
            except Exception as exc:
                logger.warning("[trigger_bus] xadd failed: %s", exc)

        if workdir:
            try:
                from pathlib import Path
                p = Path(workdir) / "pending_tasks.json"
                existing = []
                if p.exists():
                    try:
                        existing = json.loads(p.read_text()) or []
                    except Exception:
                        existing = []
                if not isinstance(existing, list):
                    existing = []
                existing.append(json.loads(trigger.to_json()))
                # Cap to last 200 entries
                if len(existing) > 200:
                    existing = existing[-200:]
                p.write_text(json.dumps(existing, indent=2))
                written = True
            except Exception as exc:
                logger.debug("[trigger_bus] file fallback failed: %s", exc)

        return written

    async def subscribe(self, agent_id: str, *, block_ms: int = 5000) -> AsyncIterator[Trigger]:
        """Consumer loop. Yields triggers as they arrive on the agent's stream.

        Use from inside each agent template's main loop. Call in a task so the
        agent can still do other work concurrently.
        """
        client = await self._get_client()
        if client is None:
            return  # no-op generator
        last_id = "$"
        while True:
            try:
                res = await client.xread({_stream_key(agent_id): last_id}, block=block_ms, count=10)
            except Exception as exc:
                logger.warning("[trigger_bus] xread error: %s", exc)
                import asyncio
                await asyncio.sleep(1)
                continue
            if not res:
                continue
            for _stream_name, entries in res:
                for entry_id, fields in entries:
                    last_id = entry_id
                    try:
                        yield Trigger.from_json(fields.get("data", "{}"))
                    except Exception as exc:
                        logger.warning("[trigger_bus] bad trigger %s: %s", entry_id, exc)

    async def ack_all(self, agent_id: str) -> None:
        """Mark the stream up to NOW as consumed. Best-effort cleanup."""
        client = await self._get_client()
        if client is None:
            return
        try:
            await client.xtrim(_stream_key(agent_id), minid=f"{int(time.time() * 1000)}-0", approximate=True)
        except Exception:
            pass


_singleton: TriggerBus | None = None


def get_bus() -> TriggerBus:
    global _singleton
    if _singleton is None:
        _singleton = TriggerBus()
    return _singleton
