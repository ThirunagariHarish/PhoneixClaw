"""Leg-sizing for sum_to_one_arb.

Reference: docs/architecture/polymarket-tab.md section 9, Phase 8 (F3.1).

The agent buys equal share quantities on YES and NO. Per-pair notional is
roughly `cost_per_pair` dollars (since YES+NO ~ $1). We constrain the
pair count by, in order:

  1. Per-trade notional cap (the larger leg must fit). This is the
     PolymarketLayerRisk per-trade cap.
  2. Per-strategy notional cap minus already-open notional. Both legs
     count.
  3. Available top-of-book size on both sides.
  4. Kelly fraction of bankroll, given the edge.

The function is pure: takes literals, returns an int pair count. The
agent caller does the risk-chain double-check and the actual order
submission.
"""

from __future__ import annotations

from dataclasses import dataclass

from .detector import ArbOpportunity


@dataclass(frozen=True)
class SizingInputs:
    bankroll_usd: float
    max_trade_notional_usd: float
    max_strategy_notional_usd: float
    open_strategy_notional_usd: float
    kelly_cap: float


@dataclass(frozen=True)
class SizingResult:
    pair_qty: float
    yes_notional_usd: float
    no_notional_usd: float
    kelly_fraction: float
    reason: str  # "ok" or the binding constraint name


def size_arb_legs(opp: ArbOpportunity, inputs: SizingInputs) -> SizingResult:
    if opp.max_pair_qty <= 0:
        return SizingResult(0.0, 0.0, 0.0, 0.0, "no_top_of_book_size")

    # 1. Per-trade cap binds the *larger* leg.
    larger_leg_price = max(opp.yes_ask, opp.no_ask)
    if larger_leg_price <= 0:
        return SizingResult(0.0, 0.0, 0.0, 0.0, "non_positive_price")
    qty_from_per_trade = inputs.max_trade_notional_usd / larger_leg_price

    # 2. Per-strategy cap binds the *combined* notional. Both legs count.
    remaining_strategy = max(
        0.0, inputs.max_strategy_notional_usd - inputs.open_strategy_notional_usd
    )
    qty_from_per_strategy = remaining_strategy / opp.cost_per_pair if opp.cost_per_pair > 0 else 0.0

    # 3. Top-of-book size on both sides.
    qty_from_book = opp.max_pair_qty

    # 4. Kelly fraction of bankroll. For a discrete sum-to-one arb, edge is
    #    deterministic (modulo resolution risk gated separately by F9), so
    #    Kelly degenerates to a hard fraction-of-bankroll cap. We use the
    #    smaller of the configured cap and the edge fraction itself.
    kelly_fraction = min(inputs.kelly_cap, max(0.0, opp.edge_per_pair))
    kelly_budget = kelly_fraction * inputs.bankroll_usd
    qty_from_kelly = kelly_budget / opp.cost_per_pair if opp.cost_per_pair > 0 else 0.0

    candidates = {
        "per_trade_cap": qty_from_per_trade,
        "per_strategy_cap": qty_from_per_strategy,
        "top_of_book": qty_from_book,
        "kelly_cap": qty_from_kelly,
    }
    reason, pair_qty = min(candidates.items(), key=lambda kv: kv[1])

    if pair_qty <= 0:
        return SizingResult(0.0, 0.0, 0.0, kelly_fraction, reason)

    # Floor to whole shares — PM CLOB trades in fractional shares but
    # rounding down keeps us strictly inside every cap.
    pair_qty_floor = float(int(pair_qty))
    if pair_qty_floor <= 0:
        return SizingResult(0.0, 0.0, 0.0, kelly_fraction, "rounded_to_zero")

    yes_notional = pair_qty_floor * opp.yes_ask
    no_notional = pair_qty_floor * opp.no_ask
    return SizingResult(
        pair_qty=pair_qty_floor,
        yes_notional_usd=yes_notional,
        no_notional_usd=no_notional,
        kelly_fraction=kelly_fraction,
        reason="ok" if pair_qty_floor == int(pair_qty) else reason,
    )
