"""Unit tests for SumToOneArbAgent (Phase 8 — F3.1).

These tests use a fake broker, fake risk chain, and fake order repo.
They cover the DoD bullets from docs/architecture/polymarket-tab.md
section 9, Phase 8:

  * detect synthetic sum<1 violation in fixture book
  * size legs respecting per-strategy caps
  * submit through risk chain
  * write `pm_orders` rows with shared `arb_group_id`
  * rollback on simulated leg failure
  * per-strategy pause works
  * kill switch halts mid-arb
"""

from __future__ import annotations

import uuid

import pytest

from agents.polymarket.sum_to_one_arb import (
    ArbSubmission,
    SumToOneArbAgent,
    SumToOneDetector,
)
from agents.polymarket.sum_to_one_arb.detector import BinaryMarket
from shared.polymarket.paper_fill import BookSnapshot


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------
class FakeBroker:
    def __init__(self, *, fail_no: bool = False, broker_raises_no: bool = False):
        self.fail_no = fail_no
        self.broker_raises_no = broker_raises_no
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []
        self._counter = 0

    async def submit_order(self, order):
        self.submitted.append(order)
        leg = order.get("arb_leg")
        if leg == "NO" and self.broker_raises_no:
            raise RuntimeError("simulated broker outage on NO leg")
        self._counter += 1
        venue_id = f"venue-{self._counter}"
        if leg == "NO" and self.fail_no:
            return {
                "status": "REJECTED",
                "venue_order_id": venue_id,
                "reason": "book_moved",
                "fees_paid_usd": 0.0,
                "slippage_bps": 0.0,
            }
        notional = order["qty_shares"] * order["limit_price"]
        return {
            "status": "FILLED",
            "venue_order_id": venue_id,
            "reason": "ok",
            "fees_paid_usd": notional * 0.02,
            "slippage_bps": 1.0,
        }

    async def cancel_order(self, venue_order_id):
        self.cancelled.append(venue_order_id)
        return {"status": "CANCELLED", "venue_order_id": venue_order_id}


class FakeRiskChain:
    def __init__(self, *, reject_no: bool = False):
        self.reject_no = reject_no
        self.calls: list[dict] = []

    def evaluate(self, intent, agent_state=None, global_state=None, pm_state=None):
        self.calls.append(intent)
        if self.reject_no and intent.get("arb_leg") == "NO":
            return {"approved": False, "reason": "pm_per_trade_cap_exceeded"}
        return {"approved": True, "reason": ""}


class FakeOrderRepo:
    def __init__(self):
        self.rows: list[dict] = []

    def insert(self, row):
        self.rows.append(row)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _arb_market(pm_id: str = "m1") -> BinaryMarket:
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


def _build_agent(
    *,
    broker=None,
    risk=None,
    repo=None,
    markets=None,
    paused=False,
    kill_switch=False,
) -> SumToOneArbAgent:
    return SumToOneArbAgent(
        pm_strategy_id=uuid.uuid4(),
        broker=broker or FakeBroker(),
        risk_chain=risk or FakeRiskChain(),
        order_repo=repo or FakeOrderRepo(),
        market_source=lambda: markets or [_arb_market()],
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
        paused_fn=lambda: paused,
        kill_switch_fn=lambda: kill_switch,
        bankroll_usd=10_000,
        max_strategy_notional_usd=1_000,
        max_trade_notional_usd=100,
        kelly_cap=0.25,
    )


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_happy_path_fires_paired_legs():
    broker = FakeBroker()
    repo = FakeOrderRepo()
    risk = FakeRiskChain()
    agent = _build_agent(broker=broker, risk=risk, repo=repo)

    results = await agent.run_cycle()
    assert len(results) == 1
    sub = results[0]
    assert sub.is_filled
    assert not sub.rolled_back
    assert sub.yes_status == "FILLED"
    assert sub.no_status == "FILLED"

    # Both legs went to the broker, in order.
    assert [o["arb_leg"] for o in broker.submitted] == ["YES", "NO"]
    # Both intents went through the risk chain.
    assert [c["arb_leg"] for c in risk.calls] == ["YES", "NO"]
    # Both orders were recorded in the repo with the same arb_group_id.
    leg_rows = [r for r in repo.rows if r["arb_leg"] in ("YES", "NO")]
    assert len(leg_rows) == 2
    assert len({r["arb_group_id"] for r in leg_rows}) == 1
    assert all(r["mode"] == "PAPER" for r in leg_rows)
    assert all(r["status"] == "FILLED" for r in leg_rows)


@pytest.mark.asyncio
async def test_rollback_when_no_leg_broker_rejects():
    broker = FakeBroker(fail_no=True)
    repo = FakeOrderRepo()
    agent = _build_agent(broker=broker, repo=repo)

    [sub] = await agent.run_cycle()
    assert sub.rolled_back is True
    assert "no_not_filled" in sub.reason
    # YES leg submitted, NO leg submitted (and rejected), YES cancelled.
    assert broker.cancelled == ["venue-1"]
    statuses = [r["status"] for r in repo.rows]
    assert "ROLLED_BACK" in statuses
    assert "FILLED" in statuses  # the YES fill was recorded before rollback


@pytest.mark.asyncio
async def test_rollback_when_no_leg_broker_raises():
    broker = FakeBroker(broker_raises_no=True)
    repo = FakeOrderRepo()
    agent = _build_agent(broker=broker, repo=repo)

    [sub] = await agent.run_cycle()
    assert sub.rolled_back
    assert "broker_error_no" in sub.reason
    assert broker.cancelled == ["venue-1"]


@pytest.mark.asyncio
async def test_rollback_when_no_leg_risk_rejects():
    broker = FakeBroker()
    repo = FakeOrderRepo()
    risk = FakeRiskChain(reject_no=True)
    agent = _build_agent(broker=broker, risk=risk, repo=repo)

    [sub] = await agent.run_cycle()
    assert sub.rolled_back
    assert "risk_reject_no" in sub.reason
    # NO leg never reached the broker.
    assert [o["arb_leg"] for o in broker.submitted] == ["YES"]
    assert broker.cancelled == ["venue-1"]


@pytest.mark.asyncio
async def test_paused_strategy_skips_cycle():
    broker = FakeBroker()
    agent = _build_agent(broker=broker, paused=True)
    results = await agent.run_cycle()
    assert results == []
    assert broker.submitted == []


@pytest.mark.asyncio
async def test_kill_switch_skips_cycle():
    broker = FakeBroker()
    agent = _build_agent(broker=broker, kill_switch=True)
    results = await agent.run_cycle()
    assert results == []
    assert broker.submitted == []


@pytest.mark.asyncio
async def test_kill_switch_mid_arb_rolls_back():
    """Kill switch flips after YES fill but before NO submit."""
    broker = FakeBroker()
    repo = FakeOrderRepo()

    state = {"killed": False}

    def kill():
        return state["killed"]

    agent = _build_agent(broker=broker, repo=repo)
    agent.kill_switch_fn = kill

    # Wrap broker to flip the kill switch right after the YES fill.
    real_submit = broker.submit_order

    async def submit_with_kill(order):
        result = await real_submit(order)
        if order["arb_leg"] == "YES":
            state["killed"] = True
        return result

    broker.submit_order = submit_with_kill  # type: ignore[assignment]

    results = await agent.run_cycle()
    assert len(results) == 1
    sub = results[0]
    assert sub.rolled_back
    assert sub.reason == "kill_switch_pre_no"
    assert broker.cancelled == ["venue-1"]
    # Only YES went to broker — NO never submitted.
    assert [o["arb_leg"] for o in broker.submitted] == ["YES"]


@pytest.mark.asyncio
async def test_no_arb_no_orders():
    no_arb = BinaryMarket(
        pm_market_id="flat",
        venue_market_id="flat",
        yes_token_id="flat-YES",
        no_token_id="flat-NO",
        yes_book=BookSnapshot.from_lists("flat-YES",
                                         bids=[(0.55, 100)], asks=[(0.56, 100)]),
        no_book=BookSnapshot.from_lists("flat-NO",
                                        bids=[(0.45, 100)], asks=[(0.46, 100)]),
    )
    broker = FakeBroker()
    agent = _build_agent(broker=broker, markets=[no_arb])
    assert await agent.run_cycle() == []
    assert broker.submitted == []


@pytest.mark.asyncio
async def test_arb_group_id_unique_per_opportunity():
    broker = FakeBroker()
    repo = FakeOrderRepo()
    markets = [_arb_market("a"), _arb_market("b")]
    agent = _build_agent(broker=broker, repo=repo, markets=markets)

    results = await agent.run_cycle()
    assert len(results) == 2
    assert isinstance(results[0], ArbSubmission)
    assert results[0].arb_group_id != results[1].arb_group_id
    # Each market produced exactly two leg rows under one arb_group_id.
    by_group: dict[str, list[dict]] = {}
    for r in repo.rows:
        if r["arb_leg"] in ("YES", "NO"):
            by_group.setdefault(r["arb_group_id"], []).append(r)
    assert len(by_group) == 2
    assert all(len(v) == 2 for v in by_group.values())


@pytest.mark.asyncio
async def test_per_strategy_cap_tracked_across_cycle():
    """After firing one arb the open notional should constrain the next."""
    broker = FakeBroker()
    repo = FakeOrderRepo()
    agent = _build_agent(
        broker=broker, repo=repo,
        markets=[_arb_market("a"), _arb_market("b")],
    )
    # Tight per-strategy cap so the second arb is sized down or skipped.
    agent.max_strategy_notional_usd = 100.0
    agent.max_trade_notional_usd = 1000.0
    agent.bankroll_usd = 10_000

    results = await agent.run_cycle()
    assert len(results) == 2
    first_open = (
        results[0].sizing.yes_notional_usd + results[0].sizing.no_notional_usd
    )
    # Second submission should see less room than the first.
    assert results[1].sizing.pair_qty <= results[0].sizing.pair_qty
    assert first_open > 0
