"""SumToOneArbAgent — orchestrates detect → size → risk → submit → record.

Reference: docs/architecture/polymarket-tab.md section 9, Phase 8 (F3.1)
and section 11 decision #3 (optimistic-sequential submit + rollback).

Design notes
============
* The agent is *not* an asyncio loop owner. It exposes one coroutine —
  `run_cycle()` — that the orchestrator schedules. This makes the agent
  trivially testable: a unit test calls `await agent.run_cycle()` once
  and inspects the recorded orders.
* All collaborators are injected via Protocols so unit tests can drop in
  fakes for the broker, the risk chain, and the order repository.
* Atomicity: PM CLOB does not support multi-leg atomic orders. We submit
  YES first, then NO. If NO fails (risk-chain reject *or* broker reject),
  we cancel-or-mark-rollback the YES leg and write a `ROLLED_BACK` row.
* Kill switch: a callable returning bool. Checked before each opportunity
  *and* between the two legs. If it flips mid-arb, the in-flight YES leg
  is rolled back. The orchestrator can therefore halt every PM strategy
  in well under 2s by flipping a single shared atomic flag.
* `paused`: a per-strategy bool, also injected. Same effect as kill switch
  but scoped to this strategy only.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

from .detector import ArbOpportunity, BinaryMarket, SumToOneDetector
from .sizing import SizingInputs, SizingResult, size_arb_legs

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Collaborator protocols
# ----------------------------------------------------------------------
class BrokerProtocol(Protocol):
    async def submit_order(self, order: dict) -> dict: ...
    async def cancel_order(self, venue_order_id: str) -> dict: ...


class RiskChainProtocol(Protocol):
    def evaluate(
        self,
        intent: dict,
        agent_state: dict | None = None,
        global_state: dict | None = None,
        pm_state: dict | None = None,
    ) -> dict: ...


class OrderRepoProtocol(Protocol):
    def insert(self, row: dict) -> None: ...


MarketSource = Callable[[], Iterable[BinaryMarket]]
PMStateBuilder = Callable[[ArbOpportunity], dict]
PausedFn = Callable[[], bool]
KillSwitchFn = Callable[[], bool]
ClockFn = Callable[[], datetime]


# ----------------------------------------------------------------------
# Public dataclasses
# ----------------------------------------------------------------------
@dataclass
class ArbSubmission:
    """Result of attempting to fire one arb opportunity."""

    arb_group_id: uuid.UUID
    opportunity: ArbOpportunity
    sizing: SizingResult
    yes_status: str = "SKIPPED"
    no_status: str = "SKIPPED"
    yes_order_id: str | None = None
    no_order_id: str | None = None
    rolled_back: bool = False
    reason: str = ""

    @property
    def is_filled(self) -> bool:
        return self.yes_status in ("FILLED", "PARTIAL") and self.no_status in (
            "FILLED",
            "PARTIAL",
        )


class KillSwitchTriggered(RuntimeError):  # noqa: N818 — public API name predates ruff rule
    """Raised internally when the kill switch flips mid-cycle."""


# ----------------------------------------------------------------------
# Agent
# ----------------------------------------------------------------------
@dataclass
class SumToOneArbAgent:
    """Polymarket sum-to-one arbitrage strategy agent."""

    pm_strategy_id: uuid.UUID
    broker: BrokerProtocol
    risk_chain: RiskChainProtocol
    order_repo: OrderRepoProtocol
    market_source: MarketSource
    pm_state_builder: PMStateBuilder
    detector: SumToOneDetector = field(default_factory=SumToOneDetector)
    paused_fn: PausedFn = field(default=lambda: False)
    kill_switch_fn: KillSwitchFn = field(default=lambda: False)
    clock_fn: ClockFn = field(
        default=lambda: datetime.now(timezone.utc)
    )

    bankroll_usd: float = 5000.0
    max_strategy_notional_usd: float = 1000.0
    max_trade_notional_usd: float = 100.0
    kelly_cap: float = 0.25
    open_strategy_notional_usd: float = 0.0
    mode: str = "PAPER"
    max_opportunities_per_cycle: int = 5

    # ---- public --------------------------------------------------------
    async def run_cycle(self) -> list[ArbSubmission]:
        """Single scan→fire pass. Returns one ArbSubmission per opportunity."""
        if self.kill_switch_fn():
            logger.info("sum_to_one_arb: kill switch active — skipping cycle")
            return []
        if self.paused_fn():
            logger.info(
                "sum_to_one_arb strategy=%s paused — skipping cycle",
                self.pm_strategy_id,
            )
            return []

        markets = list(self.market_source())
        opportunities = self.detector.scan(markets)
        if not opportunities:
            return []

        results: list[ArbSubmission] = []
        for opp in opportunities[: self.max_opportunities_per_cycle]:
            if self.kill_switch_fn() or self.paused_fn():
                break
            submission = await self._fire(opp)
            results.append(submission)
            if submission.reason.startswith("kill_switch_"):
                logger.warning("sum_to_one_arb: kill switch tripped mid-arb")
                break
            # Track open notional locally so multi-fire cycles respect the
            # per-strategy cap without round-tripping to the DB.
            if submission.is_filled and not submission.rolled_back:
                self.open_strategy_notional_usd += (
                    submission.sizing.yes_notional_usd
                    + submission.sizing.no_notional_usd
                )
        return results

    # ---- internals -----------------------------------------------------
    async def _fire(self, opp: ArbOpportunity) -> ArbSubmission:
        arb_group_id = uuid.uuid4()
        sizing = size_arb_legs(
            opp,
            SizingInputs(
                bankroll_usd=self.bankroll_usd,
                max_trade_notional_usd=self.max_trade_notional_usd,
                max_strategy_notional_usd=self.max_strategy_notional_usd,
                open_strategy_notional_usd=self.open_strategy_notional_usd,
                kelly_cap=self.kelly_cap,
            ),
        )
        sub = ArbSubmission(arb_group_id=arb_group_id, opportunity=opp, sizing=sizing)
        if sizing.pair_qty <= 0:
            sub.reason = f"sizing_blocked:{sizing.reason}"
            return sub

        yes_intent = self._intent(opp, "YES", sizing)
        no_intent = self._intent(opp, "NO", sizing)
        pm_state = self.pm_state_builder(opp)

        # YES leg ----------------------------------------------------------------
        yes_check = self.risk_chain.evaluate(yes_intent, pm_state=pm_state)
        if not yes_check.get("approved", False):
            sub.reason = f"risk_reject_yes:{yes_check.get('reason', '?')}"
            self._record_order(sub, leg="YES", intent=yes_intent, fill=None,
                               status="REJECTED", reason=sub.reason)
            return sub

        if self.kill_switch_fn():
            sub.reason = "kill_switch_pre_yes"
            return sub

        try:
            yes_fill = await self.broker.submit_order(yes_intent)
        except Exception as e:  # noqa: BLE001 — broker errors are opaque
            sub.reason = f"broker_error_yes:{type(e).__name__}:{e}"
            self._record_order(sub, leg="YES", intent=yes_intent, fill=None,
                               status="REJECTED", reason=sub.reason)
            return sub

        sub.yes_status = yes_fill.get("status", "UNKNOWN")
        sub.yes_order_id = yes_fill.get("venue_order_id")
        self._record_order(sub, leg="YES", intent=yes_intent, fill=yes_fill,
                           status=sub.yes_status, reason=yes_fill.get("reason", ""))

        if sub.yes_status not in ("FILLED", "PARTIAL"):
            sub.reason = f"yes_not_filled:{sub.yes_status}:{yes_fill.get('reason', '')}"
            return sub

        # Mid-arb kill switch check.
        if self.kill_switch_fn():
            await self._rollback(sub, leg="YES", reason="kill_switch_pre_no")
            return sub

        # NO leg -----------------------------------------------------------------
        no_check = self.risk_chain.evaluate(no_intent, pm_state=pm_state)
        if not no_check.get("approved", False):
            await self._rollback(
                sub, leg="YES",
                reason=f"risk_reject_no:{no_check.get('reason', '?')}",
            )
            return sub

        try:
            no_fill = await self.broker.submit_order(no_intent)
        except Exception as e:  # noqa: BLE001
            await self._rollback(sub, leg="YES",
                                 reason=f"broker_error_no:{type(e).__name__}:{e}")
            return sub

        sub.no_status = no_fill.get("status", "UNKNOWN")
        sub.no_order_id = no_fill.get("venue_order_id")
        self._record_order(sub, leg="NO", intent=no_intent, fill=no_fill,
                           status=sub.no_status, reason=no_fill.get("reason", ""))

        if sub.no_status not in ("FILLED", "PARTIAL"):
            await self._rollback(
                sub, leg="YES",
                reason=f"no_not_filled:{sub.no_status}:{no_fill.get('reason', '')}",
            )
            return sub

        sub.reason = "ok"
        return sub

    async def _rollback(self, sub: ArbSubmission, *, leg: str, reason: str) -> None:
        sub.rolled_back = True
        sub.reason = reason
        if leg == "YES" and sub.yes_order_id:
            try:
                await self.broker.cancel_order(sub.yes_order_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "sum_to_one_arb rollback cancel failed arb=%s err=%s",
                    sub.arb_group_id, e,
                )
        # Write an audit row so the rollback is visible in pm_orders.
        self._record_order(
            sub, leg=f"{leg}_ROLLBACK", intent=None, fill=None,
            status="ROLLED_BACK", reason=reason,
        )

    def _intent(self, opp: ArbOpportunity, side: str, sizing: SizingResult) -> dict:
        token = opp.yes_token_id if side == "YES" else opp.no_token_id
        price = opp.yes_ask if side == "YES" else opp.no_ask
        return {
            "venue": "polymarket",
            "pm_strategy_id": str(self.pm_strategy_id),
            "pm_market_id": opp.pm_market_id,
            "outcome_token_id": token,
            "side": "BUY",
            "qty": sizing.pair_qty,
            "qty_shares": sizing.pair_qty,
            "limit_price": price,
            "estimated_price": price,
            "mode": self.mode,
            "kelly_fraction": sizing.kelly_fraction,
            "arb_leg": side,
        }

    def _record_order(
        self,
        sub: ArbSubmission,
        *,
        leg: str,
        intent: dict | None,
        fill: dict | None,
        status: str,
        reason: str,
    ) -> None:
        row = {
            "pm_strategy_id": str(self.pm_strategy_id),
            "pm_market_id": sub.opportunity.pm_market_id,
            "outcome_token_id": (
                sub.opportunity.yes_token_id if leg.startswith("YES")
                else sub.opportunity.no_token_id
            ),
            "side": "BUY",
            "qty_shares": sub.sizing.pair_qty,
            "limit_price": (
                sub.opportunity.yes_ask if leg.startswith("YES")
                else sub.opportunity.no_ask
            ),
            "mode": self.mode,
            "status": status,
            "venue_order_id": (fill or {}).get("venue_order_id"),
            "fees_paid_usd": (fill or {}).get("fees_paid_usd"),
            "slippage_bps": (fill or {}).get("slippage_bps"),
            "arb_group_id": str(sub.arb_group_id),
            "arb_leg": leg,
            "reason": reason,
            "submitted_at": self.clock_fn().isoformat(),
        }
        try:
            self.order_repo.insert(row)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "sum_to_one_arb: order_repo.insert failed arb=%s leg=%s err=%s",
                sub.arb_group_id, leg, e,
            )
