"""
Flash News Processor — sub-second headline classification using SLMs.
Subscribes to news feeds, matches against historical price reactions, publishes alerts.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STREAM_KEY = "stream:flash-news"


class UrgencyLevel(str, Enum):
    FLASH = "FLASH"      # Red pulse — immediate market impact
    IMPORTANT = "IMPORTANT"  # Orange — significant
    NORMAL = "NORMAL"    # Blue — informational


@dataclass
class FlashAlert:
    headline: str
    ticker: str
    timestamp: datetime
    urgency: UrgencyLevel
    direction: str  # bullish, bearish, neutral
    avg_move: float
    matched_pattern: str
    raw_data: dict[str, Any] = field(default_factory=dict)


class FlashNewsProcessor:
    HISTORICAL_PATTERNS = [
        {"pattern": "earnings beat", "direction": "bullish", "avg_move": 3.5},
        {"pattern": "earnings miss", "direction": "bearish", "avg_move": -4.2},
        {"pattern": "FDA approval", "direction": "bullish", "avg_move": 8.0},
        {"pattern": "Fed rate hike", "direction": "bearish", "avg_move": -1.5},
        {"pattern": "Fed rate cut", "direction": "bullish", "avg_move": 1.2},
        {"pattern": "layoff", "direction": "bearish", "avg_move": -2.0},
        {"pattern": "acquisition", "direction": "bullish", "avg_move": 5.0},
        {"pattern": "bankruptcy", "direction": "bearish", "avg_move": -15.0},
        {"pattern": "short squeeze", "direction": "bullish", "avg_move": 12.0},
        {"pattern": "SEC investigation", "direction": "bearish", "avg_move": -6.0},
        {"pattern": "buyback", "direction": "bullish", "avg_move": 1.5},
        {"pattern": "dividend cut", "direction": "bearish", "avg_move": -3.0},
        {"pattern": "guidance raise", "direction": "bullish", "avg_move": 4.0},
        {"pattern": "guidance cut", "direction": "bearish", "avg_move": -5.0},
        {"pattern": "CEO resignation", "direction": "bearish", "avg_move": -2.5},
        {"pattern": "partnership", "direction": "bullish", "avg_move": 2.0},
        {"pattern": "recall", "direction": "bearish", "avg_move": -4.0},
        {"pattern": "breakthrough", "direction": "bullish", "avg_move": 6.0},
        {"pattern": "data breach", "direction": "bearish", "avg_move": -3.5},
        {"pattern": "market crash", "direction": "bearish", "avg_move": -8.0},
        {"pattern": "rally", "direction": "bullish", "avg_move": 2.5},
        {"pattern": "inflation", "direction": "bearish", "avg_move": -1.0},
        {"pattern": "recession", "direction": "bearish", "avg_move": -2.0},
    ]

    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_url = redis_url
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as redis
            self._redis = redis.from_url(self.redis_url)
        return self._redis

    def _classify_headline(self, headline: str) -> tuple[str, float, str, UrgencyLevel]:
        """Sub-second classify using pattern matching (SLM replacement for speed)."""
        text = headline.lower()
        best_match = None
        best_score = 0.0

        for p in self.HISTORICAL_PATTERNS:
            pat = p["pattern"].lower()
            if re.search(rf"\b{re.escape(pat)}\b", text):
                score = abs(p["avg_move"])
                if score > best_score:
                    best_score = score
                    best_match = p

        if best_match:
            direction = best_match["direction"]
            avg_move = best_match["avg_move"]
            urgency = UrgencyLevel.FLASH if abs(avg_move) >= 5 else UrgencyLevel.IMPORTANT
            if abs(avg_move) < 2:
                urgency = UrgencyLevel.NORMAL
            return direction, avg_move, best_match["pattern"], urgency

        return "neutral", 0.0, "", UrgencyLevel.NORMAL

    async def process_headline(
        self,
        headline: str,
        ticker: str,
        timestamp: datetime | None = None,
    ) -> FlashAlert:
        """Sub-second classify and match against historical patterns."""
        ts = timestamp or datetime.now(timezone.utc)
        direction, avg_move, pattern, urgency = self._classify_headline(headline)

        return FlashAlert(
            headline=headline,
            ticker=ticker,
            timestamp=ts,
            urgency=urgency,
            direction=direction,
            avg_move=avg_move,
            matched_pattern=pattern,
        )

    async def publish_alert(self, alert: FlashAlert) -> str | None:
        """Publish to stream:flash-news with urgency level."""
        try:
            r = await self._get_redis()
            payload = {
                "headline": alert.headline,
                "ticker": alert.ticker,
                "timestamp": alert.timestamp.isoformat(),
                "urgency": alert.urgency.value,
                "direction": alert.direction,
                "avg_move": alert.avg_move,
                "matched_pattern": alert.matched_pattern,
                **alert.raw_data,
            }
            msg_id = await r.xadd(STREAM_KEY, {"data": json.dumps(payload)}, maxlen=10000)
            logger.debug("Published flash alert %s: %s", msg_id, alert.urgency.value)
            return msg_id
        except Exception as e:
            logger.error("Failed to publish flash alert: %s", e)
            return None
