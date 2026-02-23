import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import Message

from shared.kafka_utils.producer import KafkaProducerWrapper

logger = logging.getLogger(__name__)

_redis_client = None

KAFKA_SEND_RETRIES = 3
KAFKA_RETRY_DELAY = 0.5


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis

            from shared.config.base_config import config
            _redis_client = aioredis.from_url(config.redis.url, decode_responses=True)
            await _redis_client.ping()
        except Exception:
            logger.warning("Redis unavailable for dedup, using in-memory fallback")
            _redis_client = False
    return _redis_client if _redis_client is not False else None


class DiscordIngestor:
    """Per-user Discord ingestor that publishes messages to Kafka.

    Supports two auth modes:
      - "bot"        -> standard bot token (requires server admin to invite the bot)
      - "user_token" -> user account token via discord.py-self (works as a regular member)
    """

    def __init__(
        self,
        token: str,
        target_channels: list[int],
        user_id: str,
        auth_type: str = "user_token",
        producer: KafkaProducerWrapper | None = None,
        data_source_id: str | None = None,
        on_connected: "asyncio.coroutines.coroutine | None" = None,
    ) -> None:
        self._token = token
        self._target_channels = set(target_channels)
        self._user_id = user_id
        self._auth_type = auth_type
        self._producer = producer or KafkaProducerWrapper()
        self._data_source_id = data_source_id
        self._on_connected = on_connected
        self._dedup_cache: set[str] = set()

        self._client = discord.Client()

        # discord.py dispatches events via getattr(client, 'on_<event>').
        # Setting attributes directly ensures the correct lookup name.
        self._client.on_ready = self._handle_ready  # type: ignore[attr-defined]
        self._client.on_message = self._handle_message  # type: ignore[attr-defined]

    async def _handle_ready(self) -> None:
        logger.info(
            "Discord ingestor ready (user=%s, mode=%s, channels=%s, data_source=%s)",
            self._user_id, self._auth_type, self._target_channels, self._data_source_id,
        )
        if self._on_connected:
            try:
                await self._on_connected()
            except Exception:
                logger.exception("on_connected callback failed")
        if not self._target_channels:
            logger.info("No target channels configured — listing available channels:")
            for guild in self._client.guilds:
                for channel in guild.text_channels:
                    logger.info("  #%s (id: %d) in %s", channel.name, channel.id, guild.name)

    async def _handle_message(self, message: Message) -> None:
        try:
            if message.author == self._client.user:
                return
            if self._target_channels and message.channel.id not in self._target_channels:
                return

            content = message.content.strip()
            if not content:
                return

            channel_id = str(message.channel.id)
            msg_key = f"{channel_id}:{message.id}"

            redis_cl = await _get_redis()
            if redis_cl:
                dedup_key = f"dedup:discord:{msg_key}"
                if await redis_cl.exists(dedup_key):
                    return
                await redis_cl.set(dedup_key, "1", ex=3600)
            else:
                if msg_key in self._dedup_cache:
                    return
                self._dedup_cache.add(msg_key)
                if len(self._dedup_cache) > 10000:
                    self._dedup_cache.clear()

            guild_id = ""
            try:
                guild_id = str(message.guild.id) if message.guild else ""
            except AttributeError:
                guild_id = ""

            raw_msg = {
                "content": content,
                "message_id": str(message.id),
                "source_message_id": str(message.id),
                "author": str(message.author),
                "channel_name": str(message.channel),
                "channel_id": channel_id,
                "guild_id": guild_id,
                "user_id": self._user_id,
                "data_source_id": self._data_source_id,
                "source": "discord",
                "source_type": "discord",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            headers = [
                ("user_id", self._user_id.encode("utf-8")),
                ("channel_id", channel_id.encode("utf-8")),
            ]

            for attempt in range(1, KAFKA_SEND_RETRIES + 1):
                try:
                    await self._producer.send(
                        "raw-messages", value=raw_msg, key=msg_key, headers=headers,
                    )
                    logger.debug("Published message %s to raw-messages", msg_key)
                    break
                except Exception:
                    if attempt == KAFKA_SEND_RETRIES:
                        logger.exception(
                            "Failed to publish message %s after %d attempts (dropped)",
                            msg_key, KAFKA_SEND_RETRIES,
                        )
                    else:
                        logger.warning(
                            "Kafka send attempt %d/%d failed for %s, retrying...",
                            attempt, KAFKA_SEND_RETRIES, msg_key,
                        )
                        await asyncio.sleep(KAFKA_RETRY_DELAY * attempt)
        except Exception:
            logger.exception("Unhandled error processing message %s", getattr(message, "id", "?"))

    async def start(self) -> None:
        if not self._producer.is_started:
            await self._producer.start()

        is_bot = self._auth_type == "bot"
        logger.info(
            "Connecting to Discord (user=%s, mode=%s, channels=%s, data_source=%s)",
            self._user_id, self._auth_type, self._target_channels, self._data_source_id,
        )
        try:
            await self._client.start(self._token, bot=is_bot)
        except TypeError:
            logger.warning("discord.py-self does not accept bot= param, retrying without it")
            await self._client.start(self._token)
        except Exception:
            logger.exception(
                "Failed to connect to Discord (user=%s, mode=%s, data_source=%s)",
                self._user_id, self._auth_type, self._data_source_id,
            )
            raise

    async def stop(self) -> None:
        try:
            await self._client.close()
        except Exception:
            logger.exception("Error closing Discord client")
        try:
            await self._producer.stop()
        except Exception:
            logger.exception("Error stopping Kafka producer")
