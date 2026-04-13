"""Feature Store client — read/write cached ML features.

Provides a unified interface for writing feature groups and reading
joined feature vectors. Uses Redis for hot cache and PostgreSQL for
persistence.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

REDIS_TTL_SECONDS = 300  # 5-min hot cache
FEATURE_GROUPS = ["market_data", "technical", "options", "sentiment", "market_context"]


class FeatureStoreClient:
    """Read/write interface to the Feature Store (PG + Redis)."""

    def __init__(self, db_session: AsyncSession, redis_client: Optional[aioredis.Redis] = None):
        self._db = db_session
        self._redis = redis_client

    def _cache_key(self, ticker: str, group: str) -> str:
        return f"feature:{ticker.upper()}:{group}"

    async def write_features(
        self,
        ticker: str,
        feature_group: str,
        features: dict[str, Any],
        ttl_minutes: int = 5,
    ) -> None:
        """Write a feature group for a ticker to PG + Redis cache."""
        now = datetime.now(timezone.utc)
        valid_until = now + timedelta(minutes=ttl_minutes)
        ticker = ticker.upper()

        await self._db.execute(
            text("""
                INSERT INTO feature_store_features (ticker, feature_group, features, computed_at, valid_until, version)
                VALUES (:ticker, :group, :features, :computed_at, :valid_until, 1)
            """),
            {
                "ticker": ticker,
                "group": feature_group,
                "features": json.dumps(features, default=str),
                "computed_at": now,
                "valid_until": valid_until,
            },
        )
        await self._db.commit()

        if self._redis:
            try:
                await self._redis.setex(
                    self._cache_key(ticker, feature_group),
                    REDIS_TTL_SECONDS,
                    json.dumps(features, default=str),
                )
            except Exception as exc:
                log.warning("Redis cache write failed: %s", exc)

    async def read_features(
        self, ticker: str, feature_group: str
    ) -> Optional[dict[str, Any]]:
        """Read latest features for a ticker/group. Checks Redis first, falls back to PG."""
        ticker = ticker.upper()

        if self._redis:
            try:
                cached = await self._redis.get(self._cache_key(ticker, feature_group))
                if cached:
                    return json.loads(cached)
            except Exception as exc:
                log.warning("Redis read failed, falling back to PG: %s", exc)

        result = await self._db.execute(
            text("""
                SELECT features FROM feature_store_features
                WHERE ticker = :ticker AND feature_group = :group
                ORDER BY computed_at DESC LIMIT 1
            """),
            {"ticker": ticker, "group": feature_group},
        )
        row = result.fetchone()
        if row:
            features = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            if self._redis:
                try:
                    await self._redis.setex(
                        self._cache_key(ticker, feature_group),
                        REDIS_TTL_SECONDS,
                        json.dumps(features, default=str),
                    )
                except Exception:
                    pass
            return features
        return None

    async def read_feature_view(self, ticker: str) -> dict[str, Any]:
        """Read all feature groups for a ticker, join into single vector."""
        ticker = ticker.upper()
        merged: dict[str, Any] = {}
        for group in FEATURE_GROUPS:
            features = await self.read_features(ticker, group)
            if features:
                merged.update(features)
        return merged

    async def get_feature_freshness(self) -> list[dict[str, Any]]:
        """Return freshness info for each ticker/group combo in the store."""
        result = await self._db.execute(
            text("""
                SELECT ticker, feature_group,
                       MAX(computed_at) AS last_computed,
                       COUNT(*) AS total_rows
                FROM feature_store_features
                GROUP BY ticker, feature_group
                ORDER BY ticker, feature_group
            """)
        )
        return [
            {
                "ticker": r[0],
                "feature_group": r[1],
                "last_computed": r[2].isoformat() if r[2] else None,
                "total_rows": r[3],
            }
            for r in result.fetchall()
        ]
