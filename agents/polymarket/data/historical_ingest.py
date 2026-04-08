"""Historical prediction-market ingestion pipeline (Phase 15.3).

Loads market data from a configured venue and upserts rows into the
``pm_historical_markets`` table, deduplicating by ``venue_market_id``.

Reference: docs/architecture/polymarket-phase15.md § 8 (Phase 15.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.polymarket import PMHistoricalMarket
from shared.polymarket.venue_registry import get_venue

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IngestResult:
    """Summary returned by :meth:`HistoricalIngestPipeline.run`."""

    total_fetched: int
    new_stored: int
    skipped_duplicates: int


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO-8601 date or datetime string to a :class:`datetime.date`.

    Returns ``None`` if *value* is missing or unparseable.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None


class HistoricalIngestPipeline:
    """Fetch prediction markets from a venue and persist them to the DB.

    Args:
        db_session: An active :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        venue_name: Registry name for the venue to pull from (default:
            ``"robinhood_predictions"``).
    """

    def __init__(self, db_session: AsyncSession, venue_name: str = "robinhood_predictions") -> None:
        self.db = db_session
        self.venue_name = venue_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, max_markets: int = 500) -> IngestResult:
        """Fetch up to *max_markets* from the venue and store new ones.

        Returns:
            :class:`IngestResult` with counts for fetched / stored / skipped.
        """
        venue = get_venue(self.venue_name)
        markets: list[dict[str, Any]] = await venue.fetch_markets(limit=max_markets)

        new_stored = await self._fetch_and_store(markets)
        skipped = len(markets) - new_stored

        logger.info(
            "historical_ingest venue=%s total_fetched=%d new_stored=%d skipped=%d",
            self.venue_name,
            len(markets),
            new_stored,
            skipped,
        )
        return IngestResult(
            total_fetched=len(markets),
            new_stored=new_stored,
            skipped_duplicates=skipped,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_and_store(self, markets: list[dict[str, Any]]) -> int:
        """Map venue dicts → ORM objects and persist new rows.

        Returns:
            Count of rows actually inserted (duplicates excluded).
        """
        count = 0
        for market in markets:
            venue_id: str = market.get("market_id", "")
            if not venue_id:
                logger.warning("historical_ingest skipping market with empty market_id")
                continue

            if await self._market_already_exists(venue_id):
                logger.debug("historical_ingest duplicate venue_market_id=%s — skipping", venue_id)
                continue

            yes_price = float(market["yes_price"]) if market.get("yes_price") is not None else None
            no_price = float(market["no_price"]) if market.get("no_price") is not None else None

            obj = PMHistoricalMarket(
                venue=market.get("venue") or self.venue_name,
                venue_market_id=venue_id,
                # title maps to question (the DB column name)
                question=market.get("title") or market.get("question") or "",
                # category maps to reference_class per field-mapping spec
                reference_class=market.get("category"),
                description=market.get("description"),
                volume_usd=float(market["volume"]) if market.get("volume") is not None else None,
                resolution_date=_parse_date(market.get("end_date")),
                outcomes_json=["Yes", "No"],
                # Store yes/no prices as a snapshot in price_history_json
                price_history_json=(
                    [{"yes": yes_price, "no": no_price}]
                    if yes_price is not None or no_price is not None
                    else []
                ),
            )
            self.db.add(obj)
            count += 1

        await self.db.flush()
        return count

    async def _market_already_exists(self, venue_id: str) -> bool:
        """Return ``True`` if a row with *venue_id* already exists in the DB."""
        stmt = select(PMHistoricalMarket.id).where(PMHistoricalMarket.venue_market_id == venue_id).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar() is not None
