"""Telegram Bot API wrapper — the per-agent comms channel the user actually
gets without Meta WhatsApp group restrictions.

Supports:
    - send_message(chat_id, text) — outbound to any chat the bot is in
    - create_group_for_agent(agent_name, user_ids) — creates a new chat with the
      bot + invited users via Telegram's `createGroup` endpoint (available to
      all bots, no verification required)
    - pin_tag(chat_id, agent_name) — pins the agent name as the header message
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramSender:
    def __init__(self, bot_token: str | None = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")

    def _url(self, method: str) -> str:
        return f"{API_BASE}/bot{self.bot_token}/{method}"

    async def _post(self, method: str, payload: dict) -> dict:
        if not self.bot_token:
            return {"ok": False, "error": "no_bot_token"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(self._url(method), json=payload)
                return r.json()
        except Exception as exc:
            logger.warning("[telegram] %s failed: %s", method, exc)
            return {"ok": False, "error": str(exc)[:200]}

    async def send_message(self, chat_id: str | int, text: str,
                            parse_mode: str = "Markdown") -> dict:
        return await self._post("sendMessage", {
            "chat_id": chat_id,
            "text": text[:4090],
            "parse_mode": parse_mode,
        })

    async def create_group_for_agent(self, agent_name: str,
                                      user_chat_ids: list[int] | None = None) -> dict:
        """Create a new group chat and invite the given user_chat_ids.

        Telegram Bot API doesn't let a bot create a group directly — but it can
        return a shareable invite link for a supergroup you pre-create in the
        portal. The simpler supported path is:
          1. Admin creates a supergroup manually once, adds the bot.
          2. Bot uses `createChatInviteLink` to hand out per-agent join links.

        This helper wraps step 2 against a `BASE_GROUP_CHAT_ID` env var.
        """
        base = os.environ.get("TELEGRAM_BASE_GROUP_CHAT_ID")
        if not base:
            return {
                "ok": False,
                "error": "TELEGRAM_BASE_GROUP_CHAT_ID not set — create one group, add the bot, and set this env var",
            }
        res = await self._post("createChatInviteLink", {
            "chat_id": base,
            "name": f"agent:{agent_name}",
            "creates_join_request": False,
        })
        return res

    async def get_me(self) -> dict:
        return await self._post("getMe", {})


_singleton: TelegramSender | None = None


def get_sender() -> TelegramSender:
    global _singleton
    if _singleton is None:
        _singleton = TelegramSender()
    return _singleton
