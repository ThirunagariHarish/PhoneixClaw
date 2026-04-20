"""
WebSocket Gateway — dedicated WebSocket server for real-time dashboard updates.

M1.10: Trades/Positions real-time, M1.11: Agent heartbeats, M2.5: Trade intents.
Reference: ArchitecturePlan Section 3, ImplementationPlan Section 5.10.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

CHANNELS = ("trades", "positions", "agents", "heartbeat", "alerts", "notifications")


class ConnectionManager:
    """Manages WebSocket connections grouped by channel."""

    def __init__(self):
        self._subscribers: dict[str, set] = {ch: set() for ch in CHANNELS}

    async def subscribe(self, websocket, channel: str):
        if channel not in self._subscribers:
            self._subscribers[channel] = set()
        self._subscribers[channel].add(websocket)
        logger.info("Client subscribed to channel '%s' (%d total)", channel, len(self._subscribers[channel]))

    async def unsubscribe(self, websocket, channel: str | None = None):
        channels = [channel] if channel else list(self._subscribers.keys())
        for ch in channels:
            self._subscribers.get(ch, set()).discard(websocket)

    async def broadcast(self, channel: str, data: dict[str, Any]):
        if channel not in self._subscribers:
            return
        payload = json.dumps({"channel": channel, "data": data})
        dead = set()
        for ws in self._subscribers[channel]:
            try:
                await ws.send(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._subscribers[channel].discard(ws)

    def subscriber_count(self, channel: str) -> int:
        return len(self._subscribers.get(channel, set()))


class RedisStreamConsumer:
    """Consumes Redis Streams and broadcasts to WebSocket subscribers."""

    STREAM_CHANNEL_MAP = {
        "stream:trade-intents": "trades",
        "stream:position-updates": "positions",
        "stream:agent-events": "agents",
        "stream:heartbeats": "heartbeat",
        "stream:alerts": "alerts",
    }

    def __init__(self, redis_client, manager: ConnectionManager):
        self._redis = redis_client
        self._manager = manager
        self._running = False
        self._consumer_group = "ws-gateway"
        self._consumer_name = "ws-gw-1"

    async def start(self):
        self._running = True
        streams = {s: ">" for s in self.STREAM_CHANNEL_MAP}
        for stream in self.STREAM_CHANNEL_MAP:
            try:
                await self._redis.xgroup_create(stream, self._consumer_group, id="0", mkstream=True)
            except Exception:
                pass

        logger.info("Redis stream consumer started for %d streams", len(streams))
        while self._running:
            try:
                results = await self._redis.xreadgroup(
                    self._consumer_group,
                    self._consumer_name,
                    streams,
                    count=50,
                    block=1000,
                )
                for stream_name, messages in results:
                    channel = self.STREAM_CHANNEL_MAP.get(stream_name)
                    if not channel:
                        continue
                    for msg_id, fields in messages:
                        data = {k: v for k, v in fields.items()}
                        await self._manager.broadcast(channel, data)
                        await self._redis.xack(stream_name, self._consumer_group, msg_id)
            except Exception:
                logger.exception("Stream consumer error")
                await asyncio.sleep(1)

    def stop(self):
        self._running = False


async def create_gateway(host: str = "0.0.0.0", port: int = 8031, redis_client=None):
    """
    Create and start the WebSocket gateway using the `websockets` library.
    """
    try:
        import websockets
    except ImportError:
        logger.error("websockets package not installed")
        return

    manager = ConnectionManager()

    async def handler(websocket, path="/"):
        channel = path.strip("/") or "trades"
        if channel not in CHANNELS:
            await websocket.close(1008, f"Unknown channel: {channel}")
            return
        await manager.subscribe(websocket, channel)
        try:
            async for message in websocket:
                try:
                    payload = json.loads(message)
                    if payload.get("action") == "subscribe":
                        new_ch = payload.get("channel", "")
                        if new_ch in CHANNELS:
                            await manager.subscribe(websocket, new_ch)
                    elif payload.get("action") == "unsubscribe":
                        rm_ch = payload.get("channel", "")
                        await manager.unsubscribe(websocket, rm_ch)
                except json.JSONDecodeError:
                    pass
        finally:
            await manager.unsubscribe(websocket)

    if redis_client:
        consumer = RedisStreamConsumer(redis_client, manager)
        asyncio.create_task(consumer.start())

    server = await websockets.serve(handler, host, port)
    logger.info("WebSocket gateway listening on ws://%s:%d", host, port)
    await server.wait_closed()
