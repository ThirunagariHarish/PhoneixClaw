"""
PaperFillSimulator (Polymarket v1.0 — Phase 6).

Reference: docs/architecture/polymarket-tab.md sections 4.3, 9 (Phase 6).

Goal
====
Given a desired PM order intent and a *local snapshot* of the order book for
the target outcome token, simulate a realistic fill: walk the opposing side
of the book, respect the limit price, accumulate fees, and report the
resulting average fill price, slippage in basis points, and remaining qty.

This module is intentionally pure: no DB, no network, no clock dependency
beyond an injectable `now_fn` for the timestamp on the result. The risk
chain (`PolymarketLayerRisk`) routes every PAPER intent through here.

Book snapshot shape
-------------------
A `BookSnapshot` carries `bids` and `asks` as lists of `(price, size)`
tuples sorted best-first (bids descending, asks ascending). Prices are
quoted in dollars per share in [0, 1] (PM convention). Sizes are share
quantities.

Slippage model
--------------
1. Walk the opposing side until either the requested qty is filled or the
   next level is worse than the limit price.
2. Add a fixed bps of *adverse* slippage on top of the VWAP to account for
   real-world micro-latency between snapshot and fill. Default is 5 bps;
   override per-call for stress tests.
3. Apply the per-trade fee from `shared.polymarket.fees` (flat 2% in v1.0,
   user decision; can be replaced with a Gamma-fetched schedule later).

Returns a `PaperFillResult` describing fill qty, average price, fees,
slippage, and a `status` of `FILLED`, `PARTIAL`, or `REJECTED`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

# Default extra adverse slippage (latency model). Basis points of price.
DEFAULT_LATENCY_SLIPPAGE_BPS = 5.0

# Flat PM fee in v1.0 (user decision). 2% on notional.
DEFAULT_FEE_RATE = 0.02


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BookSnapshot:
    """A frozen book snapshot for a single outcome token.

    `bids` are (price, size) sorted descending; `asks` ascending.
    Prices are dollars-per-share in [0, 1]. Sizes are shares.
    """

    outcome_token_id: str
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    sequence: int = 0

    @classmethod
    def from_lists(
        cls,
        outcome_token_id: str,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
        sequence: int = 0,
    ) -> "BookSnapshot":
        sorted_bids = tuple(sorted(bids, key=lambda lvl: -lvl[0]))
        sorted_asks = tuple(sorted(asks, key=lambda lvl: lvl[0]))
        return cls(outcome_token_id, sorted_bids, sorted_asks, sequence)

    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    def mid(self) -> Optional[float]:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0


@dataclass(frozen=True)
class PaperFillResult:
    status: str  # FILLED | PARTIAL | REJECTED
    filled_qty: float
    avg_price: float
    notional_usd: float
    fees_paid_usd: float
    slippage_bps: float
    reason: str
    filled_at: datetime
    sequence: int = 0
    levels_consumed: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "filled_qty": self.filled_qty,
            "avg_price": self.avg_price,
            "notional_usd": self.notional_usd,
            "fees_paid_usd": self.fees_paid_usd,
            "slippage_bps": self.slippage_bps,
            "reason": self.reason,
            "filled_at": self.filled_at.isoformat(),
            "sequence": self.sequence,
            "levels_consumed": self.levels_consumed,
        }


@dataclass
class PaperFillSimulator:
    """Simulate a PM order against a local book snapshot.

    Stateless wrt orders; one instance can be reused.
    """

    fee_rate: float = DEFAULT_FEE_RATE
    latency_slippage_bps: float = DEFAULT_LATENCY_SLIPPAGE_BPS
    now_fn: Callable[[], datetime] = field(default=_utcnow)

    def simulate(
        self,
        *,
        side: str,
        qty_shares: float,
        limit_price: float,
        book: BookSnapshot,
    ) -> PaperFillResult:
        side_u = side.upper()
        if side_u not in ("BUY", "SELL"):
            return self._reject(f"invalid_side:{side}")
        if qty_shares <= 0:
            return self._reject("non_positive_qty")
        if not (0.0 <= limit_price <= 1.0):
            return self._reject(f"limit_out_of_range:{limit_price}")

        # BUY consumes asks (must be <= limit), SELL consumes bids (>= limit).
        if side_u == "BUY":
            levels = book.asks
            price_ok = lambda px: px <= limit_price  # noqa: E731
        else:
            levels = book.bids
            price_ok = lambda px: px >= limit_price  # noqa: E731

        if not levels:
            return self._reject("empty_book")

        remaining = qty_shares
        cost = 0.0
        consumed = 0
        for price, size in levels:
            if not price_ok(price):
                break
            take = min(remaining, size)
            if take <= 0:
                break
            cost += take * price
            remaining -= take
            consumed += 1
            if remaining <= 1e-12:
                break

        filled = qty_shares - remaining
        if filled <= 0:
            return self._reject("limit_unmarketable")

        vwap = cost / filled
        # Apply adverse latency slippage: BUY pays more, SELL receives less.
        bps_factor = self.latency_slippage_bps / 10_000.0
        if side_u == "BUY":
            adj_price = min(1.0, vwap * (1.0 + bps_factor))
            # Re-check the limit after slippage; if blown, treat as REJECTED.
            if adj_price > limit_price:
                return self._reject("slippage_exceeded_limit")
        else:
            adj_price = max(0.0, vwap * (1.0 - bps_factor))
            if adj_price < limit_price:
                return self._reject("slippage_exceeded_limit")

        notional = adj_price * filled
        fees = notional * self.fee_rate

        # Slippage vs the *touch* (best opposing price at snapshot time).
        touch = levels[0][0]
        if touch > 0:
            slippage_bps = abs(adj_price - touch) / touch * 10_000.0
        else:
            slippage_bps = 0.0

        status = "FILLED" if remaining <= 1e-12 else "PARTIAL"
        reason = "ok" if status == "FILLED" else "book_exhausted_or_limit"

        return PaperFillResult(
            status=status,
            filled_qty=filled,
            avg_price=adj_price,
            notional_usd=notional,
            fees_paid_usd=fees,
            slippage_bps=slippage_bps,
            reason=reason,
            filled_at=self.now_fn(),
            sequence=book.sequence,
            levels_consumed=consumed,
        )

    def _reject(self, reason: str) -> PaperFillResult:
        return PaperFillResult(
            status="REJECTED",
            filled_qty=0.0,
            avg_price=0.0,
            notional_usd=0.0,
            fees_paid_usd=0.0,
            slippage_bps=0.0,
            reason=reason,
            filled_at=self.now_fn(),
        )
