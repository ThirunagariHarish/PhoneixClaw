"""WhatsApp webhook — receive incoming messages from users.

Handles Meta Cloud API webhook verification (GET) and incoming messages (POST).
Parses @agent_name mentions and routes the instruction to the corresponding
agent via gateway.send_task() or by saving a chat message.
"""
from __future__ import annotations

import logging
import os
import re
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.agent import Agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhooks"])


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta Cloud API webhook verification (GET)."""
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "phoenix-verify")
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        try:
            return int(hub_challenge)
        except (TypeError, ValueError):
            return hub_challenge
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_incoming(request: Request, session: DbSession):
    """Handle incoming WhatsApp messages.

    Format: User sends "@agent_name <instruction>" via WhatsApp.
    We parse the mention and route the instruction to that agent.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message_text = _extract_message_text(body)
    if not message_text:
        return {"status": "no_message"}

    sender = _extract_sender(body)
    logger.info("WhatsApp from %s: %s", sender, message_text[:100])

    agent_name = _extract_agent_mention(message_text)
    if not agent_name:
        return {"status": "no_agent_mention", "message": message_text[:200]}

    # Find agent (case-insensitive partial match)
    result = await session.execute(
        select(Agent).where(Agent.name.ilike(f"%{agent_name}%"))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        logger.warning("Agent '%s' not found for WhatsApp instruction", agent_name)
        return {"status": "agent_not_found", "agent_name": agent_name}

    # Strip the @mention from the instruction
    instruction = re.sub(r"@\w+\s*", "", message_text).strip()
    if not instruction:
        return {"status": "empty_instruction"}

    # P-S5: Publish inbound to the WhatsApp SDK channel so the agent's Claude
    # session consumes it as a native user turn via iter_inbound().
    try:
        from shared.whatsapp import get_channel
        await get_channel().publish_inbound(
            agent_id=str(agent.id), author=sender, text=instruction,
            raw={"original": message_text, "agent_name": agent_name},
        )
    except Exception as exc:
        logger.debug("[whatsapp] channel publish failed: %s", exc)

    # Also publish via the Trigger Bus so trigger-consumer loops wake up too
    try:
        from shared.triggers import Trigger, TriggerType, get_bus
        await get_bus().publish(Trigger(
            agent_id=str(agent.id),
            type=TriggerType.CHAT_MESSAGE,
            payload={"source": "whatsapp", "text": instruction, "from": sender},
        ))
    except Exception as exc:
        logger.debug("[whatsapp] trigger publish failed: %s", exc)

    # Route via gateway.send_task() if running, else save as system log
    try:
        from apps.api.src.services.agent_gateway import gateway
        send_result = await gateway.send_task(agent.id, instruction)
        if send_result.get("status") == "queued":
            return {
                "status": "instruction_queued",
                "agent": agent.name,
                "task_id": send_result.get("task_id"),
                "instruction": instruction[:200],
            }
    except Exception as exc:
        logger.warning("send_task failed: %s", exc)

    # Fallback: save as system log so the agent can pick it up via polling
    try:
        from shared.db.models.system_log import SystemLog
        session.add(SystemLog(
            id=uuid.uuid4(),
            source="whatsapp",
            level="INFO",
            service="whatsapp-webhook",
            agent_id=str(agent.id),
            message=f"User instruction via WhatsApp: {instruction}",
        ))
        await session.commit()
    except Exception as exc:
        logger.warning("Failed to save instruction log: %s", exc)

    return {
        "status": "instruction_saved",
        "agent": agent.name,
        "instruction": instruction[:200],
        "from": sender,
    }


def _extract_message_text(body: dict) -> str | None:
    """Extract the text from a Meta Cloud API webhook payload."""
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if messages:
            msg = messages[0]
            text = msg.get("text", {})
            if isinstance(text, dict):
                return text.get("body", "")
            return str(text)
    except (IndexError, KeyError, TypeError, AttributeError):
        pass
    return None


def _extract_sender(body: dict) -> str:
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if messages:
            return messages[0].get("from", "unknown")
    except (IndexError, KeyError, TypeError):
        pass
    return "unknown"


def _extract_agent_mention(text: str) -> str | None:
    match = re.search(r"@(\w+)", text)
    return match.group(1) if match else None
