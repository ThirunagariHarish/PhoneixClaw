"""Publishers — write decisions to Redis streams and external APIs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
import redis.asyncio as aioredis

from shared.events.producers import STREAM_AGENT_MESSAGES, STREAM_TRADE_INTENTS

logger = logging.getLogger(__name__)


async def publish_trade_intent(redis_client: aioredis.Redis, intent: dict) -> str | None:
    """XADD a trade intent to the trade-intents stream. Returns the message ID."""
    try:
        payload = json.dumps(intent, default=str)
        msg_id = await redis_client.xadd(
            STREAM_TRADE_INTENTS,
            {"payload": payload, "timestamp": datetime.now(timezone.utc).isoformat()},
        )
        logger.info("Published trade intent to %s: %s", STREAM_TRADE_INTENTS, msg_id)
        return msg_id
    except Exception as exc:
        logger.error("Failed to publish trade intent: %s", exc)
        return None


async def publish_watchlist(
    http_client: httpx.AsyncClient,
    broker_url: str,
    ticker: str,
    agent_id: str,
) -> bool:
    """POST ticker to broker-gateway watchlist. Returns True on success."""
    try:
        resp = await http_client.post(
            f"{broker_url}/watchlist",
            json={"ticker": ticker, "name": "Phoenix Watchlist"},
            timeout=10.0,
        )
        success = resp.status_code < 400
        if success:
            logger.info("Added %s to watchlist for agent %s", ticker, agent_id)
        else:
            logger.warning("Watchlist POST returned %d for %s", resp.status_code, ticker)
        return success
    except Exception as exc:
        logger.warning("Watchlist publish failed for %s: %s", ticker, exc)
        return False


async def publish_decision(
    redis_client: aioredis.Redis,
    agent_id: str,
    decision: dict,
) -> str | None:
    """XADD a decision event to the agent-messages stream."""
    try:
        payload = json.dumps(
            {
                "agent_id": agent_id,
                "type": "pipeline_decision",
                "decision": decision.get("action", "UNKNOWN"),
                "ticker": decision.get("ticker", ""),
                "reasons": decision.get("reasons", []),
                "confidence": decision.get("final_confidence", 0.0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            default=str,
        )
        msg_id = await redis_client.xadd(
            STREAM_AGENT_MESSAGES,
            {"payload": payload, "timestamp": datetime.now(timezone.utc).isoformat()},
        )
        return msg_id
    except Exception as exc:
        logger.error("Failed to publish decision for agent %s: %s", agent_id, exc)
        return None


async def log_to_api(
    http_client: httpx.AsyncClient,
    api_url: str,
    agent_id: str,
    log: dict,
) -> bool:
    """POST a structured log entry to the Phoenix API."""
    try:
        resp = await http_client.post(
            f"{api_url}/api/v2/agents/{agent_id}/logs",
            json=log,
            timeout=10.0,
        )
        return resp.status_code < 400
    except Exception as exc:
        logger.debug("API log failed for agent %s: %s", agent_id, exc)
        return False
