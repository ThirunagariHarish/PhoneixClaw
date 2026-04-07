"""MarketVenue ABC and the unified `MarketRow` shape (Phase 4).

`MarketRow` is the venue-agnostic discovery record produced by every
`MarketVenue.scan()` call. The `DiscoveryScanner` consumes these and
upserts them into `pm_markets` (see `shared/db/models/polymarket.py`).

The interface is intentionally tiny so adding a new venue (Kalshi,
Manifold, etc.) is a single-file change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator


class VenueError(RuntimeError):
    """Base error for venue implementations."""


class NotConfiguredError(VenueError):
    """Venue is shipped but not usable in this deployment.

    Used by the Kalshi stub. The `DiscoveryScanner` catches this and
    skips the venue without failing the whole scan cycle.
    """


@dataclass(frozen=True)
class MarketRow:
    """Unified market metadata record produced by every venue.

    All fields except `venue`, `venue_market_id`, and `question` are
    optional because Gamma / Kalshi / Manifold expose different subsets.
    Edge filters in the scanner tolerate `None` by treating the market
    as ineligible for that filter.
    """

    venue: str
    venue_market_id: str
    question: str
    slug: str | None = None
    category: str | None = None
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    total_volume: float | None = None
    liquidity_usd: float | None = None
    expiry: datetime | None = None
    resolution_source: str | None = None
    oracle_type: str | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    is_active: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def spread(self) -> float | None:
        """Best-ask minus best-bid; None if either side missing."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid


@dataclass
class VenueScanResult:
    """Outcome of a single venue scan call."""

    venue: str
    rows: list[MarketRow]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class MarketVenue(ABC):
    """Pluggable market-venue interface.

    Implementations MUST be safe to call from a long-lived asyncio task
    and MUST tolerate transient network errors by raising `VenueError`
    (the scanner converts that into a per-venue failure without killing
    the cycle).
    """

    #: Short, lowercase venue name. Mirrors `pm_markets.venue`.
    name: str = "abstract"

    @abstractmethod
    async def scan(self, *, limit: int = 500) -> AsyncIterator[MarketRow]:
        """Yield `MarketRow`s for this venue's currently-active markets.

        Implementations should respect `limit` as a soft cap on rows
        returned per scan call (so per-venue throughput is bounded).
        Must be implemented as an async generator.
        """
        raise NotImplementedError
        # pragma: no cover - abstract; the `yield` below makes mypy
        # treat the body as a generator.
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]

    async def aclose(self) -> None:
        """Release any owned resources. Default: no-op."""
        return None
