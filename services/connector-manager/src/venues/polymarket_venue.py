"""PolymarketVenue — `MarketVenue` backed by the Phase 2 GammaClient.

Pages through `/markets`, normalizes the Gamma payload into `MarketRow`,
and yields each row to the scanner. Pure metadata; no order book.

Phase 15.2 adds the extended venue interface (`fetch_markets`, `get_market`,
`place_order`, `get_positions`) backed by the public Polymarket CLOB API so the
venue registry can instantiate and use this class without a pre-wired GammaClient.

Reference: docs/architecture/polymarket-tab.md Phase 4.
Reference: docs/architecture/polymarket-phase15.md § 6, § 8.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

from ..brokers.polymarket.gamma_client import GammaClient, GammaClientError
from .base import MarketRow, MarketVenue, VenueError

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 100


class PolymarketVenue(MarketVenue):
    """Polymarket metadata venue with Phase-15.2 extended interface.

    The `scan()` method uses the GammaClient (Phase 2) for backwards
    compatibility with the DiscoveryScanner.  The Phase-15 extended methods
    (`fetch_markets`, `place_order`, `get_positions`) call the public
    Polymarket CLOB REST API directly so the venue can be instantiated
    standalone via the venue registry without a pre-wired GammaClient.
    """

    name = "polymarket"

    #: Public Polymarket CLOB markets endpoint (no auth required for reads).
    _CLOB_MARKETS_URL = "https://clob.polymarket.com/markets"

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

    # ------------------------------------------------------------------
    # Phase-15.2 extended venue interface
    # ------------------------------------------------------------------

    @property
    def venue_name(self) -> str:
        return "polymarket"

    @property
    def is_paper(self) -> bool:
        return True

    async def fetch_markets(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch active markets from the public Polymarket CLOB API.

        Returns an empty list on any network or HTTP error (logged as WARNING)
        so callers can degrade gracefully without crashing.

        Args:
            limit: Maximum number of market records to return.

        Returns:
            List of raw market dicts from the CLOB API.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._CLOB_MARKETS_URL, params={"limit": limit})
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 — network errors must not propagate
            logger.warning("polymarket fetch_markets failed: %s", exc)
            return []

        if isinstance(data, list):
            return data[:limit]
        # Some API versions return {"data": [...], "next_cursor": "..."}
        if isinstance(data, dict):
            markets = data.get("data") or data.get("markets") or []
            if isinstance(markets, list):
                return markets[:limit]
        return []

    async def place_order(
        self,
        market_id: str,
        side: str,
        amount: float,
        paper: bool = True,
    ) -> dict[str, Any]:
        """Simulate a Polymarket order in paper mode.

        Paper mode is MANDATORY in Phase 15.  Passing ``paper=False`` raises
        ``ValueError`` immediately — no order is placed and no money moves.

        Args:
            market_id: Polymarket condition ID or market ID string.
            side:      ``"yes"`` or ``"no"``.
            amount:    Dollar amount to simulate.
            paper:     Must be ``True``.

        Returns:
            A paper order receipt dict.

        Raises:
            ValueError: if ``paper=False`` or ``side`` is invalid.
        """
        if not paper:
            raise ValueError(
                "Live trading is blocked in Phase 15. "
                "PolymarketVenue only supports paper=True."
            )
        side_lower = side.lower()
        if side_lower not in {"yes", "no"}:
            raise ValueError(f"Invalid side {side!r}: must be 'yes' or 'no'.")
        if amount <= 0:
            raise ValueError(f"Amount must be positive, got {amount}.")

        order_id = str(uuid.uuid4())
        receipt: dict[str, Any] = {
            "order_id": order_id,
            "market_id": market_id,
            "side": side_lower,
            "amount": amount,
            "status": "filled",
            "filled_at": datetime.now(tz=timezone.utc).isoformat(),
            "paper": True,
            "venue": "polymarket",
        }
        logger.info(
            "polymarket paper_order order_id=%s market_id=%s side=%s amount=%.2f",
            order_id,
            market_id,
            side_lower,
            amount,
        )
        return receipt

    async def get_positions(self) -> list[dict[str, Any]]:
        """Return paper positions.  Always empty for stateless PolymarketVenue."""
        return []


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
