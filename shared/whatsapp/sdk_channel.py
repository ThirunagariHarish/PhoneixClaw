"""Bidirectional WhatsApp ↔ Claude Agent SDK channel.

Bridges the Meta WhatsApp Cloud API to a per-agent Redis stream so that:

  Inbound:  webhook /webhook/whatsapp parses the Meta payload, extracts an
            optional @agent_name mention, and publishes to Redis stream
            `stream:whatsapp:inbox:{agent_name}` (or `:shared` if no mention).
            Each agent's trigger-bus consumer reads that stream and treats
            the message as a first-class wake signal / user turn.

  Outbound: `WhatsAppSDKChannel.send()` calls Meta Cloud API sendMessage
            with per-agent thread tagging. `notification_dispatcher` routes
            ALL outbound WhatsApp through this channel (no more raw httpx).

This is the plumbing the Claude Agent SDK expects for custom "channels":
an async iterator for input + a send() for output, both addressable by
agent. The SDK can consume `iter_inbound(agent_id)` as its message stream.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncIterator

logger = logging.getLogger(__name__)


META_API_BASE = "https://graph.facebook.com/v18.0"
INBOX_STREAM_PREFIX = "stream:whatsapp:inbox"


def _stream_key(agent_id: str | None) -> str:
    if not agent_id:
        return f"{INBOX_STREAM_PREFIX}:shared"
    return f"{INBOX_STREAM_PREFIX}:{agent_id}"


class WhatsAppSDKChannel:
    """Per-agent WhatsApp channel adapter suitable for the Claude Agent SDK."""

    def __init__(self, *, access_token: str | None = None,
                  phone_number_id: str | None = None,
                  redis_url: str | None = None):
        self.access_token = access_token or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        self.phone_number_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._client = None

    # ─── Redis client (lazy) ──────────────────────────────────────────────
    async def _get_redis(self):
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as redis_asyncio
            self._client = redis_asyncio.from_url(
                self.redis_url, encoding="utf-8", decode_responses=True
            )
            return self._client
        except Exception as exc:
            logger.debug("[whatsapp_channel] redis unavailable: %s", exc)
            return None

    # ─── Inbound ──────────────────────────────────────────────────────────
    async def publish_inbound(self, *, agent_id: str | None, author: str,
                               text: str, raw: dict | None = None) -> bool:
        """Called by the webhook handler to push a message onto the stream."""
        r = await self._get_redis()
        if r is None:
            return False
        payload = {
            "author": author,
            "text": text[:4000],
            "raw": json.dumps(raw or {}),
        }
        try:
            await r.xadd(_stream_key(agent_id), payload, maxlen=1000, approximate=True)
            # Also write to the shared stream so unroutable messages are still visible
            if agent_id:
                await r.xadd(_stream_key(None), {**payload, "agent_id": agent_id},
                             maxlen=1000, approximate=True)
            return True
        except Exception as exc:
            logger.warning("[whatsapp_channel] publish failed: %s", exc)
            return False

    async def iter_inbound(self, agent_id: str, *,
                            block_ms: int = 5000) -> AsyncIterator[dict]:
        """Async iterator over inbound messages for a specific agent.

        Intended to be used as the input stream of a ClaudeSDKClient session:
            async for msg in channel.iter_inbound(agent_id):
                ... treat as user turn ...
        """
        r = await self._get_redis()
        if r is None:
            return
        last_id = "$"  # start from NOW
        while True:
            try:
                res = await r.xread({_stream_key(agent_id): last_id},
                                     block=block_ms, count=10)
            except Exception as exc:
                logger.warning("[whatsapp_channel] xread error: %s", exc)
                await asyncio.sleep(1)
                continue
            if not res:
                continue
            for _, entries in res:
                for entry_id, fields in entries:
                    last_id = entry_id
                    yield {
                        "role": "user",
                        "content": fields.get("text", ""),
                        "author": fields.get("author", ""),
                        "source": "whatsapp",
                    }

    # ─── Outbound ─────────────────────────────────────────────────────────
    async def send(self, *, agent_id: str | None, text: str,
                    thread_id: str | None = None) -> bool:
        """Send a message to the configured recipient / thread.

        thread_id is a WhatsApp phone number or group ID. If omitted we fall
        back to WHATSAPP_USER_NUMBER env var (classic 1:1 notification).
        """
        if not self.access_token or not self.phone_number_id:
            logger.debug("[whatsapp_channel] not configured — skipping send")
            return False

        recipient = thread_id or os.environ.get("WHATSAPP_USER_NUMBER", "")
        if not recipient:
            logger.debug("[whatsapp_channel] no recipient — skipping")
            return False

        # Prepend per-agent tag so manually-created groups can route by prefix
        prefixed = f"[agent:{agent_id}] {text}" if agent_id else text

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{META_API_BASE}/{self.phone_number_id}/messages",
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "messaging_product": "whatsapp",
                        "to": recipient,
                        "type": "text",
                        "text": {"body": prefixed[:4090]},
                    },
                )
                if resp.status_code in (200, 201):
                    return True
                logger.warning("[whatsapp_channel] send returned %s: %s",
                               resp.status_code, resp.text[:200])
                return False
        except Exception as exc:
            logger.warning("[whatsapp_channel] send failed: %s", exc)
            return False


_singleton: WhatsAppSDKChannel | None = None


def get_channel() -> WhatsAppSDKChannel:
    global _singleton
    if _singleton is None:
        _singleton = WhatsAppSDKChannel()
    return _singleton
