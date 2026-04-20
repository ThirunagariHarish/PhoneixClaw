"""
Discord connector — ingests messages from Discord channels.

M1.9: Discord is the primary connector for trading signals.
Reference: PRD Section 3.6, existing v1 services/discord-ingestor/.
"""

import asyncio
from datetime import datetime
from typing import Any, AsyncIterator

from services.connector_manager.src.base import (
    BaseConnector,
    ConnectorMessage,
    ConnectorStatus,
    ConnectorType,
)
from services.connector_manager.src.factory import register_connector


@register_connector(ConnectorType.DISCORD)
class DiscordConnector(BaseConnector):
    """
    Connects to Discord via official Bot token, listens
    to configured channels, and yields normalized ConnectorMessages.
    """

    @property
    def connector_type(self) -> ConnectorType:
        return ConnectorType.DISCORD

    def __init__(self, connector_id: str, config: dict[str, Any]):
        super().__init__(connector_id, config)
        self.token: str = config.get("token", "")
        self.guild_id: str = config.get("guild_id", "")
        self.channel_ids: list[str] = config.get("channel_ids", [])
        self._client = None
        self._message_queue: asyncio.Queue[ConnectorMessage] = asyncio.Queue()

    async def connect(self) -> None:
        """Initialize Discord connection using official discord.py (bot token)."""
        if not self.token:
            self.status = ConnectorStatus.ERROR
            raise ValueError("Discord token is required")

        self.status = ConnectorStatus.CONNECTING

        try:
            import discord
        except ImportError:
            self.status = ConnectorStatus.ERROR
            raise ValueError("discord.py not installed")

        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._channel_ids_set = {str(cid) for cid in self.channel_ids}

        @self._client.event
        async def on_ready():
            self.status = ConnectorStatus.ACTIVE

        @self._client.event
        async def on_message(message):
            # Filter to configured channels
            try:
                if self._channel_ids_set and str(message.channel.id) not in self._channel_ids_set:
                    return
                raw = {
                    "id": str(message.id),
                    "content": message.content or "",
                    "author": str(message.author),
                    "channel_id": str(message.channel.id),
                    "channel_name": getattr(message.channel, "name", ""),
                    "timestamp": message.created_at.isoformat() if message.created_at else datetime.now().isoformat(),
                    "guild_id": str(message.guild.id) if message.guild else "",
                }
                normalized = self._normalize_message(raw)
                await self._message_queue.put(normalized)
            except Exception:
                self._error_count += 1

        # Launch the client as a background task
        self._client_task = asyncio.create_task(self._client.start(self.token))

        # Wait up to 20s for on_ready
        for _ in range(40):
            if self.status == ConnectorStatus.ACTIVE:
                break
            await asyncio.sleep(0.5)

        if self.status != ConnectorStatus.ACTIVE:
            # Still connecting, but don't block forever
            self.status = ConnectorStatus.ACTIVE

    async def disconnect(self) -> None:
        """Close Discord connection."""
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        if hasattr(self, "_client_task") and self._client_task:
            try:
                self._client_task.cancel()
            except Exception:
                pass
        self.status = ConnectorStatus.DISCONNECTED

    async def health_check(self) -> dict[str, Any]:
        """Check Discord connectivity."""
        return {
            "reachable": self.status == ConnectorStatus.ACTIVE,
            "guild_id": self.guild_id,
            "channel_count": len(self.channel_ids),
            "status": self.status.value,
        }

    async def stream_messages(self) -> AsyncIterator[ConnectorMessage]:
        """Yield messages from configured Discord channels."""
        while self.status == ConnectorStatus.ACTIVE:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=30.0)
                self._last_message_at = datetime.now()
                yield msg
            except asyncio.TimeoutError:
                continue
            except Exception:
                self._error_count += 1
                if self._error_count > 10:
                    self.status = ConnectorStatus.ERROR
                    break

    def _normalize_message(self, raw: dict[str, Any]) -> ConnectorMessage:
        """Convert raw Discord message to normalized format."""
        return ConnectorMessage(
            source_type=ConnectorType.DISCORD,
            source_id=self.connector_id,
            channel=raw.get("channel_name", ""),
            author=raw.get("author", ""),
            content=raw.get("content", ""),
            raw_data=raw,
            timestamp=datetime.fromisoformat(raw["timestamp"]) if "timestamp" in raw else datetime.now(),
            metadata={
                "guild_id": self.guild_id,
                "channel_id": raw.get("channel_id", ""),
                "message_id": raw.get("id", ""),
            },
        )
