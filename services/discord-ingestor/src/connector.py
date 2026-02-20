import logging
from datetime import datetime, timezone

import discord
from discord import Message

from shared.kafka_utils.producer import KafkaProducerWrapper

logger = logging.getLogger(__name__)


class DiscordIngestor:
    """Per-user Discord ingestor that publishes messages to Kafka.

    Supports two auth modes:
      - "bot"        → standard bot token (requires server admin to invite the bot)
      - "user_token" → user account token via discord.py-self (works as a regular member)
    """

    def __init__(
        self,
        token: str,
        target_channels: list[int],
        user_id: str,
        auth_type: str = "user_token",
        producer: KafkaProducerWrapper | None = None,
    ) -> None:
        self._token = token
        self._target_channels = set(target_channels)
        self._user_id = user_id
        self._auth_type = auth_type
        self._producer = producer or KafkaProducerWrapper()
        self._dedup_cache: set[str] = set()

        self._client = discord.Client()
        self._client.event(self._on_ready)
        self._client.event(self._on_message)

    async def _on_ready(self) -> None:
        logger.info(
            "Discord ingestor ready (user=%s, mode=%s, channels=%s)",
            self._user_id, self._auth_type, self._target_channels,
        )
        if not self._target_channels:
            logger.info("No target channels configured — listing available channels:")
            for guild in self._client.guilds:
                for channel in guild.text_channels:
                    logger.info("  #%s (id: %d) in %s", channel.name, channel.id, guild.name)

    async def _on_message(self, message: Message) -> None:
        if message.author == self._client.user:
            return
        if self._target_channels and message.channel.id not in self._target_channels:
            return

        content = message.content.strip()
        if not content:
            return

        msg_key = f"{message.id}"
        if msg_key in self._dedup_cache:
            return
        self._dedup_cache.add(msg_key)
        if len(self._dedup_cache) > 10000:
            self._dedup_cache.clear()

        raw_msg = {
            "content": content,
            "message_id": str(message.id),
            "author": str(message.author),
            "channel_name": str(message.channel),
            "channel_id": str(message.channel.id),
            "guild_id": str(message.guild.id) if message.guild else "",
            "user_id": self._user_id,
            "source": "discord",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        headers = [
            ("user_id", self._user_id.encode("utf-8")),
            ("channel_id", str(message.channel.id).encode("utf-8")),
        ]

        try:
            await self._producer.send("raw-messages", value=raw_msg, key=msg_key, headers=headers)
            logger.debug("Published message %s to raw-messages", msg_key)
        except Exception:
            logger.exception("Failed to publish message %s", msg_key)

    async def start(self) -> None:
        if not self._producer.is_started:
            await self._producer.start()

        is_bot = self._auth_type == "bot"
        logger.info("Connecting to Discord (mode=%s)…", self._auth_type)
        await self._client.start(self._token, bot=is_bot)

    async def stop(self) -> None:
        await self._client.close()
        await self._producer.stop()
