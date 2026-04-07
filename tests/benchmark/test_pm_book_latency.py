"""Benchmark: book-update p95 < 50ms through the RTDS pipeline.

Reference: docs/architecture/polymarket-tab.md Phase 15 + PRD §3 v1.0
exit criteria.

Pipeline under test (mocked upstream):
  raw RTDS payload -> OrderBookState.apply_delta -> BookSnapshot.to_event

The "upstream" (websocket recv + JSON decode) is mocked because Phase 15
benchmarks measure pipeline-internal latency, not network. We pre-build
N delta payloads, then for each delta we measure the wall-clock cost of:
  1. apply_delta (sequence check + side merge + sort)
  2. to_event   (serialize for stream:pm:books)

p95 across all updates must stay under 50ms.

The test runs against a realistic book size (10 bid levels + 10 ask
levels per market, 50 simultaneous markets, 2000 sequential delta
updates) so the numbers are not trivially fast.
"""

from __future__ import annotations

import statistics
import time

import pytest

from services.connector_manager.src.brokers.polymarket.sequence_gap import (
    OrderBookState,
)

# How big the synthetic load is. Tunable but defaults are realistic.
N_MARKETS = 50
INITIAL_LEVELS = 10
N_DELTAS = 2_000


def _seed_state() -> OrderBookState:
    state = OrderBookState()
    for m in range(N_MARKETS):
        state.apply_snapshot(
            {
                "market_id": f"m{m}",
                "asset_id": f"m{m}-YES",
                "seq": 1,
                "ts_ms": 1_700_000_000_000,
                "bids": [
                    {"price": round(0.40 - i * 0.001, 4), "size": 100.0 + i}
                    for i in range(INITIAL_LEVELS)
                ],
                "asks": [
                    {"price": round(0.41 + i * 0.001, 4), "size": 100.0 + i}
                    for i in range(INITIAL_LEVELS)
                ],
            }
        )
    return state


def _build_delta_stream() -> list[dict]:
    deltas: list[dict] = []
    seqs: dict[str, int] = {f"m{m}": 1 for m in range(N_MARKETS)}
    for n in range(N_DELTAS):
        m = n % N_MARKETS
        market_id = f"m{m}"
        seqs[market_id] += 1
        # Alternate: tweak top bid, then tweak top ask, then add a level.
        kind = n % 3
        if kind == 0:
            bids = [{"price": 0.40, "size": 100.0 + (n % 50)}]
            asks = []
        elif kind == 1:
            bids = []
            asks = [{"price": 0.41, "size": 100.0 + (n % 50)}]
        else:
            bids = [{"price": round(0.39 - (n % 5) * 0.001, 4), "size": 25.0}]
            asks = [{"price": round(0.42 + (n % 5) * 0.001, 4), "size": 25.0}]
        deltas.append(
            {
                "market_id": market_id,
                "asset_id": f"{market_id}-YES",
                "seq": seqs[market_id],
                "ts_ms": 1_700_000_000_000 + n,
                "bids": bids,
                "asks": asks,
            }
        )
    return deltas


@pytest.mark.benchmark
def test_pm_book_update_p95_under_50ms():
    state = _seed_state()
    deltas = _build_delta_stream()

    timings_ms: list[float] = []
    for d in deltas:
        t0 = time.perf_counter()
        snap = state.apply_delta(d)
        _ = snap.to_event()
        t1 = time.perf_counter()
        timings_ms.append((t1 - t0) * 1000.0)

    timings_ms.sort()
    n = len(timings_ms)
    p50 = timings_ms[int(n * 0.50)]
    p95 = timings_ms[int(n * 0.95)]
    p99 = timings_ms[min(int(n * 0.99), n - 1)]
    mean = statistics.mean(timings_ms)

    # Useful diagnostic line if the assertion ever trips.
    print(
        f"\npm book update latency over {n} deltas: "
        f"mean={mean:.3f}ms p50={p50:.3f}ms p95={p95:.3f}ms p99={p99:.3f}ms"
    )

    assert p95 < 50.0, f"p95 book update {p95:.3f}ms exceeded 50ms budget"
