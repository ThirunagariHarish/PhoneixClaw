"""PolymarketVenue — `MarketVenue` backed by the Phase 2 GammaClient.

Pages through `/markets`, normalizes the Gamma payload into `MarketRow`,
and yields each row to the scanner. Pure metadata; no order book.

Reference: docs/architecture/polymarket-tab.md Phase 4.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from ..brokers.polymarket.gamma_client import GammaClient, GammaClientError
from .base import MarketRow, MarketVenue, VenueError

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 100


class PolymarketVenue(MarketVenue):
    """Read-only Polymarket metadata venue."""

    name = "polymarket"

    def __init__(
        self,
        gamma_client: GammaClient | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        self._client = gamma_client or GammaClient()
        self._owns_client = gamma_client is None
        self._page_size = page_size

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def scan(self, *, limit: int = 500) -> AsyncIterator[MarketRow]:
        """Page through Gamma `/markets` until `limit` rows yielded."""
        offset = 0
        emitted = 0
        while emitted < limit:
            page_limit = min(self._page_size, limit - emitted)
            try:
                page = await self._client.list_markets(
                    active=True,
                    closed=False,
                    limit=page_limit,
                    offset=offset,
                )
            except GammaClientError as e:
                raise VenueError(f"polymarket scan failed: {e}") from e

            if not page:
                return

            for raw in page:
                try:
                    row = self._normalize(raw)
                except Exception as e:  # noqa: BLE001 - normalization is best-effort
                    logger.warning(
                        "polymarket_venue normalize_failed id=%s err=%s",
                        raw.get("id") or raw.get("conditionId"),
                        type(e).__name__,
                    )
                    continue
                emitted += 1
                yield row
                if emitted >= limit:
                    return

            if len(page) < page_limit:
                return
            offset += page_limit

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(raw: dict[str, Any]) -> MarketRow:
        venue_market_id = str(
            raw.get("conditionId") or raw.get("id") or raw.get("condition_id") or ""
        )
        if not venue_market_id:
            raise ValueError("missing venue_market_id")

        question = str(raw.get("question") or raw.get("title") or "").strip()
        if not question:
            raise ValueError("missing question")

        outcomes = _coerce_outcomes(raw)
        best_bid, best_ask = _extract_book_top(raw, outcomes)

        return MarketRow(
            venue="polymarket",
            venue_market_id=venue_market_id,
            question=question,
            slug=raw.get("slug"),
            category=raw.get("category") or raw.get("categoryName"),
            outcomes=outcomes,
            total_volume=_to_float(raw.get("volume") or raw.get("totalVolume")),
            liquidity_usd=_to_float(raw.get("liquidity") or raw.get("liquidityUsd")),
            expiry=_to_datetime(
                raw.get("endDate") or raw.get("end_date") or raw.get("endsAt")
            ),
            resolution_source=raw.get("resolutionSource") or raw.get("resolution_source"),
            oracle_type=raw.get("oracleType") or raw.get("oracle_type") or "uma",
            best_bid=best_bid,
            best_ask=best_ask,
            is_active=bool(raw.get("active", True)) and not bool(raw.get("closed", False)),
            raw=raw,
        )


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_datetime(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, str):
        s = v.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _coerce_outcomes(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Gamma serves outcomes in a few shapes. Normalize to a list of dicts."""
    outcomes = raw.get("outcomes")
    tokens = raw.get("clobTokenIds") or raw.get("tokens")
    if isinstance(outcomes, str):
        # Some Gamma payloads serialize as JSON-string arrays.
        import json

        try:
            outcomes = json.loads(outcomes)
        except ValueError:
            outcomes = [outcomes]
    if isinstance(tokens, str):
        import json

        try:
            tokens = json.loads(tokens)
        except ValueError:
            tokens = None

    result: list[dict[str, Any]] = []
    if isinstance(outcomes, list):
        for i, o in enumerate(outcomes):
            if isinstance(o, dict):
                entry = dict(o)
            else:
                entry = {"name": str(o)}
            if isinstance(tokens, list) and i < len(tokens) and "token_id" not in entry:
                entry["token_id"] = str(tokens[i])
            result.append(entry)
    return result


def _extract_book_top(
    raw: dict[str, Any], outcomes: list[dict[str, Any]]
) -> tuple[float | None, float | None]:
    """Best-effort top-of-book extraction from a Gamma market payload.

    Gamma exposes `bestBid` / `bestAsk` on some endpoints; on others the
    only price hint is `outcomePrices`. We accept either.
    """
    bid = _to_float(raw.get("bestBid") or raw.get("best_bid"))
    ask = _to_float(raw.get("bestAsk") or raw.get("best_ask"))
    if bid is not None or ask is not None:
        return bid, ask

    prices = raw.get("outcomePrices")
    if isinstance(prices, str):
        import json

        try:
            prices = json.loads(prices)
        except ValueError:
            prices = None
    if isinstance(prices, list) and prices:
        p = _to_float(prices[0])
        if p is not None:
            # Symmetric placeholder; spread will be 0 — scanner filters
            # treat that as "unknown spread" via min_spread logic.
            return p, p
    return None, None
