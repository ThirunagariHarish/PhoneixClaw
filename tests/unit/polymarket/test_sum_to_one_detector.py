"""Unit tests for SumToOneDetector + size_arb_legs (Phase 8)."""

from __future__ import annotations

import pytest

from agents.polymarket.sum_to_one_arb.detector import (
    BinaryMarket,
    SumToOneDetector,
)
from agents.polymarket.sum_to_one_arb.sizing import SizingInputs, size_arb_legs
from shared.polymarket.paper_fill import BookSnapshot


def _market(
    *,
    yes_ask: float,
    no_ask: float,
    yes_size: float = 1000.0,
    no_size: float = 1000.0,
    pm_id: str = "m-1",
) -> BinaryMarket:
    return BinaryMarket(
        pm_market_id=pm_id,
        venue_market_id=f"venue-{pm_id}",
        yes_token_id=f"{pm_id}-YES",
        no_token_id=f"{pm_id}-NO",
        yes_book=BookSnapshot.from_lists(
            f"{pm_id}-YES",
            bids=[(yes_ask - 0.01, yes_size)],
            asks=[(yes_ask, yes_size)],
        ),
        no_book=BookSnapshot.from_lists(
            f"{pm_id}-NO",
            bids=[(no_ask - 0.01, no_size)],
            asks=[(no_ask, no_size)],
        ),
    )


class TestSumToOneDetector:
    def test_detects_clean_arb(self):
        det = SumToOneDetector(fee_rate=0.02, min_edge_bps=50.0)
        # 0.40 + 0.50 = 0.90; *(1.02) = 0.918 → 8.9% edge → ~890 bps
        opps = det.scan([_market(yes_ask=0.40, no_ask=0.50)])
        assert len(opps) == 1
        opp = opps[0]
        assert opp.yes_ask == 0.40
        assert opp.no_ask == 0.50
        assert opp.edge_bps > 800
        assert opp.cost_per_pair == pytest.approx(0.918, rel=1e-6)

    def test_ignores_no_arb(self):
        det = SumToOneDetector(fee_rate=0.02, min_edge_bps=50.0)
        # 0.55 + 0.46 = 1.01 → no arb
        assert det.scan([_market(yes_ask=0.55, no_ask=0.46)]) == []

    def test_min_edge_filter(self):
        det = SumToOneDetector(fee_rate=0.02, min_edge_bps=2000.0)
        # ~890 bps edge — filtered out
        assert det.scan([_market(yes_ask=0.40, no_ask=0.50)]) == []

    def test_fee_eats_edge(self):
        # Without fee 0.49 + 0.50 = 0.99 — only 100 bps. With 2% fee → cost
        # 1.0098 → no arb at all.
        det = SumToOneDetector(fee_rate=0.02, min_edge_bps=10.0)
        assert det.scan([_market(yes_ask=0.49, no_ask=0.50)]) == []

    def test_empty_book_ignored(self):
        det = SumToOneDetector(fee_rate=0.02, min_edge_bps=10.0)
        m = BinaryMarket(
            pm_market_id="x",
            venue_market_id="x",
            yes_token_id="xY",
            no_token_id="xN",
            yes_book=BookSnapshot.from_lists("xY", [], []),
            no_book=BookSnapshot.from_lists("xN", [], []),
        )
        assert det.scan([m]) == []

    def test_sorted_by_edge_desc(self):
        det = SumToOneDetector(fee_rate=0.02, min_edge_bps=10.0)
        small = _market(yes_ask=0.48, no_ask=0.48, pm_id="small")
        big = _market(yes_ask=0.30, no_ask=0.40, pm_id="big")
        opps = det.scan([small, big])
        assert [o.pm_market_id for o in opps] == ["big", "small"]

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            SumToOneDetector(fee_rate=-0.01)
        with pytest.raises(ValueError):
            SumToOneDetector(min_edge_bps=-1)


class TestSizing:
    def _opp(self, **overrides):
        det = SumToOneDetector(fee_rate=0.02, min_edge_bps=10.0)
        return det.scan([_market(yes_ask=0.40, no_ask=0.50, **overrides)])[0]

    def test_per_trade_cap_binds(self):
        opp = self._opp()
        result = size_arb_legs(
            opp,
            SizingInputs(
                bankroll_usd=10_000,
                max_trade_notional_usd=10.0,  # tight: $10 / $0.50 = 20 shares
                max_strategy_notional_usd=10_000,
                open_strategy_notional_usd=0,
                kelly_cap=1.0,
            ),
        )
        assert result.pair_qty == 20.0
        assert result.yes_notional_usd == pytest.approx(8.0)
        assert result.no_notional_usd == pytest.approx(10.0)

    def test_top_of_book_binds(self):
        opp = self._opp(yes_size=5.0, no_size=5.0)
        result = size_arb_legs(
            opp,
            SizingInputs(
                bankroll_usd=10_000,
                max_trade_notional_usd=1_000,
                max_strategy_notional_usd=1_000,
                open_strategy_notional_usd=0,
                kelly_cap=1.0,
            ),
        )
        assert result.pair_qty == 5.0

    def test_per_strategy_cap_with_open_notional(self):
        opp = self._opp()
        result = size_arb_legs(
            opp,
            SizingInputs(
                bankroll_usd=10_000,
                max_trade_notional_usd=1_000,
                max_strategy_notional_usd=100,
                open_strategy_notional_usd=91.8,  # $8.20 left → ~8 pairs
                kelly_cap=1.0,
            ),
        )
        # remaining = 8.2; pair cost = 0.918 → 8.93 → floor 8
        assert result.pair_qty == 8.0

    def test_kelly_cap_binds(self):
        opp = self._opp()
        result = size_arb_legs(
            opp,
            SizingInputs(
                bankroll_usd=100,
                max_trade_notional_usd=10_000,
                max_strategy_notional_usd=10_000,
                open_strategy_notional_usd=0,
                kelly_cap=0.05,  # 5% of $100 = $5 → ~5 pairs
            ),
        )
        assert result.pair_qty == 5.0
        assert result.kelly_fraction == pytest.approx(0.05)

    def test_zero_qty_when_strategy_full(self):
        opp = self._opp()
        result = size_arb_legs(
            opp,
            SizingInputs(
                bankroll_usd=10_000,
                max_trade_notional_usd=1_000,
                max_strategy_notional_usd=100,
                open_strategy_notional_usd=100,
                kelly_cap=1.0,
            ),
        )
        assert result.pair_qty == 0.0
