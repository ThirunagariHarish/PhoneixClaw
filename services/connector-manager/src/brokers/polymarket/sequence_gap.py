"""Local order book + sequence-gap detection for Polymarket RTDS.

Phase 3, Polymarket v1.0. Reference:
docs/architecture/polymarket-tab.md section 9, Phase 3 and risk row R-E.

Responsibilities (transport-agnostic, pure logic — no I/O):
  * Maintain a per-market local order book keyed by `(market_id, asset_id)`
    where `asset_id` is the CLOB token id (YES / NO outcome token).
  * Track the last applied RTDS sequence number per market.
  * Apply snapshot messages (full book) and delta messages (price-level
    changes) idempotently.
  * Detect gaps: if an incoming delta's `seq` is not exactly
    `last_seq + 1`, raise `SequenceGapError` so the websocket client can
    trigger a REST resync via the CLOB.
  * Normalize the resulting top-of-book + depth into a stable internal
    schema (`BookSnapshot`) that downstream consumers can rely on
    regardless of the upstream RTDS payload shape.

The websocket client (`rtds_ws.py`) owns transport, reconnect, backoff,
and resync orchestration. This module owns *state*. Splitting them keeps
the gap logic deterministic and unit-testable without a real socket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SequenceGapError(RuntimeError):
    """Raised when an RTDS delta arrives with a non-contiguous sequence.

    The websocket client catches this, drops the local book for the
    affected market, fetches a fresh snapshot via the CLOB REST endpoint,
    and resumes streaming. A second consecutive gap on the same market
    pauses PM strategies via the risk chain (see R-E).
    """

    def __init__(self, market_id: str, expected: int, got: int) -> None:
        super().__init__(
            f"sequence gap on market={market_id} expected={expected} got={got}"
        )
        self.market_id = market_id
        self.expected = expected
        self.got = got


class BookStateError(RuntimeError):
    """Raised on malformed RTDS payloads."""


# ---------------------------------------------------------------------------
# Normalized schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceLevel:
    """One side of one price level. Prices are USDC quotes in [0, 1]."""

    price: float
    size: float


@dataclass
class BookSnapshot:
    """Normalized book state for one (market_id, asset_id) pair.

    Emitted onto `stream:pm:books` after every applied update. The
    `seq` field lets downstream consumers detect their own ordering
    errors independent of RTDS.
    """

    market_id: str
    asset_id: str
    seq: int
    bids: list[PriceLevel] = field(default_factory=list)
    asks: list[PriceLevel] = field(default_factory=list)
    ts_ms: int = 0  # exchange timestamp; 0 if not provided

    def best_bid(self) -> PriceLevel | None:
        return self.bids[0] if self.bids else None

    def best_ask(self) -> PriceLevel | None:
        return self.asks[0] if self.asks else None

    def to_event(self) -> dict[str, Any]:
        """Serialize for `stream:pm:books`. All values are str/int/float."""
        return {
            "market_id": self.market_id,
            "asset_id": self.asset_id,
            "seq": self.seq,
            "ts_ms": self.ts_ms,
            "bids": [(lvl.price, lvl.size) for lvl in self.bids],
            "asks": [(lvl.price, lvl.size) for lvl in self.asks],
        }


# ---------------------------------------------------------------------------
# OrderBookState
# ---------------------------------------------------------------------------


def _book_key(market_id: str, asset_id: str) -> tuple[str, str]:
    return (market_id, asset_id)


def _coerce_levels(raw: Iterable[Any]) -> list[PriceLevel]:
    out: list[PriceLevel] = []
    for entry in raw:
        try:
            if isinstance(entry, dict):
                price = float(entry.get("price"))  # type: ignore[arg-type]
                size = float(entry.get("size"))  # type: ignore[arg-type]
            else:
                price = float(entry[0])
                size = float(entry[1])
        except (TypeError, ValueError, KeyError, IndexError) as e:
            raise BookStateError(f"malformed price level: {entry!r}") from e
        out.append(PriceLevel(price=price, size=size))
    return out


def _merge_side(
    existing: list[PriceLevel],
    deltas: list[PriceLevel],
    *,
    descending: bool,
) -> list[PriceLevel]:
    """Apply price-level deltas. size==0 deletes the level."""
    by_price: dict[float, float] = {lvl.price: lvl.size for lvl in existing}
    for lvl in deltas:
        if lvl.size == 0:
            by_price.pop(lvl.price, None)
        else:
            by_price[lvl.price] = lvl.size
    merged = [PriceLevel(price=p, size=s) for p, s in by_price.items()]
    merged.sort(key=lambda x: x.price, reverse=descending)
    return merged


class OrderBookState:
    """Holds local books for many markets and enforces sequence ordering.

    Thread/asyncio note: this object is not safe for concurrent mutation.
    The RTDS websocket client owns a single instance and applies updates
    serially from one consumer task.
    """

    def __init__(self) -> None:
        self._books: dict[tuple[str, str], BookSnapshot] = {}
        self._gap_strikes: dict[str, int] = {}

    # ---- introspection ---------------------------------------------------
    def get(self, market_id: str, asset_id: str) -> BookSnapshot | None:
        return self._books.get(_book_key(market_id, asset_id))

    def has(self, market_id: str, asset_id: str) -> bool:
        return _book_key(market_id, asset_id) in self._books

    def gap_strikes(self, market_id: str) -> int:
        """Number of consecutive unrecovered gaps on this market."""
        return self._gap_strikes.get(market_id, 0)

    def reset_market(self, market_id: str) -> None:
        """Drop all asset books for one market (used before resync)."""
        for key in [k for k in self._books if k[0] == market_id]:
            self._books.pop(key, None)

    # ---- snapshot apply --------------------------------------------------
    def apply_snapshot(self, payload: dict[str, Any]) -> BookSnapshot:
        """Replace the book for one (market_id, asset_id) wholesale.

        Snapshots do NOT clear gap strikes — strikes only clear when a
        *delta* successfully applies after a snapshot/resync, proving
        the live stream has recovered. This preserves the "double
        failure" semantics in R-E: a resync that is immediately followed
        by another gap counts as the second strike and trips the circuit.
        """
        market_id, asset_id, seq, ts_ms = _read_header(payload)
        bids = _coerce_levels(payload.get("bids", []) or [])
        asks = _coerce_levels(payload.get("asks", []) or [])
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        snap = BookSnapshot(
            market_id=market_id,
            asset_id=asset_id,
            seq=seq,
            bids=bids,
            asks=asks,
            ts_ms=ts_ms,
        )
        self._books[_book_key(market_id, asset_id)] = snap
        return snap

    # ---- delta apply -----------------------------------------------------
    def apply_delta(self, payload: dict[str, Any]) -> BookSnapshot:
        """Apply an incremental update.

        Raises:
          SequenceGapError: when `seq != last_seq + 1`.
          BookStateError: when no snapshot exists yet for this asset, or
            the payload is malformed.
        """
        market_id, asset_id, seq, ts_ms = _read_header(payload)
        key = _book_key(market_id, asset_id)
        existing = self._books.get(key)
        if existing is None:
            # No snapshot yet — treat as a forced resync.
            raise SequenceGapError(market_id, expected=0, got=seq)
        expected = existing.seq + 1
        if seq != expected:
            self._gap_strikes[market_id] = self._gap_strikes.get(market_id, 0) + 1
            raise SequenceGapError(market_id, expected=expected, got=seq)

        bids = _merge_side(
            existing.bids,
            _coerce_levels(payload.get("bids", []) or []),
            descending=True,
        )
        asks = _merge_side(
            existing.asks,
            _coerce_levels(payload.get("asks", []) or []),
            descending=False,
        )
        snap = BookSnapshot(
            market_id=market_id,
            asset_id=asset_id,
            seq=seq,
            bids=bids,
            asks=asks,
            ts_ms=ts_ms or existing.ts_ms,
        )
        self._books[key] = snap
        # Live stream has recovered — clear any prior gap strikes for this market.
        self._gap_strikes.pop(market_id, None)
        return snap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_header(payload: dict[str, Any]) -> tuple[str, str, int, int]:
    try:
        market_id = str(payload["market_id"])
        asset_id = str(payload["asset_id"])
        seq = int(payload["seq"])
    except (KeyError, TypeError, ValueError) as e:
        raise BookStateError(f"missing/invalid book header: {payload!r}") from e
    ts_ms = int(payload.get("ts_ms", 0) or 0)
    return market_id, asset_id, seq, ts_ms


__all__ = [
    "BookSnapshot",
    "BookStateError",
    "OrderBookState",
    "PriceLevel",
    "SequenceGapError",
]
