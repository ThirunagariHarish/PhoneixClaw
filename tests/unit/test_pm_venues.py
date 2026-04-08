"""Unit tests for Phase 15.2 prediction-market venue adapters.

Covers:
- RobinhoodPredictionsVenue mock data quality and paper order flow
- PolymarketVenue.fetch_markets HTTP error handling
- shared.polymarket.venue_registry get_venue happy/sad path

No network access.  PolymarketVenue HTTP calls are intercepted via
`respx` (already in dev-dependencies) or `unittest.mock.patch`.

Reference: docs/architecture/polymarket-phase15.md § 8 (Phase 15.2 DoD).
asyncio_mode = "auto" — no @pytest.mark.asyncio decorator needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.connector_manager.src.venues.robinhood_predictions import (
    RobinhoodPredictionsVenue,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_MARKET_FIELDS = {"market_id", "title", "category", "yes_price", "no_price", "volume", "end_date", "venue"}


# ---------------------------------------------------------------------------
# RobinhoodPredictionsVenue — fetch_markets
# ---------------------------------------------------------------------------


async def test_robinhood_fetch_markets_returns_list() -> None:
    """fetch_markets returns a non-empty list of dicts with all required fields."""
    venue = RobinhoodPredictionsVenue()
    markets = await venue.fetch_markets(limit=50)

    assert isinstance(markets, list)
    assert len(markets) > 0

    for market in markets:
        missing = REQUIRED_MARKET_FIELDS - set(market.keys())
        assert not missing, f"Market {market.get('market_id')} is missing fields: {missing}"


async def test_robinhood_fetch_markets_respects_limit() -> None:
    """fetch_markets respects the limit parameter."""
    venue = RobinhoodPredictionsVenue()
    markets = await venue.fetch_markets(limit=5)
    assert len(markets) <= 5


async def test_robinhood_fetch_markets_default_limit() -> None:
    """fetch_markets with default limit=50 returns all mock markets (≤50)."""
    venue = RobinhoodPredictionsVenue()
    markets = await venue.fetch_markets()
    # Mock catalogue has 15 markets; all should be returned when limit=50.
    assert 10 <= len(markets) <= 50


# ---------------------------------------------------------------------------
# RobinhoodPredictionsVenue — data quality
# ---------------------------------------------------------------------------


async def test_robinhood_market_ids_are_unique() -> None:
    """No two markets in the mock catalogue share the same market_id."""
    venue = RobinhoodPredictionsVenue()
    markets = await venue.fetch_markets()
    ids = [m["market_id"] for m in markets]
    assert len(ids) == len(set(ids)), "Duplicate market_ids found in mock data"


async def test_robinhood_prices_in_range() -> None:
    """Both yes_price and no_price are strictly between 0.01 and 0.99."""
    venue = RobinhoodPredictionsVenue()
    markets = await venue.fetch_markets()
    for m in markets:
        assert 0.01 <= m["yes_price"] <= 0.99, (
            f"{m['market_id']}: yes_price={m['yes_price']} out of range"
        )
        assert 0.01 <= m["no_price"] <= 0.99, (
            f"{m['market_id']}: no_price={m['no_price']} out of range"
        )


async def test_robinhood_venue_field_is_set() -> None:
    """Every mock market has venue == 'robinhood'."""
    venue = RobinhoodPredictionsVenue()
    markets = await venue.fetch_markets()
    for m in markets:
        assert m["venue"] == "robinhood", f"{m['market_id']}: unexpected venue {m['venue']!r}"


async def test_robinhood_categories_are_valid() -> None:
    """All markets belong to one of the four expected categories."""
    valid_categories = {"politics", "economics", "sports", "geopolitics"}
    venue = RobinhoodPredictionsVenue()
    markets = await venue.fetch_markets()
    for m in markets:
        assert m["category"] in valid_categories, (
            f"{m['market_id']}: unexpected category {m['category']!r}"
        )


# ---------------------------------------------------------------------------
# RobinhoodPredictionsVenue — get_market
# ---------------------------------------------------------------------------


async def test_robinhood_get_market_returns_correct_record() -> None:
    """get_market returns the matching market dict."""
    venue = RobinhoodPredictionsVenue()
    all_markets = await venue.fetch_markets()
    first = all_markets[0]

    result = await venue.get_market(first["market_id"])
    assert result["market_id"] == first["market_id"]
    assert result["title"] == first["title"]


async def test_robinhood_get_market_raises_on_unknown_id() -> None:
    """get_market raises KeyError for an unknown market_id."""
    venue = RobinhoodPredictionsVenue()
    with pytest.raises(KeyError):
        await venue.get_market("nonexistent-market-id-xyz")


# ---------------------------------------------------------------------------
# RobinhoodPredictionsVenue — place_order (paper mode)
# ---------------------------------------------------------------------------


async def test_robinhood_place_order_paper_mode() -> None:
    """place_order(paper=True) returns a valid order receipt dict."""
    venue = RobinhoodPredictionsVenue()
    receipt = await venue.place_order("rh-pol-001", side="yes", amount=50.0)

    assert isinstance(receipt, dict)
    assert receipt["paper"] is True
    assert receipt["market_id"] == "rh-pol-001"
    assert receipt["side"] == "yes"
    assert receipt["amount"] == 50.0
    assert receipt["status"] == "filled"
    assert "order_id" in receipt
    assert "filled_at" in receipt
    assert receipt["venue"] == "robinhood_predictions"


async def test_robinhood_place_order_rejects_live() -> None:
    """place_order raises ValueError immediately when paper=False."""
    venue = RobinhoodPredictionsVenue()
    with pytest.raises(ValueError, match="Live trading is blocked"):
        await venue.place_order("rh-pol-001", side="yes", amount=50.0, paper=False)


async def test_robinhood_place_order_rejects_invalid_side() -> None:
    """place_order raises ValueError for an invalid side string."""
    venue = RobinhoodPredictionsVenue()
    with pytest.raises(ValueError, match="Invalid side"):
        await venue.place_order("rh-pol-001", side="maybe", amount=10.0)


async def test_robinhood_place_order_rejects_non_positive_amount() -> None:
    """place_order raises ValueError when amount <= 0."""
    venue = RobinhoodPredictionsVenue()
    with pytest.raises(ValueError, match="Amount must be positive"):
        await venue.place_order("rh-pol-001", side="no", amount=0.0)


async def test_robinhood_place_order_no_side() -> None:
    """place_order(side='no') fills correctly."""
    venue = RobinhoodPredictionsVenue()
    receipt = await venue.place_order("rh-eco-001", side="no", amount=100.0)
    assert receipt["side"] == "no"
    assert receipt["amount"] == 100.0


# ---------------------------------------------------------------------------
# RobinhoodPredictionsVenue — get_positions
# ---------------------------------------------------------------------------


async def test_robinhood_get_positions_empty_initially() -> None:
    """A fresh venue instance has no paper positions."""
    venue = RobinhoodPredictionsVenue()
    positions = await venue.get_positions()
    assert positions == []


async def test_robinhood_get_positions_tracks_placed_orders() -> None:
    """Placed paper orders show up in get_positions."""
    venue = RobinhoodPredictionsVenue()
    await venue.place_order("rh-pol-001", side="yes", amount=25.0)
    await venue.place_order("rh-eco-001", side="no", amount=75.0)
    positions = await venue.get_positions()
    assert len(positions) == 2
    order_ids = {p["order_id"] for p in positions}
    assert len(order_ids) == 2  # both orders have distinct IDs


# ---------------------------------------------------------------------------
# RobinhoodPredictionsVenue — venue metadata properties
# ---------------------------------------------------------------------------


def test_robinhood_venue_name_property() -> None:
    """venue_name returns 'robinhood_predictions'."""
    venue = RobinhoodPredictionsVenue()
    assert venue.venue_name == "robinhood_predictions"


def test_robinhood_is_paper_property() -> None:
    """is_paper is always True."""
    venue = RobinhoodPredictionsVenue()
    assert venue.is_paper is True


def test_robinhood_name_class_attribute() -> None:
    """MarketVenue ABC `name` attribute is set correctly."""
    assert RobinhoodPredictionsVenue.name == "robinhood_predictions"


# ---------------------------------------------------------------------------
# RobinhoodPredictionsVenue — scan() (MarketVenue ABC)
# ---------------------------------------------------------------------------


async def test_robinhood_scan_yields_market_rows() -> None:
    """scan() yields MarketRow objects for all mock markets."""
    from services.connector_manager.src.venues.base import MarketRow

    venue = RobinhoodPredictionsVenue()
    rows = []
    async for row in venue.scan(limit=500):
        rows.append(row)

    assert len(rows) > 0
    for row in rows:
        assert isinstance(row, MarketRow)
        assert row.venue == "robinhood_predictions"
        assert row.venue_market_id
        assert row.question


async def test_robinhood_scan_respects_limit() -> None:
    """scan() yields at most `limit` rows."""
    venue = RobinhoodPredictionsVenue()
    rows = []
    async for row in venue.scan(limit=3):
        rows.append(row)
    assert len(rows) <= 3


# ---------------------------------------------------------------------------
# PolymarketVenue — fetch_markets HTTP error handling
# ---------------------------------------------------------------------------


async def test_polymarket_fetch_markets_handles_network_error() -> None:
    """fetch_markets returns an empty list when httpx raises a network error."""
    from services.connector_manager.src.venues.polymarket_venue import PolymarketVenue

    venue = PolymarketVenue.__new__(PolymarketVenue)  # skip __init__ (needs GammaClient)

    with patch("services.connector_manager.src.venues.polymarket_venue.httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.get.side_effect = httpx.ConnectError("Simulated network failure")
        mock_client_cls.return_value = mock_client_instance

        result = await venue.fetch_markets(limit=10)

    assert result == []


async def test_polymarket_fetch_markets_handles_http_error() -> None:
    """fetch_markets returns an empty list on a non-2xx HTTP response."""
    from services.connector_manager.src.venues.polymarket_venue import PolymarketVenue

    venue = PolymarketVenue.__new__(PolymarketVenue)

    with patch("services.connector_manager.src.venues.polymarket_venue.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=MagicMock(),
            response=MagicMock(),
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client_instance

        result = await venue.fetch_markets(limit=10)

    assert result == []


async def test_polymarket_fetch_markets_returns_list_on_success() -> None:
    """fetch_markets returns parsed market list on a successful API response."""
    from services.connector_manager.src.venues.polymarket_venue import PolymarketVenue

    venue = PolymarketVenue.__new__(PolymarketVenue)

    fake_markets = [
        {"conditionId": "abc123", "question": "Will X happen?", "active": True},
        {"conditionId": "def456", "question": "Will Y happen?", "active": True},
    ]

    with patch("services.connector_manager.src.venues.polymarket_venue.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = fake_markets

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client_instance

        result = await venue.fetch_markets(limit=10)

    assert len(result) == 2
    assert result[0]["conditionId"] == "abc123"


async def test_polymarket_place_order_paper_mode() -> None:
    """PolymarketVenue.place_order returns a valid receipt in paper mode."""
    from services.connector_manager.src.venues.polymarket_venue import PolymarketVenue

    venue = PolymarketVenue.__new__(PolymarketVenue)
    receipt = await venue.place_order("market-abc", side="yes", amount=50.0)

    assert receipt["paper"] is True
    assert receipt["market_id"] == "market-abc"
    assert receipt["side"] == "yes"
    assert receipt["venue"] == "polymarket"
    assert receipt["status"] == "filled"


async def test_polymarket_place_order_rejects_live() -> None:
    """PolymarketVenue.place_order raises ValueError when paper=False."""
    from services.connector_manager.src.venues.polymarket_venue import PolymarketVenue

    venue = PolymarketVenue.__new__(PolymarketVenue)
    with pytest.raises(ValueError, match="Live trading is blocked"):
        await venue.place_order("market-abc", side="yes", amount=50.0, paper=False)


# ---------------------------------------------------------------------------
# Venue registry
# ---------------------------------------------------------------------------


def test_venue_registry_get_known_venue_robinhood() -> None:
    """get_venue('robinhood_predictions') returns a RobinhoodPredictionsVenue."""
    from shared.polymarket.venue_registry import get_venue

    venue = get_venue("robinhood_predictions")
    assert isinstance(venue, RobinhoodPredictionsVenue)


def test_venue_registry_get_known_venue_polymarket() -> None:
    """get_venue('polymarket') returns a PolymarketVenue."""
    from services.connector_manager.src.venues.polymarket_venue import PolymarketVenue
    from shared.polymarket.venue_registry import get_venue

    venue = get_venue("polymarket")
    assert isinstance(venue, PolymarketVenue)


def test_venue_registry_unknown_raises() -> None:
    """get_venue raises ValueError for an unrecognised venue name."""
    from shared.polymarket.venue_registry import get_venue

    with pytest.raises(ValueError, match="Unknown venue"):
        get_venue("nonexistent_venue_xyz")


def test_venue_registry_unknown_message_lists_known() -> None:
    """ValueError message includes the list of known venue names."""
    from shared.polymarket.venue_registry import get_venue

    with pytest.raises(ValueError) as exc_info:
        get_venue("mystery_venue")

    msg = str(exc_info.value)
    assert "robinhood_predictions" in msg
    assert "polymarket" in msg


def test_venue_registry_dict_populated_after_get() -> None:
    """VENUE_REGISTRY dict is populated after the first get_venue call."""
    import shared.polymarket.venue_registry as reg

    # Force population (may already be populated from earlier tests)
    reg.get_venue("robinhood_predictions")

    assert "robinhood_predictions" in reg.VENUE_REGISTRY
    assert "polymarket" in reg.VENUE_REGISTRY
