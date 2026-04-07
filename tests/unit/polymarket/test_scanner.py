"""Unit tests for Phase 4 DiscoveryScanner + MarketVenue + PolymarketVenue.

No network, no DB. Uses an in-memory fake venue for scanner behaviour
and an httpx.MockTransport for PolymarketVenue normalization.

Reference: docs/architecture/polymarket-tab.md Phase 4 DoD.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import httpx
import pytest

from services.connector_manager.src.brokers.polymarket.gamma_client import GammaClient
from services.connector_manager.src.discovery.scanner import (
    DiscoveryScanner,
    EdgeFilters,
)
from services.connector_manager.src.venues.base import (
    MarketRow,
    MarketVenue,
    NotConfiguredError,
    VenueError,
)
from services.connector_manager.src.venues.kalshi_venue import KalshiVenue
from services.connector_manager.src.venues.polymarket_venue import PolymarketVenue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row(
    *,
    market_id: str = "mkt-1",
    volume: float | None = 5_000.0,
    expiry_days: float | None = 7.0,
    bid: float | None = 0.40,
    ask: float | None = 0.42,
    active: bool = True,
    venue: str = "polymarket",
) -> MarketRow:
    expiry = None
    if expiry_days is not None:
        expiry = datetime.now(timezone.utc) + timedelta(days=expiry_days)
    return MarketRow(
        venue=venue,
        venue_market_id=market_id,
        question=f"Will {market_id} happen?",
        total_volume=volume,
        expiry=expiry,
        best_bid=bid,
        best_ask=ask,
        is_active=active,
        outcomes=[{"name": "Yes"}, {"name": "No"}],
    )


class FakeVenue(MarketVenue):
    """In-memory venue for scanner tests."""

    def __init__(self, name: str, rows: list[MarketRow], *, raise_after: int | None = None):
        self.name = name
        self._rows = rows
        self._raise_after = raise_after
        self.scan_calls = 0
        self.closed = False

    async def scan(self, *, limit: int = 500) -> AsyncIterator[MarketRow]:
        self.scan_calls += 1
        emitted = 0
        for row in self._rows[:limit]:
            if self._raise_after is not None and emitted >= self._raise_after:
                raise VenueError(f"{self.name} exploded after {emitted}")
            emitted += 1
            yield row

    async def aclose(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# EdgeFilters
# ---------------------------------------------------------------------------
class TestEdgeFilters:
    def test_passes_happy_row(self):
        assert EdgeFilters().evaluate(_row()) is None

    def test_rejects_inactive(self):
        assert EdgeFilters().evaluate(_row(active=False)) == "inactive"

    def test_rejects_low_volume(self):
        assert EdgeFilters().evaluate(_row(volume=10.0)) == "volume_below_min"

    def test_rejects_unknown_volume(self):
        assert EdgeFilters().evaluate(_row(volume=None)) == "volume_unknown"

    def test_rejects_expiry_too_soon(self):
        assert EdgeFilters().evaluate(_row(expiry_days=0.01)) == "expiry_too_soon"

    def test_rejects_expiry_too_far(self):
        assert EdgeFilters().evaluate(_row(expiry_days=9999)) == "expiry_too_far"

    def test_rejects_unknown_expiry(self):
        assert EdgeFilters().evaluate(_row(expiry_days=None)) == "expiry_unknown"

    def test_rejects_wide_spread(self):
        assert (
            EdgeFilters().evaluate(_row(bid=0.1, ask=0.9)) == "spread_too_wide"
        )

    def test_allows_unknown_spread(self):
        # spread unknown is OK — F9 / RTDS will re-check later.
        assert EdgeFilters().evaluate(_row(bid=None, ask=None)) is None

    def test_disabled_filters_pass_everything(self):
        f = EdgeFilters(
            min_volume_usd=None,
            min_days_to_resolution=None,
            max_days_to_resolution=None,
            max_spread=None,
            require_active=False,
        )
        assert f.evaluate(_row(active=False, volume=None, expiry_days=None)) is None


# ---------------------------------------------------------------------------
# DiscoveryScanner
# ---------------------------------------------------------------------------
class TestDiscoveryScanner:
    @pytest.mark.asyncio
    async def test_requires_at_least_one_venue(self):
        with pytest.raises(ValueError):
            DiscoveryScanner([])

    @pytest.mark.asyncio
    async def test_scan_once_collects_and_filters(self):
        good = _row(market_id="good", volume=10_000)
        bad = _row(market_id="bad", volume=10)  # filtered
        venue = FakeVenue("polymarket", [good, bad])
        captured: list[MarketRow] = []

        async def sink(rows):
            captured.extend(rows)
            return len(rows)

        scanner = DiscoveryScanner([venue], sink=sink)
        result = await scanner.scan_once()

        assert venue.scan_calls == 1
        assert result.total_scanned == 2
        assert len(result.accepted) == 1
        assert result.accepted[0].venue_market_id == "good"
        assert result.rejected == {"volume_below_min": 1}
        assert result.persisted_count == 1
        assert captured == result.accepted
        assert result.venue_errors == []

    @pytest.mark.asyncio
    async def test_per_venue_failure_is_isolated(self):
        survivor = FakeVenue("polymarket", [_row(market_id=f"m{i}") for i in range(3)])
        crasher = FakeVenue(
            "other", [_row(market_id=f"x{i}", venue="other") for i in range(5)], raise_after=2
        )

        async def sink(rows):
            return len(rows)

        scanner = DiscoveryScanner([survivor, crasher], sink=sink)
        result = await scanner.scan_once()

        # survivor yielded all rows; crasher yielded some then errored
        by_venue = {v.venue: v for v in result.venues}
        assert by_venue["polymarket"].error is None
        assert len(by_venue["polymarket"].rows) == 3
        assert by_venue["other"].error is not None
        assert "exploded" in by_venue["other"].error
        assert len(by_venue["other"].rows) == 2  # partial rows preserved
        # Survivor rows still flow to sink
        assert len(result.accepted) >= 3

    @pytest.mark.asyncio
    async def test_kalshi_stub_skipped_without_breaking_cycle(self):
        polymarket = FakeVenue("polymarket", [_row(market_id="good")])
        kalshi = KalshiVenue()

        scanner = DiscoveryScanner([polymarket, kalshi])
        result = await scanner.scan_once()

        by_venue = {v.venue: v for v in result.venues}
        assert "not_configured" in (by_venue["kalshi"].error or "")
        assert by_venue["polymarket"].error is None
        assert len(result.accepted) == 1

    @pytest.mark.asyncio
    async def test_sink_exception_does_not_kill_cycle(self):
        venue = FakeVenue("polymarket", [_row(market_id="good")])

        async def bad_sink(rows):
            raise RuntimeError("db down")

        scanner = DiscoveryScanner([venue], sink=bad_sink)
        result = await scanner.scan_once()
        assert result.persisted_count == 0
        assert len(result.accepted) == 1  # still collected

    @pytest.mark.asyncio
    async def test_aclose_closes_venues(self):
        v1 = FakeVenue("polymarket", [])
        v2 = FakeVenue("other", [])
        scanner = DiscoveryScanner([v1, v2])
        await scanner.aclose()
        assert v1.closed and v2.closed


# ---------------------------------------------------------------------------
# KalshiVenue stub
# ---------------------------------------------------------------------------
class TestKalshiVenue:
    @pytest.mark.asyncio
    async def test_scan_raises_not_configured(self):
        venue = KalshiVenue()
        with pytest.raises(NotConfiguredError):
            async for _ in venue.scan():
                pass

    def test_name_is_kalshi(self):
        assert KalshiVenue().name == "kalshi"


# ---------------------------------------------------------------------------
# PolymarketVenue (via mocked GammaClient)
# ---------------------------------------------------------------------------
def _gamma_mock_client(pages: list[list[dict]]) -> GammaClient:
    """Build a GammaClient whose /markets returns the given pages in order."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/markets"
        idx = call_count["n"]
        call_count["n"] += 1
        if idx >= len(pages):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://gamma-api.polymarket.com")
    return GammaClient(client=client)


class TestPolymarketVenue:
    @pytest.mark.asyncio
    async def test_normalizes_and_paginates(self):
        page1 = [
            {
                "conditionId": "0xabc",
                "question": "Will X happen?",
                "slug": "will-x",
                "category": "Politics",
                "outcomes": ["Yes", "No"],
                "clobTokenIds": ["t1", "t2"],
                "volume": "12345.6",
                "liquidity": 500.0,
                "endDate": "2027-01-01T00:00:00Z",
                "active": True,
                "closed": False,
                "bestBid": 0.40,
                "bestAsk": 0.42,
                "oracleType": "uma",
            },
            {
                "conditionId": "0xdef",
                "question": "Will Y happen?",
                "outcomes": ["Yes", "No"],
                "volume": 1000,
                "endDate": "2027-02-01T00:00:00Z",
                "active": True,
            },
        ]
        page2: list[dict] = []  # terminates pagination

        venue = PolymarketVenue(gamma_client=_gamma_mock_client([page1, page2]), page_size=100)
        rows = []
        async for r in venue.scan(limit=500):
            rows.append(r)
        await venue.aclose()

        assert len(rows) == 2
        r0 = rows[0]
        assert r0.venue == "polymarket"
        assert r0.venue_market_id == "0xabc"
        assert r0.slug == "will-x"
        assert r0.category == "Politics"
        assert r0.total_volume == pytest.approx(12345.6)
        assert r0.liquidity_usd == 500.0
        assert r0.best_bid == 0.40 and r0.best_ask == 0.42
        assert r0.spread == pytest.approx(0.02)
        assert r0.expiry is not None and r0.expiry.year == 2027
        assert r0.oracle_type == "uma"
        assert len(r0.outcomes) == 2
        assert r0.outcomes[0]["token_id"] == "t1"

    @pytest.mark.asyncio
    async def test_limit_is_honored(self):
        page = [
            {"conditionId": f"id{i}", "question": f"Q{i}", "active": True}
            for i in range(20)
        ]
        venue = PolymarketVenue(gamma_client=_gamma_mock_client([page]), page_size=100)
        rows = [r async for r in venue.scan(limit=5)]
        await venue.aclose()
        assert len(rows) == 5

    @pytest.mark.asyncio
    async def test_bad_row_is_skipped_not_fatal(self):
        page = [
            {"conditionId": "", "question": "bad — no id"},  # dropped
            {"conditionId": "ok", "question": "good", "active": True},
        ]
        venue = PolymarketVenue(gamma_client=_gamma_mock_client([page, []]), page_size=100)
        rows = [r async for r in venue.scan(limit=10)]
        await venue.aclose()
        assert len(rows) == 1
        assert rows[0].venue_market_id == "ok"

    @pytest.mark.asyncio
    async def test_http_error_raises_venue_error(self):
        def handler(request):
            return httpx.Response(503, json={"err": "nope"})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="https://gamma-api.polymarket.com")
        venue = PolymarketVenue(gamma_client=GammaClient(client=client))
        with pytest.raises(VenueError):
            async for _ in venue.scan(limit=10):
                pass
        await venue.aclose()
