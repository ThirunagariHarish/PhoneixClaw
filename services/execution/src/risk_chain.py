"""
3-layer risk check chain: agent-level, execution-level, global-level.

M1.12: Risk management before trade execution.
Reference: PRD Section 8.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class RiskCheckResult:
    """Result of a risk check evaluation."""
    def __init__(self, approved: bool, reason: str = "", checks: list[dict] | None = None):
        self.approved = approved
        self.reason = reason
        self.checks = checks or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "checks": self.checks,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }


class AgentLevelRisk:
    """Check agent-specific limits: max concurrent positions, daily trade count."""

    MAX_CONCURRENT = 5
    MAX_DAILY_TRADES = 50

    def check(self, intent: dict, agent_state: dict | None = None) -> dict:
        state = agent_state or {}
        open_positions = state.get("open_positions", 0)
        daily_trades = state.get("daily_trades", 0)

        if open_positions >= self.MAX_CONCURRENT:
            return {"passed": False, "layer": "agent", "reason": f"Max concurrent positions ({self.MAX_CONCURRENT}) reached"}
        if daily_trades >= self.MAX_DAILY_TRADES:
            return {"passed": False, "layer": "agent", "reason": f"Daily trade limit ({self.MAX_DAILY_TRADES}) reached"}
        return {"passed": True, "layer": "agent", "reason": ""}


class ExecutionLevelRisk:
    """Check trade-specific rules: position size, symbol validity, market hours."""

    MAX_POSITION_VALUE = 50000.0  # $50k max per position
    MAX_STOP_LOSS_PCT = 0.20  # 20% max stop loss

    def check(self, intent: dict) -> dict:
        qty = intent.get("qty", 0)
        price = intent.get("limit_price") or intent.get("estimated_price", 0)
        position_value = qty * price

        if position_value > self.MAX_POSITION_VALUE:
            return {"passed": False, "layer": "execution", "reason": f"Position value ${position_value:.0f} exceeds max ${self.MAX_POSITION_VALUE:.0f}"}

        stop_price = intent.get("stop_price")
        if stop_price and price > 0:
            stop_pct = abs(price - stop_price) / price
            if stop_pct > self.MAX_STOP_LOSS_PCT:
                return {"passed": False, "layer": "execution", "reason": f"Stop loss {stop_pct:.1%} exceeds max {self.MAX_STOP_LOSS_PCT:.0%}"}

        return {"passed": True, "layer": "execution", "reason": ""}


class GlobalLevelRisk:
    """Check system-wide limits: total exposure, circuit breaker state."""

    MAX_TOTAL_EXPOSURE = 500000.0  # $500k total across all accounts
    CIRCUIT_BREAKER_ACTIVE = False

    def check(self, intent: dict, global_state: dict | None = None) -> dict:
        if self.CIRCUIT_BREAKER_ACTIVE:
            return {"passed": False, "layer": "global", "reason": "Circuit breaker is active — all trading halted"}

        state = global_state or {}
        total_exposure = state.get("total_exposure", 0)
        qty = intent.get("qty", 0)
        price = intent.get("limit_price") or intent.get("estimated_price", 0)

        if total_exposure + (qty * price) > self.MAX_TOTAL_EXPOSURE:
            return {"passed": False, "layer": "global", "reason": f"Total exposure would exceed ${self.MAX_TOTAL_EXPOSURE:.0f}"}

        return {"passed": True, "layer": "global", "reason": ""}


class PolymarketLayerRisk:
    """Polymarket-specific risk layer (Phase 6).

    Reference: docs/architecture/polymarket-tab.md sections 4.2, 4.6, 4.8,
    9 (Phase 6), 10 (R-A, R-B, R-H).

    Enforces, in order:
      1. Hard mode-mismatch fail. Intent `mode` must equal strategy `mode`.
         A LIVE intent for a PAPER strategy (or vice-versa) is rejected
         with no further checks. v1.0 ships PAPER-only by policy, so any
         LIVE intent without an explicitly-LIVE strategy is rejected.
      2. Jurisdiction gate. The user must currently hold a valid
         attestation. The chain accepts a pre-evaluated `attestation_valid`
         bool in `pm_state` so the layer stays pure (the API/orchestrator
         calls `JurisdictionAttestationGate` once and forwards the result).
      3. F9 resolution-risk gate. The market must have a recent score with
         `tradeable=True` and `final_score < threshold`.
      4. Per-trade notional cap (default $100).
      5. Per-strategy notional cap (default $1000) — already-open notional
         plus this trade must not exceed.
      6. Bankroll cap (default $5000) — total open exposure for the strategy.
      7. Fractional Kelly cap (default 0.25) — if the intent carries a
         `kelly_fraction`, it must be <= cap.

    The layer is *pure*: it takes an intent dict and a `pm_state` dict that
    the caller (orchestrator) populates from repos. No DB I/O lives here so
    unit tests can drive every branch with literals.

    `pm_state` shape (all optional, defaults are conservative):
      {
        "strategy_mode": "PAPER" | "LIVE",
        "bankroll_usd": float,
        "max_strategy_notional_usd": float,
        "max_trade_notional_usd": float,
        "kelly_cap": float,
        "open_strategy_notional_usd": float,
        "attestation_valid": bool,
        "f9_tradeable": bool,
        "f9_score": float | None,
        "f9_threshold": float,
      }
    """

    DEFAULT_BANKROLL_USD = 5000.0
    DEFAULT_MAX_STRATEGY_NOTIONAL_USD = 1000.0
    DEFAULT_MAX_TRADE_NOTIONAL_USD = 100.0
    DEFAULT_KELLY_CAP = 0.25
    DEFAULT_F9_THRESHOLD = 0.55  # mirrors shared.polymarket.resolution_risk

    def check(self, intent: dict, pm_state: dict | None = None) -> dict:
        state = pm_state or {}

        intent_mode = (intent.get("mode") or "").upper()
        strategy_mode = (state.get("strategy_mode") or "PAPER").upper()
        if intent_mode not in ("PAPER", "LIVE"):
            return self._fail(f"pm_mode_invalid:{intent.get('mode')!r}")
        if intent_mode != strategy_mode:
            return self._fail(
                f"pm_mode_mismatch: intent={intent_mode} strategy={strategy_mode}"
            )

        if not state.get("attestation_valid", False):
            return self._fail("pm_jurisdiction_attestation_invalid")

        if not state.get("f9_tradeable", False):
            return self._fail("pm_f9_not_tradeable")
        f9_score = state.get("f9_score")
        threshold = state.get("f9_threshold", self.DEFAULT_F9_THRESHOLD)
        if f9_score is not None and f9_score >= threshold:
            return self._fail(
                f"pm_f9_score_above_threshold: {f9_score:.3f} >= {threshold:.3f}"
            )

        qty = float(intent.get("qty_shares") or intent.get("qty") or 0)
        price = float(
            intent.get("limit_price")
            or intent.get("estimated_price")
            or 0
        )
        if qty <= 0 or price <= 0:
            return self._fail("pm_intent_qty_or_price_non_positive")
        if not (0.0 <= price <= 1.0):
            return self._fail(f"pm_price_out_of_range:{price}")

        notional = qty * price

        max_trade = float(
            state.get("max_trade_notional_usd", self.DEFAULT_MAX_TRADE_NOTIONAL_USD)
        )
        if notional > max_trade:
            return self._fail(
                f"pm_per_trade_cap_exceeded: ${notional:.2f} > ${max_trade:.2f}"
            )

        open_notional = float(state.get("open_strategy_notional_usd", 0.0))
        max_strat = float(
            state.get(
                "max_strategy_notional_usd", self.DEFAULT_MAX_STRATEGY_NOTIONAL_USD
            )
        )
        if open_notional + notional > max_strat:
            return self._fail(
                f"pm_per_strategy_cap_exceeded: "
                f"${open_notional + notional:.2f} > ${max_strat:.2f}"
            )

        bankroll = float(state.get("bankroll_usd", self.DEFAULT_BANKROLL_USD))
        if open_notional + notional > bankroll:
            return self._fail(
                f"pm_bankroll_exceeded: "
                f"${open_notional + notional:.2f} > ${bankroll:.2f}"
            )

        kelly_cap = float(state.get("kelly_cap", self.DEFAULT_KELLY_CAP))
        kelly_fraction = intent.get("kelly_fraction")
        if kelly_fraction is not None and float(kelly_fraction) > kelly_cap:
            return self._fail(
                f"pm_kelly_cap_exceeded: {float(kelly_fraction):.3f} > {kelly_cap:.3f}"
            )

        return {"passed": True, "layer": "polymarket", "reason": ""}

    @staticmethod
    def _fail(reason: str) -> dict:
        return {"passed": False, "layer": "polymarket", "reason": reason}


_PM_INTENT_FIELDS = ("pm_market_id", "pm_strategy_id", "pm_outcome_token_id", "arb_leg")


def _intent_smells_like_pm(intent: dict) -> bool:
    """Heuristic: any PM-shaped field present in the intent."""
    return any(intent.get(f) for f in _PM_INTENT_FIELDS)


class RiskCheckChain:
    """Chains all 3 risk layers. All must pass for approval."""

    def __init__(self, pm_strategy_repo: Any = None):
        """`pm_strategy_repo` (M7): optional sync callable that takes a
        `pm_strategy_id` (str|UUID) and returns the live `mode` ('PAPER' or
        'LIVE') from the database. The risk chain compares the intent's
        declared mode against this DB-sourced value and rejects on mismatch
        — defending against a tampered intent that lies about its mode.
        """
        self.agent_risk = AgentLevelRisk()
        self.execution_risk = ExecutionLevelRisk()
        self.global_risk = GlobalLevelRisk()
        self.pm_risk = PolymarketLayerRisk()
        self._pm_strategy_repo = pm_strategy_repo

    def evaluate(
        self,
        intent: dict,
        agent_state: dict | None = None,
        global_state: dict | None = None,
        pm_state: dict | None = None,
    ) -> dict[str, Any]:
        checks = []

        agent_check = self.agent_risk.check(intent, agent_state)
        checks.append(agent_check)
        if not agent_check["passed"]:
            return RiskCheckResult(False, agent_check["reason"], checks).to_dict()

        exec_check = self.execution_risk.check(intent)
        checks.append(exec_check)
        if not exec_check["passed"]:
            return RiskCheckResult(False, exec_check["reason"], checks).to_dict()

        global_check = self.global_risk.check(intent, global_state)
        checks.append(global_check)
        if not global_check["passed"]:
            return RiskCheckResult(False, global_check["reason"], checks).to_dict()

        venue = (intent.get("venue") or "").lower()

        # B3: fail closed when an intent carries PM-shaped fields but is not
        # tagged for the polymarket venue and no pm_state was supplied. This
        # prevents the PM layer from being silently bypassed by a caller who
        # forgot the venue tag.
        if venue != "polymarket" and pm_state is None and _intent_smells_like_pm(intent):
            fail = {
                "passed": False,
                "layer": "polymarket",
                "reason": "pm_intent_missing_venue_tag",
            }
            checks.append(fail)
            return RiskCheckResult(False, fail["reason"], checks).to_dict()

        if venue == "polymarket" or pm_state is not None:
            # M7: re-fetch the strategy mode from the DB and reject the
            # intent if it disagrees with what the caller claims.
            if self._pm_strategy_repo is not None and intent.get("pm_strategy_id"):
                try:
                    db_mode = self._pm_strategy_repo(intent["pm_strategy_id"])
                except Exception as exc:  # noqa: BLE001 — fail closed
                    fail = {
                        "passed": False,
                        "layer": "polymarket",
                        "reason": f"pm_strategy_repo_error:{type(exc).__name__}",
                    }
                    checks.append(fail)
                    return RiskCheckResult(False, fail["reason"], checks).to_dict()
                if db_mode is None:
                    fail = {
                        "passed": False,
                        "layer": "polymarket",
                        "reason": "pm_strategy_unknown",
                    }
                    checks.append(fail)
                    return RiskCheckResult(False, fail["reason"], checks).to_dict()
                intent_mode = (intent.get("mode") or "").upper()
                if intent_mode != str(db_mode).upper():
                    fail = {
                        "passed": False,
                        "layer": "polymarket",
                        "reason": (
                            f"pm_mode_intent_db_mismatch: intent={intent_mode} "
                            f"db={db_mode}"
                        ),
                    }
                    checks.append(fail)
                    return RiskCheckResult(False, fail["reason"], checks).to_dict()

            pm_check = self.pm_risk.check(intent, pm_state)
            checks.append(pm_check)
            if not pm_check["passed"]:
                return RiskCheckResult(False, pm_check["reason"], checks).to_dict()

        return RiskCheckResult(True, "", checks).to_dict()
