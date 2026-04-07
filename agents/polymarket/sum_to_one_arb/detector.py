"""Pure detector for YES+NO < 1 arbitrage on Polymarket binary markets.

Reference: docs/architecture/polymarket-tab.md section 9, Phase 8 (F3.1).

The detector is intentionally pure: it takes a list of markets (each with
its YES and NO `BookSnapshot`) and returns `ArbOpportunity` objects sorted
by descending edge_bps. No DB, no network, no clock. The agent layer wraps
this with sizing, risk-chain, broker, and persistence.

Edge definition
---------------
For a binary market with YES asks and NO asks, the cheapest fillable price
to *acquire* one share of each side is `yes_ask + no_ask`. If

    yes_ask + no_ask + 2 * fee_rate * (yes_ask + no_ask) / 2 < 1

then buying both legs guarantees ~$1 payout per share-pair on resolution,
yielding an arbitrage profit. We fold the fee into the cost up front:

    cost_per_pair    = (yes_ask + no_ask) * (1 + fee_rate)
    edge_per_pair    = 1.0 - cost_per_pair
    edge_bps         = edge_per_pair / cost_per_pair * 10_000

`min_edge_bps` filters out marginal opportunities so we do not churn the
risk chain on noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from shared.polymarket.paper_fill import BookSnapshot


@dataclass(frozen=True)
class BinaryMarket:
    """Minimal binary-market view the detector consumes.

    `pm_market_id` is the internal `pm_markets.id` UUID (str-encoded so
    the detector stays UUID-library-agnostic). The two outcome token ids
    correspond to the YES and NO sides on Polymarket.
    """

    pm_market_id: str
    venue_market_id: str
    yes_token_id: str
    no_token_id: str
    yes_book: BookSnapshot
    no_book: BookSnapshot


@dataclass(frozen=True)
class ArbOpportunity:
    """A single detected YES+NO<1 arbitrage opportunity on one market."""

    pm_market_id: str
    venue_market_id: str
    yes_token_id: str
    no_token_id: str
    yes_ask: float
    no_ask: float
    yes_size_available: float
    no_size_available: float
    cost_per_pair: float
    edge_per_pair: float
    edge_bps: float

    @property
    def max_pair_qty(self) -> float:
        return min(self.yes_size_available, self.no_size_available)


class SumToOneDetector:
    """Scan binary markets for YES+NO<1 arbitrage."""

    def __init__(self, *, fee_rate: float = 0.02, min_edge_bps: float = 50.0) -> None:
        if fee_rate < 0:
            raise ValueError("fee_rate must be non-negative")
        if min_edge_bps < 0:
            raise ValueError("min_edge_bps must be non-negative")
        self.fee_rate = fee_rate
        self.min_edge_bps = min_edge_bps

    def scan(self, markets: Iterable[BinaryMarket]) -> list[ArbOpportunity]:
        opportunities: list[ArbOpportunity] = []
        for m in markets:
            opp = self._evaluate(m)
            if opp is not None:
                opportunities.append(opp)
        opportunities.sort(key=lambda o: o.edge_bps, reverse=True)
        return opportunities

    def _evaluate(self, m: BinaryMarket) -> ArbOpportunity | None:
        yes_top = m.yes_book.asks[0] if m.yes_book.asks else None
        no_top = m.no_book.asks[0] if m.no_book.asks else None
        if yes_top is None or no_top is None:
            return None

        yes_ask, yes_size = yes_top
        no_ask, no_size = no_top
        if yes_ask <= 0 or no_ask <= 0:
            return None
        if not (0.0 < yes_ask < 1.0 and 0.0 < no_ask < 1.0):
            return None

        raw_cost = yes_ask + no_ask
        cost_per_pair = raw_cost * (1.0 + self.fee_rate)
        if cost_per_pair >= 1.0:
            return None

        edge_per_pair = 1.0 - cost_per_pair
        edge_bps = (edge_per_pair / cost_per_pair) * 10_000.0
        if edge_bps < self.min_edge_bps:
            return None

        return ArbOpportunity(
            pm_market_id=m.pm_market_id,
            venue_market_id=m.venue_market_id,
            yes_token_id=m.yes_token_id,
            no_token_id=m.no_token_id,
            yes_ask=yes_ask,
            no_ask=no_ask,
            yes_size_available=yes_size,
            no_size_available=no_size,
            cost_per_pair=cost_per_pair,
            edge_per_pair=edge_per_pair,
            edge_bps=edge_bps,
        )
