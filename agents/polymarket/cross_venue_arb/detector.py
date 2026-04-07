"""Cross-venue spread detector — scaffold (Phase 9).

This module pairs Polymarket markets against a *second* venue (Kalshi in
v1.x) using the `MarketVenue` interface from Phase 4 and emits
`CrossVenueOpportunity` records when the implied spread exceeds the
configured edge threshold.

DISABLED-by-default behavior:

* `CrossVenueArbDetector.scan()` MUST fail fast with
  `CrossVenueDisabledError` when the configured secondary venue is not
  configured (e.g., the Kalshi stub raises `NotConfiguredError`). The
  message must be human-readable and reference Phase 9.
* The detector itself is venue-agnostic: it accepts any two
  `MarketVenue` implementations, so unit tests use two fakes and v1.x
  can drop in real Kalshi without touching this file.

See `docs/architecture/polymarket-tab.md` Phase 9 and risk R-I.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from services.connector_manager.src.venues.base import (  # type: ignore[import-not-found]
    MarketRow,
    MarketVenue,
    NotConfiguredError,
)

from .config import CrossVenueArbConfig


class CrossVenueDisabledError(RuntimeError):
    """Raised when the secondary venue is not usable in this deployment.

    The orchestrator catches this, logs once, and leaves the agent in
    STOPPED state (Phase 9 DoD).
    """


@dataclass(frozen=True)
class CrossVenueOpportunity:
    """A detected spread between the same event on two venues."""

    primary_venue: str
    secondary_venue: str
    primary_market_id: str
    secondary_market_id: str
    question: str
    primary_ask: float
    secondary_bid: float
    edge_bps: int
    notional_cap_usd: float

    @property
    def raw_edge(self) -> float:
        """Best secondary bid minus best primary ask (signed)."""
        return self.secondary_bid - self.primary_ask


def _match_key(row: MarketRow) -> str:
    """Heuristic event-matching key.

    v1.0 stays intentionally dumb: lowercased question text. Real
    cross-venue matching (slug normalization, fuzzy match, manual
    override list per risk R-I) lands when the agent is activated.
    """
    return row.question.strip().lower()


def _bps(value: float) -> int:
    return int(round(value * 10_000))


class CrossVenueArbDetector:
    """Stateless detector. Holds references to two venues + config.

    The class lives in v1.0 so the loader can construct it, but
    `scan()` will refuse to run while the secondary venue is the Kalshi
    stub. Tests inject two fake venues to exercise the matching logic.
    """

    def __init__(
        self,
        *,
        primary: MarketVenue,
        secondary: MarketVenue,
        config: CrossVenueArbConfig,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def _collect(self, venue: MarketVenue, *, limit: int) -> list[MarketRow]:
        try:
            rows: list[MarketRow] = []
            async for row in venue.scan(limit=limit):
                rows.append(row)
            return rows
        except NotConfiguredError as exc:
            raise CrossVenueDisabledError(
                f"cross_venue_arb cannot run: secondary venue "
                f"'{venue.name}' is not configured ({exc}). "
                "v1.0 ships this agent disabled per Phase 9; activate "
                "by providing a real venue implementation and flipping "
                "enabled: true in agents/polymarket/cross_venue_arb/config.yaml."
            ) from exc

    async def scan(self, *, limit: int = 200) -> list[CrossVenueOpportunity]:
        """Return all opportunities clearing the configured edge.

        Fails fast (`CrossVenueDisabledError`) when the secondary venue
        is the Kalshi stub or any other unconfigured venue.
        """
        secondary_rows = await self._collect(self._secondary, limit=limit)
        primary_rows = await self._collect(self._primary, limit=limit)

        secondary_index: dict[str, MarketRow] = {
            _match_key(r): r for r in secondary_rows
        }

        opportunities: list[CrossVenueOpportunity] = []
        for prow in primary_rows:
            srow = secondary_index.get(_match_key(prow))
            if srow is None:
                continue
            opp = self._evaluate(prow, srow)
            if opp is not None:
                opportunities.append(opp)
        return opportunities

    def _evaluate(
        self, prow: MarketRow, srow: MarketRow
    ) -> CrossVenueOpportunity | None:
        if prow.best_ask is None or srow.best_bid is None:
            return None

        # Liquidity gate (both legs).
        for row in (prow, srow):
            if row.liquidity_usd is None:
                return None
            if row.liquidity_usd < self._config.min_liquidity_usd:
                return None

        raw_edge = srow.best_bid - prow.best_ask
        if raw_edge <= 0:
            return None

        edge_bps = _bps(raw_edge) - self._config.slippage_buffer_bps
        if edge_bps < self._config.min_edge_bps:
            return None

        return CrossVenueOpportunity(
            primary_venue=prow.venue,
            secondary_venue=srow.venue,
            primary_market_id=prow.venue_market_id,
            secondary_market_id=srow.venue_market_id,
            question=prow.question,
            primary_ask=prow.best_ask,
            secondary_bid=srow.best_bid,
            edge_bps=edge_bps,
            notional_cap_usd=self._config.max_notional_usd,
        )


def filter_tradeable(
    opps: Iterable[CrossVenueOpportunity],
    *,
    primary_tradeable: dict[str, bool],
    secondary_tradeable: dict[str, bool],
) -> list[CrossVenueOpportunity]:
    """Apply F9 resolution-risk gate to both legs.

    Pure helper so the activation path in v1.x can plug straight into
    `shared/polymarket/resolution_risk.py` without re-doing the loop.
    """
    out: list[CrossVenueOpportunity] = []
    for opp in opps:
        if not primary_tradeable.get(opp.primary_market_id, False):
            continue
        if not secondary_tradeable.get(opp.secondary_market_id, False):
            continue
        out.append(opp)
    return out
