"""KalshiVenue — stub implementation (Phase 4).

The user does not have a Kalshi account, so v1.0 ships Kalshi as a
deliberately-disabled venue. The class exists so the scanner's
multi-venue plumbing is exercised end-to-end and so v1.x can drop in a
real implementation without touching the scanner.

Per Phase 4 DoD: must raise a clear, catchable error and must not break
the scanner. We use `NotConfiguredError`; the scanner logs and skips.
"""

from __future__ import annotations

from typing import AsyncIterator

from .base import MarketRow, MarketVenue, NotConfiguredError


class KalshiVenue(MarketVenue):
    """Stub venue. Always raises `NotConfiguredError` from `scan()`."""

    name = "kalshi"

    def __init__(self, *, reason: str | None = None) -> None:
        self._reason = reason or (
            "Kalshi venue is not configured in v1.0 (no account). "
            "See docs/architecture/polymarket-tab.md Phase 4 / Phase 9."
        )

    async def scan(self, *, limit: int = 500) -> AsyncIterator[MarketRow]:
        raise NotConfiguredError(self._reason)
        if False:  # pragma: no cover - make this an async generator for typing
            yield  # type: ignore[unreachable]
