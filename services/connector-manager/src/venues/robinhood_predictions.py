"""RobinhoodPredictionsVenue — paper-mode-only prediction market venue (Phase 15.2).

Robinhood Predictions does not yet expose a public API.  This implementation
uses a deterministic hardcoded mock data set so tests are reproducible and the
venue can be exercised end-to-end in the discovery scanner without any network
access.

Paper mode is MANDATORY.  `place_order(paper=False)` always raises `ValueError`.

Reference: docs/architecture/polymarket-phase15.md § 6 (Venue Layer), § 8 (Phase 15.2).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from .base import MarketRow, MarketVenue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deterministic reference date so every run produces the same end_dates.
# Tests must not depend on wall-clock "today".
# ---------------------------------------------------------------------------
_ANCHOR_DATE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _end(days: int) -> str:
    """Return ISO-8601 date string relative to the anchor date."""
    return (_ANCHOR_DATE + timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Hardcoded mock market catalogue (15 markets, four categories)
# ---------------------------------------------------------------------------
_MOCK_MARKETS: list[dict[str, Any]] = [
    # ── Politics ────────────────────────────────────────────────────────────
    {
        "market_id": "rh-pol-001",
        "title": "Will the US Senate pass a balanced-budget amendment in 2025?",
        "category": "politics",
        "yes_price": 0.08,
        "no_price": 0.92,
        "volume": 128_500,
        "end_date": _end(150),
        "description": (
            "Resolves YES if the US Senate passes a balanced-budget constitutional "
            "amendment by 31 December 2025."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-pol-002",
        "title": "Will the US House pass major immigration reform legislation by mid-2025?",
        "category": "politics",
        "yes_price": 0.31,
        "no_price": 0.69,
        "volume": 245_000,
        "end_date": _end(90),
        "description": (
            "Resolves YES if a comprehensive immigration reform bill passes the US "
            "House of Representatives before 1 July 2025."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-pol-003",
        "title": "Will any US state successfully ban social-media access for minors under 16 in 2025?",
        "category": "politics",
        "yes_price": 0.55,
        "no_price": 0.45,
        "volume": 89_200,
        "end_date": _end(120),
        "description": (
            "Resolves YES if any US state enacts and has a law take effect banning "
            "social-media platform access for users under 16 by 31 December 2025."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-pol-004",
        "title": "Will the UK hold a second Brexit-related referendum before end of 2026?",
        "category": "politics",
        "yes_price": 0.07,
        "no_price": 0.93,
        "volume": 47_300,
        "end_date": _end(180),
        "description": (
            "Resolves YES if the UK government officially schedules or holds a national "
            "referendum on EU-UK trade or membership relations before 31 December 2026."
        ),
        "venue": "robinhood",
    },
    # ── Economics ────────────────────────────────────────────────────────────
    {
        "market_id": "rh-eco-001",
        "title": "Will the Federal Reserve cut rates at the March 2025 FOMC meeting?",
        "category": "economics",
        "yes_price": 0.22,
        "no_price": 0.78,
        "volume": 412_000,
        "end_date": _end(75),
        "description": (
            "Resolves YES if the Federal Open Market Committee votes to lower the "
            "federal funds rate target range at the March 2025 scheduled meeting."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-eco-002",
        "title": "Will US CPI inflation exceed 3.5% year-over-year in Q1 2025?",
        "category": "economics",
        "yes_price": 0.38,
        "no_price": 0.62,
        "volume": 177_800,
        "end_date": _end(95),
        "description": (
            "Resolves YES if the Bureau of Labor Statistics reports US CPI (all items) "
            "year-over-year growth above 3.5% for any month in Q1 2025."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-eco-003",
        "title": "Will US Q1 2025 GDP growth (annualised) exceed 2.5%?",
        "category": "economics",
        "yes_price": 0.61,
        "no_price": 0.39,
        "volume": 203_400,
        "end_date": _end(110),
        "description": (
            "Resolves YES if the Bureau of Economic Analysis advance estimate of "
            "annualised real GDP growth for Q1 2025 is above 2.5%."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-eco-004",
        "title": "Will the European Central Bank cut rates twice or more before June 2025?",
        "category": "economics",
        "yes_price": 0.48,
        "no_price": 0.52,
        "volume": 155_700,
        "end_date": _end(130),
        "description": (
            "Resolves YES if the ECB Governing Council cuts the main refinancing rate "
            "at least twice between January 2025 and 30 June 2025."
        ),
        "venue": "robinhood",
    },
    # ── Sports ───────────────────────────────────────────────────────────────
    {
        "market_id": "rh-spt-001",
        "title": "Will the Kansas City Chiefs win Super Bowl LIX?",
        "category": "sports",
        "yes_price": 0.27,
        "no_price": 0.73,
        "volume": 498_000,
        "end_date": _end(40),
        "description": (
            "Resolves YES if the Kansas City Chiefs are declared champions of Super "
            "Bowl LIX played in February 2025."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-spt-002",
        "title": "Will Real Madrid win the 2024-25 UEFA Champions League?",
        "category": "sports",
        "yes_price": 0.34,
        "no_price": 0.66,
        "volume": 321_000,
        "end_date": _end(145),
        "description": (
            "Resolves YES if Real Madrid CF are crowned UEFA Champions League winners "
            "at the final in May 2025."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-spt-003",
        "title": "Will an NBA team other than the Boston Celtics win the 2025 championship?",
        "category": "sports",
        "yes_price": 0.76,
        "no_price": 0.24,
        "volume": 267_500,
        "end_date": _end(160),
        "description": (
            "Resolves YES if any NBA franchise other than the Boston Celtics is crowned "
            "2024-25 NBA champion."
        ),
        "venue": "robinhood",
    },
    # ── Geopolitics ──────────────────────────────────────────────────────────
    {
        "market_id": "rh-geo-001",
        "title": "Will Russia and Ukraine sign a ceasefire agreement in 2025?",
        "category": "geopolitics",
        "yes_price": 0.19,
        "no_price": 0.81,
        "volume": 374_200,
        "end_date": _end(165),
        "description": (
            "Resolves YES if Russia and Ukraine publicly agree to and implement a "
            "formal ceasefire lasting at least 30 days before 31 December 2025."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-geo-002",
        "title": "Will Taiwan experience a major military incident with China in 2025?",
        "category": "geopolitics",
        "yes_price": 0.12,
        "no_price": 0.88,
        "volume": 188_900,
        "end_date": _end(170),
        "description": (
            "Resolves YES if credible international media report a kinetic military "
            "incident between Chinese and Taiwanese forces in 2025."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-geo-003",
        "title": "Will Saudi Arabia and Israel normalise diplomatic relations by end of 2025?",
        "category": "geopolitics",
        "yes_price": 0.29,
        "no_price": 0.71,
        "volume": 142_600,
        "end_date": _end(175),
        "description": (
            "Resolves YES if Saudi Arabia and Israel formally establish full diplomatic "
            "relations (exchange of ambassadors) before 31 December 2025."
        ),
        "venue": "robinhood",
    },
    {
        "market_id": "rh-geo-004",
        "title": "Will North Korea conduct a nuclear weapons test in 2025?",
        "category": "geopolitics",
        "yes_price": 0.14,
        "no_price": 0.86,
        "volume": 96_400,
        "end_date": _end(180),
        "description": (
            "Resolves YES if North Korea carries out a confirmed underground nuclear "
            "weapons test detected by seismic monitoring agencies in 2025."
        ),
        "venue": "robinhood",
    },
]

# Index by market_id for O(1) lookup
_MOCK_MARKET_INDEX: dict[str, dict[str, Any]] = {m["market_id"]: m for m in _MOCK_MARKETS}


class RobinhoodPredictionsVenue(MarketVenue):
    """Paper-mode Robinhood Predictions venue.

    Uses a deterministic mock data set because Robinhood Predictions does not
    expose a public API.  All order placement is simulated in memory.

    This class satisfies the `MarketVenue` ABC (`scan`) **and** exposes the
    extended Phase-15 venue interface (`fetch_markets`, `get_market`,
    `place_order`, `get_positions`).
    """

    name = "robinhood_predictions"

    def __init__(self) -> None:
        # In-memory paper order book: order_id -> order receipt dict
        self._paper_orders: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # MarketVenue ABC
    # ------------------------------------------------------------------

    async def scan(self, *, limit: int = 500) -> AsyncIterator[MarketRow]:  # type: ignore[override]
        """Yield MarketRow objects from mock data up to `limit`."""
        for raw in _MOCK_MARKETS[:limit]:
            yield self._to_market_row(raw)

    # ------------------------------------------------------------------
    # Extended Phase-15 venue interface
    # ------------------------------------------------------------------

    @property
    def venue_name(self) -> str:
        return "robinhood_predictions"

    @property
    def is_paper(self) -> bool:
        return True

    async def fetch_markets(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return up to `limit` mock prediction market contracts."""
        return list(_MOCK_MARKETS[:limit])

    async def get_market(self, market_id: str) -> dict[str, Any]:
        """Fetch a single market by ID.

        Raises:
            KeyError: if `market_id` is not found in the mock catalogue.
        """
        market = _MOCK_MARKET_INDEX.get(market_id)
        if market is None:
            raise KeyError(f"Market not found in Robinhood Predictions mock: {market_id!r}")
        return dict(market)

    async def place_order(
        self,
        market_id: str,
        side: str,
        amount: float,
        paper: bool = True,
    ) -> dict[str, Any]:
        """Simulate a prediction market order.

        Paper mode is MANDATORY in Phase 15.  Passing ``paper=False`` raises
        ``ValueError`` immediately — no order is placed and no money moves.

        Args:
            market_id: Robinhood Predictions contract ID (e.g. ``"rh-pol-001"``).
            side:      ``"yes"`` or ``"no"``.
            amount:    Dollar amount to simulate buying.
            paper:     Must be ``True``.  Passing ``False`` raises ``ValueError``.

        Returns:
            A dict order receipt with keys ``order_id``, ``market_id``, ``side``,
            ``amount``, ``status``, ``filled_at``, ``paper``.

        Raises:
            ValueError: if ``paper=False`` or ``side`` is not ``"yes"``/``"no"``.
            KeyError:   if ``market_id`` does not exist in the mock catalogue.
        """
        if not paper:
            raise ValueError(
                "Live trading is blocked in Phase 15. "
                "RobinhoodPredictionsVenue only supports paper=True."
            )
        side_lower = side.lower()
        if side_lower not in {"yes", "no"}:
            raise ValueError(f"Invalid side {side!r}: must be 'yes' or 'no'.")
        if amount <= 0:
            raise ValueError(f"Amount must be positive, got {amount}.")

        # Verify the market exists (raises KeyError if not)
        market = await self.get_market(market_id)
        price = market["yes_price"] if side_lower == "yes" else market["no_price"]

        order_id = str(uuid.uuid4())
        receipt: dict[str, Any] = {
            "order_id": order_id,
            "market_id": market_id,
            "side": side_lower,
            "amount": amount,
            "price": price,
            "contracts": round(amount / price, 6) if price > 0 else 0.0,
            "status": "filled",
            "filled_at": datetime.now(tz=timezone.utc).isoformat(),
            "paper": True,
            "venue": "robinhood_predictions",
        }
        self._paper_orders[order_id] = receipt
        logger.info(
            "robinhood_predictions paper_order order_id=%s market_id=%s side=%s amount=%.2f",
            order_id,
            market_id,
            side_lower,
            amount,
        )
        return receipt

    async def get_positions(self) -> list[dict[str, Any]]:
        """Return all paper positions accumulated since this instance was created."""
        return list(self._paper_orders.values())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_market_row(raw: dict[str, Any]) -> MarketRow:
        from datetime import datetime, timezone

        def _parse_date(s: str) -> datetime | None:
            try:
                return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                return None

        yes_price = float(raw.get("yes_price", 0.5))
        no_price = float(raw.get("no_price", 0.5))

        return MarketRow(
            venue="robinhood_predictions",
            venue_market_id=raw["market_id"],
            question=raw["title"],
            category=raw.get("category"),
            outcomes=[
                {"name": "Yes", "price": yes_price},
                {"name": "No", "price": no_price},
            ],
            total_volume=float(raw.get("volume", 0)),
            expiry=_parse_date(raw.get("end_date", "")),
            best_bid=no_price,
            best_ask=yes_price,
            is_active=True,
            raw=raw,
        )
