"""Unit tests for PaperFillSimulator (Phase 6)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.polymarket.paper_fill import (
    DEFAULT_FEE_RATE,
    BookSnapshot,
    PaperFillSimulator,
)


def _book(bids=None, asks=None, seq: int = 1) -> BookSnapshot:
    return BookSnapshot.from_lists(
        outcome_token_id="tok-1",
        bids=bids or [],
        asks=asks or [],
        sequence=seq,
    )


def _sim() -> PaperFillSimulator:
    fixed = datetime(2026, 4, 7, tzinfo=timezone.utc)
    return PaperFillSimulator(
        latency_slippage_bps=0.0,
        now_fn=lambda: fixed,
    )


def test_buy_full_fill_single_level():
    sim = _sim()
    book = _book(asks=[(0.40, 1000.0)])
    res = sim.simulate(side="BUY", qty_shares=100, limit_price=0.40, book=book)
    assert res.status == "FILLED"
    assert res.filled_qty == pytest.approx(100.0)
    assert res.avg_price == pytest.approx(0.40)
    assert res.notional_usd == pytest.approx(40.0)
    assert res.fees_paid_usd == pytest.approx(40.0 * DEFAULT_FEE_RATE)
    assert res.levels_consumed == 1
    assert res.sequence == 1


def test_buy_walks_multiple_levels_vwap():
    sim = _sim()
    book = _book(asks=[(0.40, 50.0), (0.42, 50.0), (0.50, 100.0)])
    res = sim.simulate(side="BUY", qty_shares=100, limit_price=0.45, book=book)
    assert res.status == "FILLED"
    assert res.filled_qty == pytest.approx(100.0)
    # VWAP across the first two levels.
    assert res.avg_price == pytest.approx((0.40 * 50 + 0.42 * 50) / 100)
    assert res.levels_consumed == 2


def test_buy_partial_when_book_thin():
    sim = _sim()
    book = _book(asks=[(0.40, 30.0)])
    res = sim.simulate(side="BUY", qty_shares=100, limit_price=0.40, book=book)
    assert res.status == "PARTIAL"
    assert res.filled_qty == pytest.approx(30.0)


def test_buy_rejected_when_limit_unmarketable():
    sim = _sim()
    book = _book(asks=[(0.50, 100.0)])
    res = sim.simulate(side="BUY", qty_shares=10, limit_price=0.40, book=book)
    assert res.status == "REJECTED"
    assert res.reason == "limit_unmarketable"


def test_sell_consumes_bids():
    sim = _sim()
    book = _book(bids=[(0.60, 100.0), (0.55, 100.0)])
    res = sim.simulate(side="SELL", qty_shares=50, limit_price=0.55, book=book)
    assert res.status == "FILLED"
    assert res.avg_price == pytest.approx(0.60)


def test_latency_slippage_applies_to_buy():
    sim = PaperFillSimulator(
        latency_slippage_bps=100.0,  # 1%
        now_fn=lambda: datetime(2026, 4, 7, tzinfo=timezone.utc),
    )
    book = _book(asks=[(0.40, 1000.0)])
    res = sim.simulate(side="BUY", qty_shares=10, limit_price=0.45, book=book)
    assert res.status == "FILLED"
    assert res.avg_price == pytest.approx(0.40 * 1.01)
    assert res.slippage_bps == pytest.approx(100.0, rel=1e-3)


def test_latency_slippage_can_blow_limit():
    sim = PaperFillSimulator(
        latency_slippage_bps=500.0,  # 5%
        now_fn=lambda: datetime(2026, 4, 7, tzinfo=timezone.utc),
    )
    book = _book(asks=[(0.40, 1000.0)])
    res = sim.simulate(side="BUY", qty_shares=10, limit_price=0.41, book=book)
    assert res.status == "REJECTED"
    assert res.reason == "slippage_exceeded_limit"


def test_invalid_inputs():
    sim = _sim()
    book = _book(asks=[(0.40, 100.0)])
    assert sim.simulate(side="HODL", qty_shares=1, limit_price=0.4, book=book).status == "REJECTED"
    assert sim.simulate(side="BUY", qty_shares=0, limit_price=0.4, book=book).status == "REJECTED"
    assert sim.simulate(side="BUY", qty_shares=1, limit_price=1.5, book=book).status == "REJECTED"
    empty = _book()
    assert sim.simulate(side="BUY", qty_shares=1, limit_price=0.4, book=empty).status == "REJECTED"


def test_book_snapshot_helpers():
    book = BookSnapshot.from_lists(
        "tok-x",
        bids=[(0.30, 10.0), (0.40, 10.0)],
        asks=[(0.50, 10.0), (0.45, 10.0)],
    )
    assert book.best_bid() == 0.40
    assert book.best_ask() == 0.45
    assert book.mid() == pytest.approx(0.425)
