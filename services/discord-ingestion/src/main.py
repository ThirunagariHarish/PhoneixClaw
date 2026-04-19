"""Discord Ingestion Service — standalone container for Discord message listening.

Connects to Discord via official Bot tokens stored in the connectors table,
persists messages to channel_messages, and publishes events to Redis streams.
Runs independently of the API so Discord connections survive API restarts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.observability.metrics import discord_messages_counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("discord-ingestion")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

BACKOFF_SCHEDULE = [5, 10, 30, 60]
POLL_INTERVAL_SECONDS = 30

POSITIVE_KEYWORDS = frozenset({
    "bullish", "buy", "calls", "long", "moon", "rocket", "breakout", "pump", "rip", "green", "runner",
})
NEGATIVE_KEYWORDS = frozenset({
    "bearish", "sell", "puts", "short", "dump", "crash", "drill", "red", "fade", "tank",
})
TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")


class ConnectorState:
    """Tracks runtime state for a single Discord connector."""

    __slots__ = (
        "connector_id", "channel_name", "connected", "messages_received",
        "task", "poll_task", "channel_ids", "token", "auth_type",
    )

    def __init__(
        self, connector_id: str, channel_name: str, channel_ids: list[str],
        token: str, auth_type: str = "bot",
    ):
        self.connector_id = connector_id
        self.channel_name = channel_name
        self.connected = False
        self.messages_received = 0
        self.task: asyncio.Task | None = None
        self.poll_task: asyncio.Task | None = None
        self.channel_ids = channel_ids
        self.token = token
        self.auth_type = auth_type


_engine = None
_session_factory: async_sessionmaker | None = None
_redis: aioredis.Redis | None = None
_connectors: dict[str, ConnectorState] = {}
_running = False


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            DATABASE_URL,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _session_factory


async def _get_redis() -> aioredis.Redis | None:
    global _redis
    if _redis is None:
        try:
            _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        except Exception as exc:
            logger.warning("Redis unavailable: %s", exc)
    return _redis


def _decrypt_token(credentials_encrypted: str | None) -> tuple[str, str]:
    """Decrypt connector credentials and extract the Discord bot token.

    Returns (token, auth_type) where auth_type is 'bot' or 'user_token'.
    Prioritises bot_token for Discord TOS compliance.
    """
    if not credentials_encrypted:
        return "", "bot"
    try:
        from shared.crypto.credentials import decrypt_credentials
        creds = decrypt_credentials(credentials_encrypted)
        bot_token = creds.get("bot_token", "")
        if bot_token:
            return bot_token, "bot"
        user_token = creds.get("user_token", "")
        if user_token:
            logger.warning(
                "Connector uses deprecated user_token auth. "
                "Migrate to a Discord Bot token for TOS compliance."
            )
            return user_token, "user_token"
        return "", "bot"
    except Exception as exc:
        logger.error("Failed to decrypt credentials: %s", exc)
        return "", "bot"


def _extract_channel_ids(config: dict[str, Any] | None) -> list[str]:
    """Extract channel IDs from connector config, supporting multiple formats."""
    if not config:
        return []
    cids = config.get("channel_ids")
    if isinstance(cids, list) and cids:
        return [str(c) for c in cids if c]
    single = config.get("channel_id")
    if single:
        return [str(single)]
    selected = config.get("selected_channels")
    if isinstance(selected, list) and selected:
        out: list[str] = []
        for entry in selected:
            if isinstance(entry, dict):
                ch = entry.get("channel_id")
                if ch:
                    out.append(str(ch))
            elif isinstance(entry, str) and entry:
                out.append(entry)
        return out
    return []


def _extract_tickers(content: str) -> list[str]:
    return list(set(TICKER_PATTERN.findall(content)))


def _basic_sentiment(content: str) -> str:
    lower = content.lower()
    words = set(re.findall(r"[a-z]+", lower))
    pos = len(words & POSITIVE_KEYWORDS)
    neg = len(words & NEGATIVE_KEYWORDS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


async def _persist_message(
    session_factory: async_sessionmaker,
    state: ConnectorState,
    channel_name: str,
    author: str,
    content: str,
    raw_data: dict[str, Any],
    platform_message_id: str,
    posted_at: datetime,
) -> None:
    """INSERT a message row into channel_messages and publish to Redis."""
    tickers = _extract_tickers(content)
    msg_id = uuid.uuid4()
    connector_uuid = uuid.UUID(state.connector_id)
    correlation_id = str(uuid.uuid4())
    raw_data["correlation_id"] = correlation_id

    async with session_factory() as session:
        exists = await session.execute(
            text("SELECT 1 FROM channel_messages WHERE platform_message_id = :mid LIMIT 1"),
            {"mid": platform_message_id},
        )
        if exists.scalar():
            logger.debug("Duplicate message %s for connector %s, skipping", platform_message_id, state.connector_id)
            return

        await session.execute(
            text("""
                INSERT INTO channel_messages
                    (id, connector_id, channel, author, content, message_type, tickers_mentioned,
                     raw_data, platform_message_id, posted_at, created_at)
                VALUES
                    (:id, :connector_id, :channel, :author, :content, :message_type, :tickers,
                     :raw_data, :platform_message_id, :posted_at, :created_at)
            """),
            {
                "id": str(msg_id),
                "connector_id": str(connector_uuid),
                "channel": channel_name,
                "author": author,
                "content": content,
                "message_type": "info",
                "tickers": json.dumps(tickers),
                "raw_data": json.dumps(raw_data, default=str),
                "platform_message_id": platform_message_id,
                "posted_at": posted_at,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await session.commit()
        discord_messages_counter.inc()

    state.messages_received += 1

    redis_client = await _get_redis()
    if redis_client:
        payload = {
            "connector_id": state.connector_id,
            "channel": channel_name,
            "author": author,
            "content": content,
            "tickers": json.dumps(tickers),
            "timestamp": posted_at.isoformat(),
            "message_id": platform_message_id,
            "sentiment": _basic_sentiment(content),
            "correlation_id": correlation_id,
        }
        try:
            stream_payload = {k: str(v) for k, v in payload.items()}
            await redis_client.xadd(
                f"stream:messages:{state.connector_id}",
                stream_payload,
                maxlen=5000,
            )
            await redis_client.xadd(
                f"stream:channel:{state.connector_id}",
                stream_payload,
                maxlen=5000,
            )
        except Exception as exc:
            logger.warning("Redis publish failed for connector %s: %s", state.connector_id, exc)

    await _write_sentiment_feature(state.connector_id, tickers, content)


async def _write_sentiment_feature(connector_id: str, tickers: list[str], content: str) -> None:
    """Best-effort write of basic sentiment to the Feature Store."""
    if not tickers:
        return
    try:
        sentiment = _basic_sentiment(content)
        session_factory = _get_session_factory()
        redis_client = await _get_redis()
        from shared.feature_store.client import FeatureStoreClient
        async with session_factory() as session:
            fs = FeatureStoreClient(session, redis_client)
            for ticker in tickers:
                await fs.write_features(
                    ticker,
                    "sentiment",
                    {"discord_sentiment": sentiment, "source_connector": connector_id},
                    ttl_minutes=15,
                )
    except Exception as exc:
        logger.debug("Feature store write skipped: %s", exc)


async def _http_poller(state: ConnectorState) -> None:
    """HTTP polling fallback when the Discord gateway is unreachable."""
    session_factory = _get_session_factory()
    last_message_ids: dict[str, str] = {}
    logger.info("HTTP poller started for connector %s", state.connector_id)

    auth_value = (
        f"Bot {state.token}" if state.auth_type == "bot" and not state.token.startswith("Bot ")
        else state.token
    )

    while _running:
        for channel_id in state.channel_ids:
            try:
                url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=50"
                last_id = last_message_ids.get(channel_id)
                if last_id:
                    url += f"&after={last_id}"

                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(url, headers={"Authorization": auth_value})

                if resp.status_code == 200:
                    messages = resp.json()
                    for msg in reversed(messages):
                        mid = str(msg["id"])
                        async with session_factory() as session:
                            exists = await session.execute(
                                text("SELECT 1 FROM channel_messages WHERE platform_message_id = :mid LIMIT 1"),
                                {"mid": mid},
                            )
                            if exists.scalar():
                                continue

                        posted_at = (
                            datetime.fromisoformat(msg["timestamp"]).replace(tzinfo=timezone.utc)
                            if msg.get("timestamp") else datetime.now(timezone.utc)
                        )
                        author_info = msg.get("author", {})
                        author = f"{author_info.get('username', 'unknown')}#{author_info.get('discriminator', '0')}"
                        content = msg.get("content", "")
                        raw = {
                            "id": mid,
                            "content": content,
                            "author": author,
                            "channel_id": channel_id,
                            "channel_name": state.channel_name,
                            "timestamp": msg.get("timestamp"),
                            "guild_id": msg.get("guild_id", ""),
                        }
                        try:
                            await _persist_message(
                                session_factory,
                                state,
                                channel_name=state.channel_name,
                                author=author,
                                content=content,
                                raw_data=raw,
                                platform_message_id=mid,
                                posted_at=posted_at,
                            )
                        except Exception as exc:
                            logger.error("HTTP poller persist error for connector %s: %s", state.connector_id, exc)

                        last_message_ids[channel_id] = mid

                elif resp.status_code == 429:
                    retry_after = resp.json().get("retry_after", 5)
                    logger.warning(
                        "HTTP poller rate-limited for connector %s, sleeping %ss",
                        state.connector_id, retry_after,
                    )
                    await asyncio.sleep(float(retry_after))

                elif resp.status_code in (401, 403):
                    logger.error(
                        "HTTP poller token invalid for connector %s (HTTP %d), stopping",
                        state.connector_id, resp.status_code,
                    )
                    return

                else:
                    logger.warning(
                        "HTTP poller unexpected status %d for connector %s channel %s",
                        resp.status_code, state.connector_id, channel_id,
                    )

            except asyncio.CancelledError:
                logger.info("HTTP poller cancelled for connector %s", state.connector_id)
                return
            except Exception as exc:
                logger.error("HTTP poller error for connector %s channel %s: %s", state.connector_id, channel_id, exc)

        try:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("HTTP poller cancelled for connector %s", state.connector_id)
            return


async def _discord_listener(state: ConnectorState) -> None:
    """Connect to Discord and listen for messages on configured channels."""
    attempt = 0
    session_factory = _get_session_factory()

    while _running:
        try:
            import discord

            if state.auth_type == "bot":
                intents = discord.Intents.default()
                intents.guilds = True
                intents.guild_messages = True
                intents.message_content = True
                client = discord.Client(intents=intents)
            else:
                client = discord.Client()

            channel_ids_set = {str(cid) for cid in state.channel_ids}
            ready_event = asyncio.Event()

            @client.event
            async def on_ready():
                state.connected = True
                attempt_ref = 0  # noqa: F841
                ready_event.set()
                logger.info("Connected to Discord for connector %s (user: %s)", state.connector_id, client.user)
                if state.poll_task and not state.poll_task.done():
                    state.poll_task.cancel()
                    state.poll_task = None
                    logger.info("Gateway reconnected, stopped HTTP poller for connector %s", state.connector_id)

            @client.event
            async def on_message(message):
                try:
                    if channel_ids_set and str(message.channel.id) not in channel_ids_set:
                        return
                    raw = {
                        "id": str(message.id),
                        "content": message.content or "",
                        "author": str(message.author),
                        "channel_id": str(message.channel.id),
                        "channel_name": getattr(message.channel, "name", ""),
                        "timestamp": message.created_at.isoformat() if message.created_at else None,
                        "guild_id": str(message.guild.id) if message.guild else "",
                    }
                    await _persist_message(
                        session_factory,
                        state,
                        channel_name=raw["channel_name"] or raw["channel_id"],
                        author=raw["author"],
                        content=raw["content"],
                        raw_data=raw,
                        platform_message_id=raw["id"],
                        posted_at=(
                            message.created_at.replace(tzinfo=timezone.utc)
                            if message.created_at and message.created_at.tzinfo is None
                            else message.created_at or datetime.now(timezone.utc)
                        ),
                    )
                except Exception as exc:
                    logger.error("Error processing message on connector %s: %s", state.connector_id, exc)

            client_task = asyncio.create_task(
                client.start(state.token, bot=(state.auth_type == "bot"))
            )
            attempt = 0

            try:
                await asyncio.wait_for(ready_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Discord login timed out for connector %s, continuing anyway", state.connector_id)
                state.connected = True

            await client_task

        except asyncio.CancelledError:
            state.connected = False
            return
        except Exception as exc:
            state.connected = False
            backoff = BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)]
            logger.error(
                "Discord connection error for connector %s (attempt %d, retry in %ds): %s",
                state.connector_id, attempt, backoff, exc,
            )
            attempt += 1
            if attempt >= 5 and (state.poll_task is None or state.poll_task.done()):
                logger.warning(
                    "Gateway failed %d times for connector %s, starting HTTP poller fallback",
                    attempt, state.connector_id,
                )
                state.poll_task = asyncio.create_task(_http_poller(state))
            jitter = random.uniform(0, min(5, backoff * 0.3))
            await asyncio.sleep(backoff + jitter)

    state.connected = False


async def _load_and_start_connectors() -> None:
    """Query active Discord connectors from DB and start listener tasks."""
    global _running
    _running = True
    session_factory = _get_session_factory()

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT id, name, config, credentials_encrypted
                FROM connectors
                WHERE type = 'discord' AND status IN ('active', 'connected') AND is_active = true
            """)
        )
        rows = result.fetchall()

    for row in rows:
        connector_id = str(row[0])
        connector_name = row[1]
        config = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
        credentials_encrypted = row[3]

        token, auth_type = _decrypt_token(credentials_encrypted)
        if not token:
            token = config.get("token", "")
        if not token:
            logger.warning("Connector %s (%s) has no token, skipping", connector_id, connector_name)
            continue

        stored_auth_type = config.get("auth_type", "")
        if stored_auth_type:
            auth_type = stored_auth_type

        channel_ids = _extract_channel_ids(config)
        channel_name = config.get("channel_name", connector_name or "unknown")

        state = ConnectorState(
            connector_id=connector_id,
            channel_name=channel_name,
            channel_ids=channel_ids,
            token=token,
            auth_type=auth_type,
        )
        state.task = asyncio.create_task(_discord_listener(state))
        _connectors[connector_id] = state
        logger.info(
            "Started listener for connector %s (%s) with %d channels",
            connector_id, connector_name, len(channel_ids),
        )

    logger.info("Discord ingestion started with %d connectors", len(_connectors))


async def _shutdown_connectors() -> None:
    """Cancel all listener tasks and clean up."""
    global _running, _redis, _engine
    _running = False

    for state in _connectors.values():
        if state.task and not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except asyncio.CancelledError:
                pass
        if state.poll_task and not state.poll_task.done():
            state.poll_task.cancel()
            try:
                await state.poll_task
            except asyncio.CancelledError:
                pass
    _connectors.clear()

    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None

    if _engine is not None:
        try:
            await _engine.dispose()
        except Exception:
            pass
        _engine = None

    logger.info("Discord ingestion shut down")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _load_and_start_connectors()
    yield
    await _shutdown_connectors()


app = FastAPI(title="Phoenix Discord Ingestion", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "connectors": [
            {
                "id": state.connector_id,
                "channel": state.channel_name,
                "connected": state.connected,
                "messages_received": state.messages_received,
            }
            for state in _connectors.values()
        ],
    }


@app.get("/status")
async def status():
    return {
        "service": "discord-ingestion",
        "running": _running,
        "total_connectors": len(_connectors),
        "connectors": [
            {
                "id": state.connector_id,
                "channel": state.channel_name,
                "connected": state.connected,
                "messages_received": state.messages_received,
                "channel_ids": state.channel_ids,
                "task_alive": state.task is not None and not state.task.done() if state.task else False,
            }
            for state in _connectors.values()
        ],
    }


@app.get("/token-health/{connector_id}")
async def token_health(connector_id: str):
    state = _connectors.get(connector_id)
    if not state:
        return {"status": "unknown", "detail": "connector not found"}
    auth_value = (
        f"Bot {state.token}" if state.auth_type == "bot" and not state.token.startswith("Bot ")
        else state.token
    )
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": auth_value},
        )
    if resp.status_code == 200:
        user = resp.json()
        return {
            "status": "valid", "username": user.get("username"),
            "connected": state.connected, "auth_type": state.auth_type,
        }
    return {"status": "invalid", "http_status": resp.status_code}
