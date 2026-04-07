"""Benchmark: DiscoveryScanner processes >= 500 markets/min.

Reference: docs/architecture/polymarket-tab.md Phase 15 DoD —
"scanner throughput >= 500 markets/min asserted".

We use an in-memory `MarketVenue` that yields a large catalogue of
synthetic `MarketRow`s, attach the real `DiscoveryScanner` with the
default `EdgeFilters`, and time a single `scan_once` cycle. We then
extrapolate to a per-minute rate.

The default `DEFAULT_PER_VENUE_LIMIT` of 500 caps a single venue per
cycle, so we run the scanner against TWO venues each yielding 500 rows
(1_000 rows per cycle). The scanner is asked to complete the cycle and
we assert: rows_per_minute >= 500. In practice the scanner finishes
1_000 rows in well under a second so the realized rate is enormous;
the assertion is a hard floor that catches future regressions (a
catastrophic O(n^2) refactor would still be detected).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest

from services.connector_manager.src.discovery.scanner import (
    DiscoveryScanner,
    EdgeFilters,
)
from services.connector_manager.src.venues.base import MarketRow, MarketVenue

N_PER_VENUE = 500
N_VENUES = 2


def _make_row(venue: str, i: int) -> MarketRow:
    return MarketRow(
        venue=venue,
        venue_market_id=f"{venue}-mkt-{i}",
        question=f"Will event {i} on {venue} resolve YES?",
        slug=f"{venue}-{i}",
        category="benchmark",
        outcomes=[{"name": "Yes"}, {"name": "No"}],
        total_volume=10_000.0 + i,
        liquidity_usd=5_000.0,
        expiry=datetime.now(timezone.utc) + timedelta(days=7),
        best_bid=0.40,
        best_ask=0.42,
        is_active=True,
    )


class BulkVenue(MarketVenue):
    def __init__(self, name: str, n: int) -> None:
        self.name = name
        self._rows = [_make_row(name, i) for i in range(n)]

    async def scan(self, *, limit: int = 500) -> AsyncIterator[MarketRow]:
        for row in self._rows[:limit]:
            yield row

    async def aclose(self) -> None:
        return None


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_discovery_scanner_throughput_at_least_500_per_minute():
    venues = [BulkVenue(f"v{n}", N_PER_VENUE) for n in range(N_VENUES)]

    captured: list[MarketRow] = []

    async def sink(rows: list[MarketRow]) -> int:
        captured.extend(rows)
        return len(rows)

    scanner = DiscoveryScanner(
        venues,
        sink=sink,
        filters=EdgeFilters(),
        per_venue_limit=N_PER_VENUE,
    )

    t0 = time.perf_counter()
    result = await scanner.scan_once()
    t1 = time.perf_counter()

    elapsed_s = t1 - t0
    total_rows = result.total_scanned
    assert total_rows == N_PER_VENUE * N_VENUES, (
        f"expected {N_PER_VENUE * N_VENUES} rows scanned, got {total_rows}"
    )
    # Every synthetic row passes the default EdgeFilters.
    assert len(result.accepted) == total_rows
    assert result.persisted_count == total_rows

    rows_per_minute = (total_rows / elapsed_s) * 60.0 if elapsed_s > 0 else float("inf")
    print(
        f"\npm scanner throughput: {total_rows} rows in {elapsed_s * 1000:.1f}ms "
        f"-> {rows_per_minute:,.0f} rows/min"
    )

    assert rows_per_minute >= 500.0, (
        f"scanner throughput {rows_per_minute:.0f} rows/min below 500/min floor"
    )
