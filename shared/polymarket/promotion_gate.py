"""
Polymarket promotion gate engine (Phase 11).

Single source of truth for evaluating whether a PM strategy may transition
from PAPER to LIVE. Called from the API promotion endpoint, from CI/chaos
tests, and from the startup consistency check.

All thresholds are configuration-driven; no magic numbers in this module.
Every promote / demote / attempt writes an immutable row to
`pm_promotion_audit` via the injected repository.

Design notes:
- The engine is intentionally decoupled from SQLAlchemy. It depends on a
  small `PromotionGateDataProvider` protocol so unit tests can inject fake
  rows and the production wiring (Phase 10 API route) can plug in a
  repository backed by the real DB models in `shared/db/models/polymarket.py`.
- `evaluate()` is pure: it computes a `PromotionGateResult` and does not
  mutate state.
- `attempt()` evaluates and writes an audit row regardless of pass/fail.
- `promote()` only flips `pm_strategies.mode` to 'LIVE' after every gate
  passes; on failure it writes a `block` audit row and raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromotionGateConfig:
    """All thresholds for the PAPER -> LIVE gate. No defaults are hardcoded
    in the engine; callers must construct this from app config / env."""

    soak_days: int
    min_trades: int
    max_brier: float
    min_sharpe: float
    max_drawdown_pct: float
    min_f9_score: float
    max_backtest_age_days: int = 30

    def as_dict(self) -> dict[str, Any]:
        return {
            "soak_days": self.soak_days,
            "min_trades": self.min_trades,
            "max_brier": self.max_brier,
            "min_sharpe": self.min_sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
            "min_f9_score": self.min_f9_score,
            "max_backtest_age_days": self.max_backtest_age_days,
        }


# ---------------------------------------------------------------------------
# Snapshot data structures (DB-agnostic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeRow:
    """A single PM order/fill considered by the gate."""

    submitted_at: datetime
    pm_market_id: UUID
    f9_score: float | None


@dataclass(frozen=True)
class CalibrationRow:
    """Latest calibration snapshot for the strategy over the soak window."""

    n_trades: int
    brier: float | None
    sharpe: float | None
    max_drawdown_pct: float | None
    window_days: int


@dataclass(frozen=True)
class StrategySnapshot:
    """Everything the gate needs about a single PM strategy at evaluation time."""

    pm_strategy_id: UUID
    current_mode: str  # 'PAPER' or 'LIVE'
    created_at: datetime
    trades: list[TradeRow]
    calibration: CalibrationRow | None
    f9_scores_by_market: dict[UUID, float]  # latest F9 score per market id
    last_successful_backtest_at: datetime | None = None


# ---------------------------------------------------------------------------
# Gate result
# ---------------------------------------------------------------------------


@dataclass
class GateCheck:
    name: str
    passed: bool
    observed: Any
    threshold: Any
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "observed": self.observed,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass
class PromotionGateResult:
    passed: bool
    checks: list[GateCheck] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_audit_payload(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "failure_reasons": list(self.failure_reasons),
            "metrics_snapshot": dict(self.metrics_snapshot),
            "config_snapshot": dict(self.config_snapshot),
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Repository / data-provider protocol
# ---------------------------------------------------------------------------


class PromotionGateDataProvider(Protocol):
    """Surface the engine needs from persistence. Implemented by the
    PM repository in production and by a fake in unit tests."""

    def load_snapshot(self, pm_strategy_id: UUID) -> StrategySnapshot: ...

    def write_audit(
        self,
        *,
        pm_strategy_id: UUID,
        actor_user_id: UUID | None,
        action: str,
        outcome: str,
        gate_evaluations: dict[str, Any],
        previous_mode: str | None,
        new_mode: str | None,
        notes: str | None,
    ) -> UUID: ...

    def set_strategy_mode(self, pm_strategy_id: UUID, new_mode: str) -> None: ...


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PromotionGateError(Exception):
    """Raised when promote() is called but the gate did not pass."""

    def __init__(self, result: PromotionGateResult):
        self.result = result
        super().__init__(
            "Promotion gate failed: " + "; ".join(result.failure_reasons)
        )


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class PromotionGateEngine:
    """Evaluate PM strategy promotion gates and (optionally) flip mode."""

    def __init__(
        self,
        config: PromotionGateConfig,
        provider: PromotionGateDataProvider,
        *,
        now_fn: Any = None,
    ) -> None:
        self._cfg = config
        self._provider = provider
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    # -- public API --------------------------------------------------------

    def evaluate(self, pm_strategy_id: UUID) -> PromotionGateResult:
        """Pure evaluation; no DB writes. Returns a structured result."""
        snapshot = self._provider.load_snapshot(pm_strategy_id)
        return self._evaluate_snapshot(snapshot)

    def attempt(
        self,
        pm_strategy_id: UUID,
        actor_user_id: UUID | None,
        notes: str | None = None,
    ) -> PromotionGateResult:
        """Evaluate and write an audit row regardless of outcome.

        Use this when the API receives a promote request but you want the
        attempt logged even on failure. Does NOT mutate strategy mode.
        """
        snapshot = self._provider.load_snapshot(pm_strategy_id)
        result = self._evaluate_snapshot(snapshot)
        self._provider.write_audit(
            pm_strategy_id=pm_strategy_id,
            actor_user_id=actor_user_id,
            action="attempt",
            outcome="pass" if result.passed else "fail",
            gate_evaluations=result.to_audit_payload(),
            previous_mode=snapshot.current_mode,
            new_mode=None,
            notes=notes,
        )
        return result

    def promote(
        self,
        pm_strategy_id: UUID,
        actor_user_id: UUID | None,
        notes: str | None = None,
    ) -> PromotionGateResult:
        """Evaluate; on pass flip mode to LIVE and write a `promote` audit
        row; on fail write a `block` audit row and raise."""
        snapshot = self._provider.load_snapshot(pm_strategy_id)
        result = self._evaluate_snapshot(snapshot)
        if not result.passed:
            self._provider.write_audit(
                pm_strategy_id=pm_strategy_id,
                actor_user_id=actor_user_id,
                action="promote",
                outcome="block",
                gate_evaluations=result.to_audit_payload(),
                previous_mode=snapshot.current_mode,
                new_mode=None,
                notes=notes,
            )
            raise PromotionGateError(result)

        self._provider.set_strategy_mode(pm_strategy_id, "LIVE")
        self._provider.write_audit(
            pm_strategy_id=pm_strategy_id,
            actor_user_id=actor_user_id,
            action="promote",
            outcome="pass",
            gate_evaluations=result.to_audit_payload(),
            previous_mode=snapshot.current_mode,
            new_mode="LIVE",
            notes=notes,
        )
        return result

    # -- internals ---------------------------------------------------------

    def _evaluate_snapshot(self, snapshot: StrategySnapshot) -> PromotionGateResult:
        cfg = self._cfg
        now = self._now_fn()
        checks: list[GateCheck] = []

        # 1) Soak window
        soak_cutoff = now - timedelta(days=cfg.soak_days)
        soak_age_days = (now - snapshot.created_at).total_seconds() / 86400.0
        soak_passed = snapshot.created_at <= soak_cutoff
        checks.append(
            GateCheck(
                name="paper_soak_days",
                passed=soak_passed,
                observed=round(soak_age_days, 3),
                threshold=cfg.soak_days,
                detail="Strategy must exist in PAPER for at least the configured soak window.",
            )
        )

        # 2) Trade count within soak window
        trades_in_window = [t for t in snapshot.trades if t.submitted_at >= soak_cutoff]
        n_trades = len(trades_in_window)
        trades_passed = n_trades >= cfg.min_trades
        checks.append(
            GateCheck(
                name="min_trades",
                passed=trades_passed,
                observed=n_trades,
                threshold=cfg.min_trades,
            )
        )

        cal = snapshot.calibration

        # 3) Brier
        brier = cal.brier if cal else None
        brier_passed = brier is not None and brier <= cfg.max_brier
        checks.append(
            GateCheck(
                name="brier",
                passed=brier_passed,
                observed=brier,
                threshold=cfg.max_brier,
                detail="Lower is better; calibration over soak window.",
            )
        )

        # 4) Sharpe
        sharpe = cal.sharpe if cal else None
        sharpe_passed = sharpe is not None and sharpe >= cfg.min_sharpe
        checks.append(
            GateCheck(
                name="sharpe",
                passed=sharpe_passed,
                observed=sharpe,
                threshold=cfg.min_sharpe,
            )
        )

        # 5) Max drawdown
        dd = cal.max_drawdown_pct if cal else None
        dd_passed = dd is not None and dd <= cfg.max_drawdown_pct
        checks.append(
            GateCheck(
                name="max_drawdown_pct",
                passed=dd_passed,
                observed=dd,
                threshold=cfg.max_drawdown_pct,
                detail="Worst peak-to-trough drawdown over soak window.",
            )
        )

        # 6) F9 score above threshold on EVERY traded market
        traded_market_ids = {t.pm_market_id for t in trades_in_window}
        missing: list[str] = []
        below: list[str] = []
        for mid in traded_market_ids:
            score = snapshot.f9_scores_by_market.get(mid)
            if score is None:
                missing.append(str(mid))
            elif score < cfg.min_f9_score:
                below.append(f"{mid}={score}")
        f9_passed = (
            bool(traded_market_ids) and not missing and not below
        )
        f9_detail_parts: list[str] = []
        if not traded_market_ids:
            f9_detail_parts.append("no traded markets in soak window")
        if missing:
            f9_detail_parts.append(f"missing F9 scores for: {', '.join(sorted(missing))}")
        if below:
            f9_detail_parts.append(f"below threshold: {', '.join(sorted(below))}")
        checks.append(
            GateCheck(
                name="f9_score_per_market",
                passed=f9_passed,
                observed={
                    "n_markets": len(traded_market_ids),
                    "missing": sorted(missing),
                    "below_threshold": sorted(below),
                },
                threshold=cfg.min_f9_score,
                detail="; ".join(f9_detail_parts) or "all traded markets pass F9",
            )
        )

        # 7) Successful backtest attached and fresh (PRD §5 rule 1)
        bt_at = snapshot.last_successful_backtest_at
        bt_cutoff = now - timedelta(days=cfg.max_backtest_age_days)
        if bt_at is None:
            bt_passed = False
            bt_detail = "no successful backtest attached to this strategy"
            bt_age_days: float | None = None
        else:
            bt_age_days = (now - bt_at).total_seconds() / 86400.0
            bt_passed = bt_at >= bt_cutoff
            bt_detail = (
                "attached backtest is within freshness window"
                if bt_passed
                else f"attached backtest is {round(bt_age_days, 1)}d old; max allowed {cfg.max_backtest_age_days}d"
            )
        checks.append(
            GateCheck(
                name="successful_backtest_attached",
                passed=bt_passed,
                observed=(
                    {"last_successful_backtest_at": bt_at.isoformat(), "age_days": round(bt_age_days, 3)}
                    if bt_at is not None and bt_age_days is not None
                    else {"last_successful_backtest_at": None}
                ),
                threshold={"max_age_days": cfg.max_backtest_age_days},
                detail=bt_detail,
            )
        )

        passed = all(c.passed for c in checks)
        failure_reasons = [
            f"{c.name}: observed={c.observed} threshold={c.threshold}"
            for c in checks
            if not c.passed
        ]

        metrics = {
            "n_trades_in_window": n_trades,
            "soak_age_days": round(soak_age_days, 3),
            "brier": brier,
            "sharpe": sharpe,
            "max_drawdown_pct": dd,
            "n_traded_markets": len(traded_market_ids),
            "calibration_window_days": cal.window_days if cal else None,
            "last_successful_backtest_at": (
                snapshot.last_successful_backtest_at.isoformat()
                if snapshot.last_successful_backtest_at is not None
                else None
            ),
        }

        return PromotionGateResult(
            passed=passed,
            checks=checks,
            failure_reasons=failure_reasons,
            metrics_snapshot=metrics,
            config_snapshot=cfg.as_dict(),
            evaluated_at=now,
        )


__all__ = [
    "PromotionGateConfig",
    "PromotionGateEngine",
    "PromotionGateDataProvider",
    "PromotionGateError",
    "PromotionGateResult",
    "GateCheck",
    "StrategySnapshot",
    "TradeRow",
    "CalibrationRow",
]
