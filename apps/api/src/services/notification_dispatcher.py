"""Multi-channel notification dispatcher.

Sends notifications to:
- Database (notifications table)
- WebSocket via Redis Stream (real-time dashboard updates)
- WhatsApp via existing shared/whatsapp/sender.py

Used by morning routine, decision engine, position monitor, and supervisor.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# Event type → message templates
EVENT_TEMPLATES = {
    "agent_wake": {
        "title": "{agent_name} is awake",
        "body": "Good morning! {agent_name} is starting morning research for {channel_name}",
    },
    "morning_briefing": {
        "title": "Morning Market Briefing",
        "body": "{briefing}",
    },
    "trade_entry": {
        "title": "TRADE: {agent_name} {side} {ticker}",
        "body": "{side} {ticker} @ ${price} x{qty}\nReason: {reasoning}",
    },
    "trade_exit": {
        "title": "CLOSED: {agent_name} {ticker}",
        "body": "{ticker} closed @ ${exit_price}\nP&L: {pnl_pct}\nReason: {exit_reason}",
    },
    "risk_alert": {
        "title": "RISK ALERT: {agent_name}",
        "body": "Daily loss at {pct}% of limit. Action: {action_taken}",
    },
    "watchlist_add": {
        "title": "Watchlist: {agent_name} added {ticker}",
        "body": "{ticker} added to watchlist (confidence={confidence})\nReason: {reason}",
    },
    "paper_trade": {
        "title": "PAPER: {agent_name} {ticker}",
        "body": "Simulated {side} {ticker} @ ${price}\nReason: {reasoning}",
    },
    "info": {
        "title": "{title}",
        "body": "{body}",
    },
}


class NotificationDispatcher:
    """Dispatch notifications across DB, WebSocket, and WhatsApp."""

    def __init__(self):
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379"),
                    decode_responses=True,
                )
            except Exception as e:
                logger.warning("Redis unavailable for notifications: %s", e)
        return self._redis

    async def dispatch(
        self,
        event_type: str,
        agent_id: str | None,
        title: str | None = None,
        body: str | None = None,
        data: dict | None = None,
        channels: list[str] | None = None,
    ) -> dict:
        """Dispatch notification across all configured channels.

        Args:
            event_type: One of EVENT_TEMPLATES keys + custom
            agent_id: Optional agent UUID string
            title: Override title (else uses template)
            body: Override body (else uses template)
            data: Context for template formatting and ws payload
            channels: ["db", "ws", "whatsapp"] (defaults to all)
        """
        channels = channels or ["db", "ws", "whatsapp"]
        data = data or {}

        # Format title/body from template if not explicitly provided
        template = EVENT_TEMPLATES.get(event_type, EVENT_TEMPLATES["info"])
        try:
            final_title = title or template["title"].format(**data, title="")
            final_body = body or template["body"].format(**data, body="")
        except KeyError as exc:
            logger.warning("Notification template missing key %s for %s", exc, event_type)
            final_title = title or event_type.replace("_", " ").title()
            final_body = body or json.dumps(data, default=str)[:500]

        results: dict = {}

        if "db" in channels:
            results["db"] = await self._save_to_db(
                event_type, agent_id, final_title, final_body, data
            )
        if "ws" in channels:
            results["ws"] = await self._push_websocket(
                event_type, agent_id, final_title, final_body, data
            )
        if "whatsapp" in channels:
            results["whatsapp"] = await self._send_whatsapp(final_title, final_body)

        logger.info("Notification %s dispatched: %s", event_type, results)
        return results

    async def _save_to_db(self, event_type: str, agent_id: str | None,
                          title: str, body: str, data: dict) -> bool:
        try:
            from shared.db.engine import get_session
            from shared.db.models.notification import Notification

            agent_uuid = uuid.UUID(agent_id) if agent_id else None
            async for session in get_session():
                notif = Notification(
                    id=uuid.uuid4(),
                    user_id=None,
                    title=title[:200],
                    body=body[:5000],
                    category=event_type,
                    severity="info",
                    source="agent" if agent_id else "system",
                    agent_id=agent_uuid,
                    event_type=event_type,
                    data=data,
                    channels_sent={"db": True},
                )
                session.add(notif)
                await session.commit()
            return True
        except Exception as e:
            logger.warning("DB notification save failed: %s", e)
            return False

    async def _push_websocket(self, event_type: str, agent_id: str | None,
                               title: str, body: str, data: dict) -> bool:
        redis = await self._get_redis()
        if not redis:
            return False
        try:
            payload = {
                "type": f"notification.{event_type}",
                "agent_id": agent_id or "",
                "title": title,
                "body": body,
                "data": json.dumps(data, default=str),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await redis.xadd("stream:notifications", payload, maxlen=1000)
            return True
        except Exception as e:
            logger.warning("WS push failed: %s", e)
            return False

    async def _send_whatsapp(self, title: str, body: str) -> bool:
        phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        token = os.getenv("WHATSAPP_ACCESS_TOKEN")
        to_number = os.getenv("WHATSAPP_USER_NUMBER")

        if not all([phone_id, token, to_number]):
            logger.debug("WhatsApp not configured")
            return False

        try:
            from shared.whatsapp.sender import send_whatsapp_message
            message = f"*{title}*\n\n{body}"
            return bool(send_whatsapp_message(phone_id, token, to_number, message))
        except Exception as e:
            logger.warning("WhatsApp send failed: %s", e)
            return False


# Module-level singleton
notification_dispatcher = NotificationDispatcher()
