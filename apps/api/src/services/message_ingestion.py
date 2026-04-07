"""Message ingestion daemon — runs inside API lifespan.

For every active Discord connector:
1. Instantiates DiscordConnector with decrypted token
2. Calls connector.stream_messages() in a background task
3. Persists each message to `channel_messages` table
4. Publishes to Redis stream `stream:channel:{connector_id}` so live
   analyst agents can subscribe via their discord_listener.py tool

This is the SINGLE source of truth for Discord messages. Analyst agents
no longer run their own Discord clients — they consume from Redis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task] = {}
_redis = None
_running = False


async def _get_redis():
    global _redis
    if _redis is None:
        try:
            import redis.asyncio as aioredis
            _redis = aioredis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379"),
                decode_responses=True,
            )
        except Exception as exc:
            logger.warning("[ingestion] Redis unavailable: %s", exc)
    return _redis


async def _persist_message(connector_id: str, msg) -> None:
    """Write a ConnectorMessage to channel_messages table + publish to Redis."""
    try:
        from shared.db.engine import get_session
        from shared.db.models.channel_message import ChannelMessage

        async for session in get_session():
            row = ChannelMessage(
                id=uuid.uuid4(),
                connector_id=uuid.UUID(connector_id),
                channel=msg.channel or "",
                author=msg.author or "",
                content=msg.content or "",
                message_type=getattr(msg, "message_type", "info"),
                tickers_mentioned=getattr(msg, "tickers", []) or [],
                raw_data=msg.raw_data or {},
                platform_message_id=(msg.metadata or {}).get("message_id", "")
                    if hasattr(msg, "metadata") else "",
                posted_at=msg.timestamp or datetime.now(timezone.utc),
            )
            session.add(row)
            await session.commit()
    except Exception as exc:
        logger.warning("[ingestion] DB persist failed: %s", exc)

    # Publish to Redis so analyst agents can consume
    try:
        redis = await _get_redis()
        if redis:
            channel_id = ""
            if hasattr(msg, "metadata") and msg.metadata:
                channel_id = msg.metadata.get("channel_id", "")
            if not channel_id:
                channel_id = connector_id

            payload = {
                "connector_id": connector_id,
                "channel_id": channel_id,
                "channel": msg.channel or "",
                "author": msg.author or "",
                "content": msg.content or "",
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else datetime.now(timezone.utc).isoformat(),
                "message_id": (msg.metadata or {}).get("message_id", "") if hasattr(msg, "metadata") else "",
            }
            # Stream per connector AND per channel for fine-grained subscription
            await redis.xadd(f"stream:channel:{connector_id}", {k: str(v) for k, v in payload.items()}, maxlen=5000)
            if channel_id and channel_id != connector_id:
                await redis.xadd(f"stream:channel:{channel_id}", {k: str(v) for k, v in payload.items()}, maxlen=5000)
    except Exception as exc:
        logger.warning("[ingestion] Redis publish failed: %s", exc)

    # P9: Fan out trigger bus wake signals to every agent subscribed via connector_agents
    try:
        from shared.db.engine import get_session
        from shared.db.models.connector import ConnectorAgent
        from sqlalchemy import select
        from shared.triggers import get_bus, Trigger, TriggerType

        async for session in get_session():
            res = await session.execute(
                select(ConnectorAgent).where(
                    ConnectorAgent.connector_id == uuid.UUID(connector_id)
                )
            )
            subs = list(res.scalars().all())
            if subs:
                bus = get_bus()
                for sub in subs:
                    channel_filter = getattr(sub, "channel", "*") or "*"
                    if channel_filter != "*" and channel_filter != (msg.channel or ""):
                        continue
                    try:
                        await bus.publish(Trigger(
                            agent_id=str(sub.agent_id),
                            type=TriggerType.CHANNEL_NEW_MESSAGE,
                            payload={
                                "connector_id": connector_id,
                                "channel": msg.channel or "",
                                "author": msg.author or "",
                                "content": (msg.content or "")[:2000],
                                "tickers": getattr(msg, "tickers", []) or [],
                            },
                        ))
                    except Exception:
                        pass
            break
    except Exception as exc:
        logger.debug("[ingestion] trigger fan-out skipped: %s", exc)


async def _ingest_loop(connector_id: str, connector) -> None:
    """Main loop: call connector.stream_messages() and persist each."""
    logger.info("[ingestion] Starting loop for connector %s", connector_id)
    reconnect_delay = 5

    while _running:
        try:
            await connector.connect()
            async for msg in connector.stream_messages():
                if not _running:
                    break
                await _persist_message(connector_id, msg)
            # If we exit the loop normally, try to reconnect
            if _running:
                logger.warning("[ingestion] Connector %s stream ended, reconnecting in %ds",
                               connector_id, reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 300)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception("[ingestion] Connector %s error: %s", connector_id, exc)
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 300)

    try:
        await connector.disconnect()
    except Exception:
        pass
    logger.info("[ingestion] Loop stopped for connector %s", connector_id)


async def start_ingestion() -> None:
    """Start ingestion for all active Discord connectors."""
    global _running
    if _running:
        return
    _running = True

    try:
        from shared.db.engine import get_session
        from shared.db.models.connector import Connector
        from shared.crypto.credentials import decrypt_credentials
        from sqlalchemy import select
    except Exception as exc:
        logger.warning("[ingestion] Imports failed: %s", exc)
        _running = False
        return

    try:
        from services.connector_manager.src.connectors.discord import DiscordConnector
    except Exception as exc:
        logger.warning("[ingestion] DiscordConnector import failed: %s", exc)
        _running = False
        return

    connectors_to_start = []
    async for session in get_session():
        result = await session.execute(
            select(Connector).where(
                Connector.type == "discord",
                Connector.is_active.is_(True),
            )
        )
        for c in result.scalars().all():
            try:
                creds = decrypt_credentials(c.credentials_encrypted) if c.credentials_encrypted else {}
            except Exception:
                creds = {}
            token = creds.get("user_token") or creds.get("bot_token") or (c.config or {}).get("token", "")
            if not token:
                logger.warning("[ingestion] Connector %s has no token", c.id)
                continue
            cfg = dict(c.config or {})
            cfg["token"] = token
            if not cfg.get("channel_ids") and cfg.get("channel_id"):
                cfg["channel_ids"] = [cfg["channel_id"]]
            connectors_to_start.append((str(c.id), cfg))

    for conn_id, cfg in connectors_to_start:
        try:
            connector = DiscordConnector(conn_id, cfg)
            task = asyncio.create_task(_ingest_loop(conn_id, connector))
            _tasks[conn_id] = task
        except Exception as exc:
            logger.exception("[ingestion] Failed to start connector %s: %s", conn_id, exc)

    logger.info("[ingestion] Started %d connectors", len(_tasks))


async def stop_ingestion() -> None:
    """Cancel all ingestion tasks."""
    global _running, _redis
    _running = False
    for conn_id, task in list(_tasks.items()):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _tasks.clear()
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None
    logger.info("[ingestion] Stopped")


def get_ingestion_status() -> dict:
    """Return current ingestion status for dashboard."""
    return {
        "running": _running,
        "connectors": [
            {"connector_id": cid, "alive": not task.done()}
            for cid, task in _tasks.items()
        ],
    }
