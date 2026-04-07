"""Unit tests for the Polymarket promotion gate engine (Phase 11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from shared.polymarket.promotion_gate import (
    CalibrationRow,
    PromotionGateConfig,
    PromotionGateEngine,
    PromotionGateError,
    StrategySnapshot,
    TradeRow,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeProvider:
    snapshot: StrategySnapshot
    audits: list[dict[str, Any]] = field(default_factory=list)
    mode_writes: list[tuple[UUID, str]] = field(default_factory=list)

    def load_snapshot(self, pm_strategy_id: UUID) -> StrategySnapshot:
        return self.snapshot

    def write_audit(self, **kwargs: Any) -> UUID:
        self.audits.append(kwargs)
        return uuid4()

    def set_strategy_mode(self, pm_strategy_id: UUID, new_mode: str) -> None:
        self.mode_writes.append((pm_strategy_id, new_mode))
        # reflect for follow-up assertions
        self.snapshot = StrategySnapshot(
            pm_strategy_id=self.snapshot.pm_strategy_id,
            current_mode=new_mode,
            created_at=self.snapshot.created_at,
            trades=self.snapshot.trades,
            calibration=self.snapshot.calibration,
            f9_scores_by_market=self.snapshot.f9_scores_by_market,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


NOW = datetime(2026, 4, 7, 12, 0, 0, tzinfo=timezone.utc)


def _cfg(**overrides: Any) -> PromotionGateConfig:
    base = dict(
        soak_days=7,
        min_trades=50,
        max_brier=0.20,
        min_sharpe=1.0,
        max_drawdown_pct=5.0,
        min_f9_score=0.70,
    )
    base.update(overrides)
    return PromotionGateConfig(**base)


def _passing_snapshot(n_markets: int = 3, n_trades: int = 60) -> StrategySnapshot:
    market_ids = [uuid4() for _ in range(n_markets)]
    trades = [
        TradeRow(
            submitted_at=NOW - timedelta(days=2, hours=i),
            pm_market_id=market_ids[i % n_markets],
            f9_score=0.85,
        )
        for i in range(n_trades)
    ]
    return StrategySnapshot(
        pm_strategy_id=uuid4(),
        current_mode="PAPER",
        created_at=NOW - timedelta(days=10),
        trades=trades,
        calibration=CalibrationRow(
            n_trades=n_trades,
            brier=0.15,
            sharpe=1.5,
            max_drawdown_pct=3.2,
            window_days=7,
        ),
        f9_scores_by_market={mid: 0.82 for mid in market_ids},
        last_successful_backtest_at=NOW - timedelta(days=5),
    )


def _engine(snapshot: StrategySnapshot, **cfg_overrides: Any) -> tuple[PromotionGateEngine, FakeProvider]:
    provider = FakeProvider(snapshot=snapshot)
    engine = PromotionGateEngine(_cfg(**cfg_overrides), provider, now_fn=lambda: NOW)
    return engine, provider


# ---------------------------------------------------------------------------
# Pass case
# ---------------------------------------------------------------------------


def test_evaluate_passes_when_all_gates_satisfied():
    engine, _ = _engine(_passing_snapshot())
    result = engine.evaluate(uuid4())
    assert result.passed, result.failure_reasons
    assert result.failure_reasons == []
    names = {c.name for c in result.checks}
    assert names == {
        "paper_soak_days",
        "min_trades",
        "brier",
        "sharpe",
        "max_drawdown_pct",
        "f9_score_per_market",
        "successful_backtest_attached",
    }
    assert all(c.passed for c in result.checks)
    assert result.config_snapshot["min_trades"] == 50


def test_promote_flips_mode_and_writes_audit_on_pass():
    snap = _passing_snapshot()
    engine, provider = _engine(snap)
    actor = uuid4()
    result = engine.promote(snap.pm_strategy_id, actor_user_id=actor, notes="ship it")
    assert result.passed
    assert provider.mode_writes == [(snap.pm_strategy_id, "LIVE")]
    assert len(provider.audits) == 1
    a = provider.audits[0]
    assert a["action"] == "promote"
    assert a["outcome"] == "pass"
    assert a["previous_mode"] == "PAPER"
    assert a["new_mode"] == "LIVE"
    assert a["actor_user_id"] == actor
    assert a["gate_evaluations"]["passed"] is True
    assert "config_snapshot" in a["gate_evaluations"]
    assert "metrics_snapshot" in a["gate_evaluations"]


def test_attempt_writes_audit_on_pass_without_mode_change():
    snap = _passing_snapshot()
    engine, provider = _engine(snap)
    result = engine.attempt(snap.pm_strategy_id, actor_user_id=None)
    assert result.passed
    assert provider.mode_writes == []
    assert len(provider.audits) == 1
    assert provider.audits[0]["action"] == "attempt"
    assert provider.audits[0]["outcome"] == "pass"
    assert provider.audits[0]["new_mode"] is None


# ---------------------------------------------------------------------------
# Failure modes — each independently
# ---------------------------------------------------------------------------


def _fail_only(result, gate_name: str) -> None:
    failed = [c.name for c in result.checks if not c.passed]
    assert failed == [gate_name], f"expected only {gate_name} to fail, got {failed}"
    assert not result.passed


def test_fail_soak_too_short():
    snap = _passing_snapshot()
    snap = StrategySnapshot(
        pm_strategy_id=snap.pm_strategy_id,
        current_mode=snap.current_mode,
        created_at=NOW - timedelta(days=3),  # only 3d, need 7
        trades=snap.trades,
        calibration=snap.calibration,
        f9_scores_by_market=snap.f9_scores_by_market,
        last_successful_backtest_at=snap.last_successful_backtest_at,
    )
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    _fail_only(result, "paper_soak_days")


def test_fail_too_few_trades():
    snap = _passing_snapshot(n_trades=10)
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    _fail_only(result, "min_trades")


def test_fail_brier_too_high():
    snap = _passing_snapshot()
    snap = StrategySnapshot(
        **{**snap.__dict__, "calibration": CalibrationRow(
            n_trades=60, brier=0.35, sharpe=1.5, max_drawdown_pct=3.2, window_days=7
        )},
    )
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    _fail_only(result, "brier")


def test_fail_sharpe_too_low():
    snap = _passing_snapshot()
    snap = StrategySnapshot(
        **{**snap.__dict__, "calibration": CalibrationRow(
            n_trades=60, brier=0.15, sharpe=0.4, max_drawdown_pct=3.2, window_days=7
        )},
    )
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    _fail_only(result, "sharpe")


def test_fail_drawdown_too_deep():
    snap = _passing_snapshot()
    snap = StrategySnapshot(
        **{**snap.__dict__, "calibration": CalibrationRow(
            n_trades=60, brier=0.15, sharpe=1.5, max_drawdown_pct=9.9, window_days=7
        )},
    )
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    _fail_only(result, "max_drawdown_pct")


def test_fail_f9_below_on_one_market():
    snap = _passing_snapshot()
    bad_market = next(iter(snap.f9_scores_by_market.keys()))
    new_scores = dict(snap.f9_scores_by_market)
    new_scores[bad_market] = 0.40  # below 0.70
    snap = StrategySnapshot(**{**snap.__dict__, "f9_scores_by_market": new_scores})
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    _fail_only(result, "f9_score_per_market")
    f9_check = next(c for c in result.checks if c.name == "f9_score_per_market")
    assert f9_check.observed["below_threshold"]


def test_fail_f9_missing_for_a_traded_market():
    snap = _passing_snapshot()
    drop = next(iter(snap.f9_scores_by_market.keys()))
    new_scores = {k: v for k, v in snap.f9_scores_by_market.items() if k != drop}
    snap = StrategySnapshot(**{**snap.__dict__, "f9_scores_by_market": new_scores})
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    _fail_only(result, "f9_score_per_market")
    f9_check = next(c for c in result.checks if c.name == "f9_score_per_market")
    assert f9_check.observed["missing"]


def test_fail_when_calibration_missing_entirely():
    snap = _passing_snapshot()
    snap = StrategySnapshot(**{**snap.__dict__, "calibration": None})
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    failed = {c.name for c in result.checks if not c.passed}
    assert failed == {"brier", "sharpe", "max_drawdown_pct"}
    assert not result.passed


# ---------------------------------------------------------------------------
# promote() failure path
# ---------------------------------------------------------------------------


def test_promote_blocks_and_writes_block_audit_on_failure():
    snap = _passing_snapshot(n_trades=5)  # too few trades
    engine, provider = _engine(snap)
    actor = uuid4()
    with pytest.raises(PromotionGateError) as ei:
        engine.promote(snap.pm_strategy_id, actor_user_id=actor)
    assert not ei.value.result.passed
    assert provider.mode_writes == []
    assert len(provider.audits) == 1
    a = provider.audits[0]
    assert a["action"] == "promote"
    assert a["outcome"] == "block"
    assert a["new_mode"] is None
    assert a["previous_mode"] == "PAPER"
    assert a["actor_user_id"] == actor


def test_attempt_writes_fail_outcome_on_failure():
    snap = _passing_snapshot(n_trades=5)
    engine, provider = _engine(snap)
    result = engine.attempt(snap.pm_strategy_id, actor_user_id=None)
    assert not result.passed
    assert provider.audits[0]["action"] == "attempt"
    assert provider.audits[0]["outcome"] == "fail"
    assert provider.mode_writes == []


# ---------------------------------------------------------------------------
# Config-driven thresholds
# ---------------------------------------------------------------------------


def test_fail_when_no_successful_backtest_attached():
    snap = _passing_snapshot()
    snap = StrategySnapshot(**{**snap.__dict__, "last_successful_backtest_at": None})
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    _fail_only(result, "successful_backtest_attached")
    bt = next(c for c in result.checks if c.name == "successful_backtest_attached")
    assert bt.observed["last_successful_backtest_at"] is None


def test_fail_when_successful_backtest_older_than_30_days():
    snap = _passing_snapshot()
    snap = StrategySnapshot(
        **{**snap.__dict__, "last_successful_backtest_at": NOW - timedelta(days=45)}
    )
    engine, _ = _engine(snap)
    result = engine.evaluate(snap.pm_strategy_id)
    _fail_only(result, "successful_backtest_attached")


def test_backtest_age_window_is_config_driven():
    snap = _passing_snapshot()
    snap = StrategySnapshot(
        **{**snap.__dict__, "last_successful_backtest_at": NOW - timedelta(days=45)}
    )
    engine, _ = _engine(snap, max_backtest_age_days=60)
    result = engine.evaluate(snap.pm_strategy_id)
    assert result.passed, result.failure_reasons


def test_thresholds_are_config_driven_not_hardcoded():
    # A snapshot that fails default 0.20 brier...
    snap = _passing_snapshot()
    snap = StrategySnapshot(
        **{**snap.__dict__, "calibration": CalibrationRow(
            n_trades=60, brier=0.30, sharpe=1.5, max_drawdown_pct=3.2, window_days=7
        )},
    )
    # ...passes when the configured ceiling is loosened.
    engine, _ = _engine(snap, max_brier=0.40)
    result = engine.evaluate(snap.pm_strategy_id)
    assert result.passed, result.failure_reasons
