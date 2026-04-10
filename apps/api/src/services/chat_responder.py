"""Chat Responder — legacy utility module.

All chat routing now goes through AgentGateway.chat_with_agent().
This module is kept for backward-compatibility imports only.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from apps.api.src.services.agent_gateway import gateway

logger = logging.getLogger(__name__)


async def _write_fallback_reply(agent_id: uuid.UUID, text: str) -> None:
    """Write a reply directly to the DB (convenience wrapper)."""
    await gateway._write_chat_reply(agent_id, text)


def schedule_reply(agent_id: uuid.UUID, user_message: str) -> None:
    """Deprecated — routes through ChatGateway.  Kept for any stale callers."""
    logger.info("[chat_responder] schedule_reply redirecting to gateway.chat_with_agent")
    asyncio.ensure_future(gateway.chat_with_agent(agent_id, user_message))
