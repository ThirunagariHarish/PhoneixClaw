"""Unit tests for cross_venue_arb scaffold (Phase 9, F3.2).

The agent ships DISABLED in v1.0. These tests verify:

* the loader can read its config and sees `enabled=false` / status STOPPED;
* the detector matching + edge logic works against two FAKE venues
  (so v1.x activation is mechanical);
* the detector FAILS FAST with a clear, Phase-9-referencing message
  when the secondary venue is the Kalshi stub (real `NotConfiguredError`).

No network, no DB.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from agents.polymarket.cross_venue_arb import (
    CrossVenueArbDetector,
    CrossVenueDisabledError,
    CrossVenueOpportunity,
    load_config,
)
from agents.polymarket.cross_venue_arb.detector import filter_tradeable
from services.connector_manager.src.venues.base import MarketRow, MarketVenue
from services.connector_manager.src.venues.kalshi_venue import KalshiVenue


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeVenue(MarketVenue):
    def __init__(self, name: str, rows: list[MarketRow]) -> None:
        self.name = name
        self._rows = rows

    async def scan(self, *, limit: int = 500) -> AsyncIterator[MarketRow]:
        for row in self._rows[:limit]:
            yield row


def _row(
    venue: str,
    mid: str,
    question: str,
    *,
    bid: float | None = None,
    ask: float | None = None,
    liq: float | None = 50_000,
) -> MarketRow:
    return MarketRow(
        venue=venue,
        venue_market_id=mid,
        question=question,
        best_bid=bid,
        best_ask=ask,
        liquidity_usd=liq,
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def test_config_ships_disabled_in_v1_0() -> None:
    cfg = load_config()
    assert cfg.name == "cross_venue_arb"
    assert cfg.enabled is False, "Phase 9 DoD: must ship disabled"
    assert cfg.status == "stopped"
    assert cfg.secondary_venue == "kalshi"
    assert cfg.require_f9_tradeable_both_legs is True
    assert cfg.min_edge_bps > 0
    assert cfg.max_notional_usd > 0


# ---------------------------------------------------------------------------
# Fail-fast against Kalshi stub
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_detector_fails_fast_when_secondary_is_kalshi_stub() -> None:
    cfg = load_config()
    primary = FakeVenue("polymarket", [_row("polymarket", "p1", "Will X happen?", ask=0.40)])
    detector = CrossVenueArbDetector(
        primary=primary, secondary=KalshiVenue(), config=cfg
    )

    with pytest.raises(CrossVenueDisabledError) as exc:
        await detector.scan()

    msg = str(exc.value)
    assert "kalshi" in msg.lower()
    assert "Phase 9" in msg
    assert "enabled" in msg  # references the config flip


# ---------------------------------------------------------------------------
# Detector logic with two fakes
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_detector_finds_spread_above_threshold() -> None:
    cfg = load_config()
    primary = FakeVenue(
        "polymarket",
        [
            _row("polymarket", "pm-1", "Will X happen?", ask=0.40),
            _row("polymarket", "pm-2", "Unrelated market", ask=0.50),
        ],
    )
    secondary = FakeVenue(
        "kalshi",
        [
            # 6c raw edge => 600 bps - 25 buffer = 575 bps >> 150 threshold
            _row("kalshi", "k-1", "Will X happen?", bid=0.46),
        ],
    )
    detector = CrossVenueArbDetector(
        primary=primary, secondary=secondary, config=cfg
    )

    opps = await detector.scan()
    assert len(opps) == 1
    opp = opps[0]
    assert isinstance(opp, CrossVenueOpportunity)
    assert opp.primary_market_id == "pm-1"
    assert opp.secondary_market_id == "k-1"
    assert opp.edge_bps == 575
    assert opp.notional_cap_usd == cfg.max_notional_usd


@pytest.mark.asyncio
async def test_detector_skips_below_edge_threshold() -> None:
    cfg = load_config()
    # 1c raw edge => 100 bps - 25 = 75 bps, below 150 min
    primary = FakeVenue("polymarket", [_row("polymarket", "p", "Q", ask=0.50)])
    secondary = FakeVenue("kalshi", [_row("kalshi", "k", "Q", bid=0.51)])
    detector = CrossVenueArbDetector(
        primary=primary, secondary=secondary, config=cfg
    )
    assert await detector.scan() == []


@pytest.mark.asyncio
async def test_detector_skips_when_liquidity_below_floor() -> None:
    cfg = load_config()
    primary = FakeVenue(
        "polymarket", [_row("polymarket", "p", "Q", ask=0.30, liq=100)]
    )
    secondary = FakeVenue(
        "kalshi", [_row("kalshi", "k", "Q", bid=0.50, liq=100)]
    )
    detector = CrossVenueArbDetector(
        primary=primary, secondary=secondary, config=cfg
    )
    assert await detector.scan() == []


@pytest.mark.asyncio
async def test_detector_skips_negative_edge() -> None:
    cfg = load_config()
    primary = FakeVenue("polymarket", [_row("polymarket", "p", "Q", ask=0.60)])
    secondary = FakeVenue("kalshi", [_row("kalshi", "k", "Q", bid=0.40)])
    detector = CrossVenueArbDetector(
        primary=primary, secondary=secondary, config=cfg
    )
    assert await detector.scan() == []


@pytest.mark.asyncio
async def test_detector_ignores_unmatched_questions() -> None:
    cfg = load_config()
    primary = FakeVenue("polymarket", [_row("polymarket", "p", "Apples?", ask=0.30)])
    secondary = FakeVenue("kalshi", [_row("kalshi", "k", "Oranges?", bid=0.90)])
    detector = CrossVenueArbDetector(
        primary=primary, secondary=secondary, config=cfg
    )
    assert await detector.scan() == []


# ---------------------------------------------------------------------------
# F9 filter helper
# ---------------------------------------------------------------------------
def test_filter_tradeable_drops_either_leg_blocked() -> None:
    base = CrossVenueOpportunity(
        primary_venue="polymarket",
        secondary_venue="kalshi",
        primary_market_id="p1",
        secondary_market_id="k1",
        question="Q",
        primary_ask=0.4,
        secondary_bid=0.5,
        edge_bps=900,
        notional_cap_usd=250,
    )
    blocked_primary = CrossVenueOpportunity(**{**base.__dict__, "primary_market_id": "p2"})
    blocked_secondary = CrossVenueOpportunity(**{**base.__dict__, "secondary_market_id": "k2"})

    out = filter_tradeable(
        [base, blocked_primary, blocked_secondary],
        primary_tradeable={"p1": True, "p2": False},
        secondary_tradeable={"k1": True, "k2": False},
    )
    assert out == [base]


# ---------------------------------------------------------------------------
# Detector property
# ---------------------------------------------------------------------------
def test_detector_enabled_flag_mirrors_config() -> None:
    cfg = load_config()
    detector = CrossVenueArbDetector(
        primary=FakeVenue("polymarket", []),
        secondary=FakeVenue("kalshi", []),
        config=cfg,
    )
    assert detector.enabled is False
