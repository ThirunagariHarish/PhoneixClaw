"""
Kill Switch — emergency position liquidation trigger.

When activated, publishes to Redis ``stream:kill-switch`` so every
downstream service can halt trading immediately.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class KillSwitch:
    """Global emergency stop for the trading system."""

    def __init__(self, redis_client: redis.Redis | None = None):
        self._redis = redis_client
        self._active: bool = False
        self._reason: str = ""
        self._activated_at: datetime | None = None
        self._history: list[dict[str, Any]] = []

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def activated_at(self) -> datetime | None:
        return self._activated_at

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    async def activate(self, reason: str) -> None:
        """Activate the kill switch and publish to Redis."""
        now = datetime.now(timezone.utc)
        self._active = True
        self._reason = reason
        self._activated_at = now
        self._history.append({
            "action": "activate",
            "reason": reason,
            "timestamp": now.isoformat(),
        })

        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

        if self._redis:
            await self._redis.xadd(
                "stream:kill-switch",
                {
                    "action": "activate",
                    "reason": reason,
                    "timestamp": now.isoformat(),
                },
            )

    async def deactivate(self) -> None:
        """Deactivate the kill switch and publish to Redis."""
        now = datetime.now(timezone.utc)
        prev_reason = self._reason
        self._active = False
        self._reason = ""
        self._activated_at = None
        self._history.append({
            "action": "deactivate",
            "previous_reason": prev_reason,
            "timestamp": now.isoformat(),
        })

        logger.warning("Kill switch deactivated (was: %s)", prev_reason)

        if self._redis:
            await self._redis.xadd(
                "stream:kill-switch",
                {
                    "action": "deactivate",
                    "previous_reason": prev_reason,
                    "timestamp": now.isoformat(),
                },
            )

    def status(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "reason": self._reason,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
            "activation_count": sum(1 for h in self._history if h["action"] == "activate"),
        }
