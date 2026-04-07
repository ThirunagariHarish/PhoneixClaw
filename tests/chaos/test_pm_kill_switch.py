"""Chaos test: PM kill switch must halt sum_to_one_arb in <2s.

Reference: docs/architecture/polymarket-tab.md Phase 15 DoD —
"kill-switch propagation < 2s asserted".

Design
------
We model a continuously-running orchestrator loop that drives
`SumToOneArbAgent.run_cycle()` back-to-back. A shared mutable flag
acts as the kill switch. The chaos scenario:

  1. The agent is firing arbs at full tilt against a fake broker that
     introduces a small artificial latency per leg (so each cycle costs
     real wall time, not just CPU).
  2. After ~250ms a separate task flips the kill switch.
  3. We measure the wall-clock delta between the flip and the moment
     the orchestrator loop observes that the agent has stopped doing
     work (`run_cycle` returns []).
  4. Assert that delta is well under 2 seconds (the architecture
     budget). We assert <1s as the operational target with 1s of head
     room before the hard SLA.

The agent itself checks the kill switch:
  * before each cycle,
  * before each opportunity inside a cycle,
  * before submitting each leg,
  * between YES and NO legs (rolling back YES if needed).

So once the flag flips, the worst case is "currently in the middle of
one leg's broker call". The fake broker's per-call latency dominates
the propagation time, which is exactly what we want to bound.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from agents.polymarket.sum_to_one_arb import SumToOneArbAgent, SumToOneDetector
from agents.polymarket.sum_to_one_arb.detector import BinaryMarket
from shared.polymarket.paper_fill import BookSnapshot


# ----------------------------------------------------------------------
# Fakes — slow on purpose so the kill switch has real time to chase
# ----------------------------------------------------------------------
class SlowBroker:
    """Fake broker with a per-call latency to simulate real I/O."""

    def __init__(self, *, leg_latency_s: float = 0.05) -> None:
        self.leg_latency_s = leg_latency_s
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []
        self._counter = 0

    async def submit_order(self, order: dict) -> dict:
        # Record submission *before* the latency sleep so a concurrent
        # observer (e.g. the chaos flipper task) can see the in-flight leg
        # while the broker call is still pending.
        self.submitted.append(order)
        self._counter += 1
        await asyncio.sleep(self.leg_latency_s)
        notional = order["qty_shares"] * order["limit_price"]
        return {
            "status": "FILLED",
            "venue_order_id": f"venue-{self._counter}",
            "reason": "ok",
            "fees_paid_usd": notional * 0.02,
            "slippage_bps": 1.0,
        }

    async def cancel_order(self, venue_order_id: str) -> dict:
        await asyncio.sleep(self.leg_latency_s / 2)
        self.cancelled.append(venue_order_id)
        return {"status": "CANCELLED", "venue_order_id": venue_order_id}


class PassRiskChain:
    def evaluate(self, intent, agent_state=None, global_state=None, pm_state=None):
        return {"approved": True, "reason": ""}


class NullRepo:
    def insert(self, row: dict) -> None:  # noqa: D401 — protocol method
        return None


def _arb_market(pm_id: str) -> BinaryMarket:
    """Sum<1 binary market that the detector will fire on every cycle."""
    return BinaryMarket(
        pm_market_id=pm_id,
        venue_market_id=f"venue-{pm_id}",
        yes_token_id=f"{pm_id}-YES",
        no_token_id=f"{pm_id}-NO",
        yes_book=BookSnapshot.from_lists(
            f"{pm_id}-YES",
            bids=[(0.39, 500.0)],
            asks=[(0.40, 500.0)],
        ),
        no_book=BookSnapshot.from_lists(
            f"{pm_id}-NO",
            bids=[(0.49, 500.0)],
            asks=[(0.50, 500.0)],
        ),
    )


@pytest.mark.asyncio
async def test_kill_switch_halts_sum_to_one_arb_under_2s():
    """Kill switch must propagate to a halted agent in well under 2s."""
    kill_flag = {"on": False}
    broker = SlowBroker(leg_latency_s=0.05)

    markets = [_arb_market(f"m{i}") for i in range(8)]

    agent = SumToOneArbAgent(
        pm_strategy_id=uuid.uuid4(),
        broker=broker,
        risk_chain=PassRiskChain(),
        order_repo=NullRepo(),
        market_source=lambda: markets,
        pm_state_builder=lambda opp: {
            "strategy_mode": "PAPER",
            "attestation_valid": True,
            "f9_tradeable": True,
            "f9_score": 0.1,
            "max_trade_notional_usd": 1000.0,
            "max_strategy_notional_usd": 10_000.0,
            "bankroll_usd": 10_000.0,
            "kelly_cap": 0.25,
            "open_strategy_notional_usd": 0.0,
        },
        detector=SumToOneDetector(fee_rate=0.02, min_edge_bps=10.0),
        kill_switch_fn=lambda: kill_flag["on"],
        bankroll_usd=10_000,
        max_strategy_notional_usd=10_000,
        max_trade_notional_usd=100,
        kelly_cap=0.25,
        max_opportunities_per_cycle=8,
    )

    halted_at: dict[str, float] = {}
    flipped_at: dict[str, float] = {}
    cycles_run = {"n": 0}
    stop_loop = asyncio.Event()

    async def orchestrator_loop() -> None:
        # Drive the agent the way the real orchestrator does: back-to-back
        # `run_cycle` calls. The first cycle that returns [] *after* the
        # kill switch is flipped is our "halted" observation.
        while not stop_loop.is_set():
            results = await agent.run_cycle()
            cycles_run["n"] += 1
            if kill_flag["on"] and not results:
                halted_at["t"] = time.perf_counter()
                return
            # Tiny yield so the flipper task can run on busy event loops.
            await asyncio.sleep(0)

    async def flipper() -> None:
        await asyncio.sleep(0.25)
        flipped_at["t"] = time.perf_counter()
        kill_flag["on"] = True

    # Hard ceiling so a buggy implementation cannot hang the suite.
    try:
        await asyncio.wait_for(
            asyncio.gather(orchestrator_loop(), flipper()),
            timeout=5.0,
        )
    finally:
        stop_loop.set()

    assert "t" in flipped_at, "flipper never ran"
    assert "t" in halted_at, "agent never halted after kill switch flip"
    assert cycles_run["n"] >= 1

    propagation_s = halted_at["t"] - flipped_at["t"]
    # Architecture SLA: <2s. Operational target: <1s. Assert the tighter
    # bound; the looser SLA is documented in the assertion message.
    assert propagation_s < 1.0, (
        f"kill switch propagation {propagation_s * 1000:.1f}ms exceeded 1s "
        f"operational target (architecture SLA is 2s)"
    )


@pytest.mark.asyncio
async def test_kill_switch_rolls_back_in_flight_yes_leg():
    """Mid-arb kill: a YES leg already filled must be rolled back."""
    # Flip kill flag *after* YES submit completes but *before* NO submit
    # by checking the broker counter from a side task.
    kill_flag = {"on": False}
    broker = SlowBroker(leg_latency_s=0.05)
    market = _arb_market("solo")

    agent = SumToOneArbAgent(
        pm_strategy_id=uuid.uuid4(),
        broker=broker,
        risk_chain=PassRiskChain(),
        order_repo=NullRepo(),
        market_source=lambda: [market],
        pm_state_builder=lambda opp: {
            "strategy_mode": "PAPER",
            "attestation_valid": True,
            "f9_tradeable": True,
            "f9_score": 0.1,
            "max_trade_notional_usd": 1000.0,
            "max_strategy_notional_usd": 10_000.0,
            "bankroll_usd": 10_000.0,
            "kelly_cap": 0.25,
            "open_strategy_notional_usd": 0.0,
        },
        detector=SumToOneDetector(fee_rate=0.02, min_edge_bps=10.0),
        kill_switch_fn=lambda: kill_flag["on"],
        bankroll_usd=10_000,
        max_strategy_notional_usd=1_000,
        max_trade_notional_usd=100,
        kelly_cap=0.25,
    )

    async def flip_after_yes() -> None:
        # Wait until the YES leg has been submitted, then flip.
        for _ in range(200):
            if any(o.get("arb_leg") == "YES" for o in broker.submitted):
                kill_flag["on"] = True
                return
            await asyncio.sleep(0.005)

    flipper_task = asyncio.create_task(flip_after_yes())
    results = await agent.run_cycle()
    await flipper_task

    assert len(results) == 1
    sub = results[0]
    # YES filled, NO never went out, YES rolled back.
    assert sub.yes_status == "FILLED"
    assert sub.rolled_back is True
    assert "kill_switch" in sub.reason
    assert broker.cancelled, "rolled-back YES leg must have been cancelled"
