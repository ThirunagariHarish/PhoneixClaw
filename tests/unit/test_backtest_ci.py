"""Unit tests for BacktestCIService — Phase 0: Verifiable Alpha CI.

Tests cover:
- _evaluate_thresholds() for all three outcomes: passed, borderline, failed
- _is_borderline() edge cases
- run_ci_for_improvement() integration path (mocked DB session)
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.src.services.backtest_ci import (
    BORDERLINE_TOLERANCE,
    THRESHOLDS,
    BacktestCIService,
)

# ---------------------------------------------------------------------------
# Helpers to build lightweight fake objects
# ---------------------------------------------------------------------------


def _make_svc() -> BacktestCIService:
    """Return a BacktestCIService with a stub session (not used in pure-logic tests)."""
    return BacktestCIService(session=MagicMock())  # type: ignore[arg-type]


def _passing_metrics() -> dict[str, Any]:
    """Metrics that comfortably pass every threshold."""
    return {
        "sharpe": 1.2,         # threshold 0.8
        "win_rate": 0.60,      # threshold 0.53
        "max_drawdown": -0.08, # threshold -0.15  (less negative = passes)
        "profit_factor": 1.8,  # threshold 1.3
        "trade_count": 30,     # threshold 15
    }


# ---------------------------------------------------------------------------
# _evaluate_thresholds — all-pass
# ---------------------------------------------------------------------------


class TestEvaluateThresholdsAllPass:
    def test_returns_passed_status(self):
        svc = _make_svc()
        status, passed, missed = svc._evaluate_thresholds(_passing_metrics())
        assert status == "passed"
        assert passed is True
        assert missed == []

    def test_exact_threshold_values_pass(self):
        """Metrics at exactly the threshold value should pass (>=)."""
        svc = _make_svc()
        exact = {
            "sharpe": THRESHOLDS["sharpe_ratio"],
            "win_rate": THRESHOLDS["win_rate"],
            "max_drawdown": THRESHOLDS["max_drawdown"],
            "profit_factor": THRESHOLDS["profit_factor"],
            "trade_count": THRESHOLDS["min_trades"],
        }
        status, passed, missed = svc._evaluate_thresholds(exact)
        assert status == "passed"
        assert passed is True
        assert missed == []


# ---------------------------------------------------------------------------
# _evaluate_thresholds — borderline (1 threshold missed by < 10 %)
# ---------------------------------------------------------------------------


class TestEvaluateThresholdsBorderline:
    def test_sharpe_borderline_5pct_miss(self):
        """sharpe_ratio = 0.76 is 5 % below threshold 0.8 → borderline."""
        svc = _make_svc()
        metrics = _passing_metrics()
        # 5 % below 0.8: 0.8 * 0.95 = 0.76
        metrics["sharpe"] = 0.76
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "borderline"
        assert passed is False
        assert "sharpe_ratio" in missed

    def test_win_rate_borderline(self):
        """win_rate slightly below 0.53 within 10 % tolerance → borderline."""
        svc = _make_svc()
        metrics = _passing_metrics()
        # 9 % below 0.53: threshold 0.53, tol = 0.053 → actual = 0.53 - 0.05 = 0.48 is within tol
        metrics["win_rate"] = 0.52  # miss = 0.01, tol = 0.053 → borderline
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "borderline"
        assert passed is False
        assert "win_rate" in missed

    def test_max_drawdown_borderline(self):
        """max_drawdown = -0.164 is within 10 % of -0.15 → borderline."""
        svc = _make_svc()
        metrics = _passing_metrics()
        # tolerance = abs(-0.15) * 0.10 = 0.015; miss = -0.15 - (-0.164) = 0.014 < 0.015 → borderline
        metrics["max_drawdown"] = -0.164
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "borderline"
        assert passed is False
        assert "max_drawdown" in missed

    def test_profit_factor_borderline(self):
        """profit_factor = 1.25 is within 10 % of 1.3 → borderline."""
        svc = _make_svc()
        metrics = _passing_metrics()
        metrics["profit_factor"] = 1.25  # miss = 0.05, tol = 0.13 → borderline
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "borderline"
        assert passed is False
        assert "profit_factor" in missed

    def test_min_trades_borderline(self):
        """trade_count = 14 is within 10 % of 15 → borderline."""
        svc = _make_svc()
        metrics = _passing_metrics()
        metrics["trade_count"] = 14  # miss = 1, tol = 1.5 → borderline
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "borderline"
        assert passed is False
        assert "min_trades" in missed


# ---------------------------------------------------------------------------
# _evaluate_thresholds — failed (2+ misses OR single miss > 10 %)
# ---------------------------------------------------------------------------


class TestEvaluateThresholdsFailed:
    def test_two_thresholds_failing(self):
        """Two thresholds below minimum → failed, not borderline."""
        svc = _make_svc()
        metrics = _passing_metrics()
        metrics["sharpe"] = 0.5          # clearly below 0.8
        metrics["win_rate"] = 0.40       # clearly below 0.53
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "failed"
        assert passed is False
        assert "sharpe_ratio" in missed
        assert "win_rate" in missed

    def test_single_threshold_failing_beyond_tolerance(self):
        """sharpe_ratio 15 % below threshold → failed (not borderline)."""
        svc = _make_svc()
        metrics = _passing_metrics()
        # 15 % below 0.8: 0.8 * 0.85 = 0.68
        metrics["sharpe"] = 0.68
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "failed"
        assert passed is False
        assert "sharpe_ratio" in missed

    def test_max_drawdown_failing_beyond_tolerance(self):
        """max_drawdown = -0.18 is 20 % beyond -0.15 → failed."""
        svc = _make_svc()
        metrics = _passing_metrics()
        metrics["max_drawdown"] = -0.18  # miss = 0.03, tol = 0.015 → NOT borderline
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "failed"
        assert passed is False
        assert "max_drawdown" in missed

    def test_all_thresholds_zero_metrics(self):
        """All-zero metrics → failed with 4 misses (max_drawdown=0.0 *passes* since 0 > -0.15)."""
        svc = _make_svc()
        metrics = {
            "sharpe": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,  # 0.0 > -0.15 → PASSES (no drawdown is good)
            "profit_factor": 0.0,
            "trade_count": 0,
        }
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "failed"
        assert passed is False
        # max_drawdown passes because 0.0 >= -0.15; the other 4 fail
        assert len(missed) == 4
        assert "max_drawdown" not in missed

    def test_borderline_plus_another_failure_is_failed(self):
        """1 borderline miss + 1 additional miss → failed (not borderline)."""
        svc = _make_svc()
        metrics = _passing_metrics()
        metrics["sharpe"] = 0.76    # borderline miss
        metrics["win_rate"] = 0.40  # hard miss
        status, passed, missed = svc._evaluate_thresholds(metrics)
        assert status == "failed"
        assert passed is False


# ---------------------------------------------------------------------------
# _is_borderline edge cases
# ---------------------------------------------------------------------------


class TestIsBorderline:
    def test_exactly_at_threshold_is_not_borderline(self):
        svc = _make_svc()
        assert svc._is_borderline("sharpe_ratio", 0.8, 0.8) is False

    def test_above_threshold_is_not_borderline(self):
        svc = _make_svc()
        assert svc._is_borderline("sharpe_ratio", 0.9, 0.8) is False

    def test_just_inside_tolerance(self):
        """Exactly BORDERLINE_TOLERANCE below threshold should be borderline."""
        svc = _make_svc()
        threshold = 1.0
        actual = threshold * (1 - BORDERLINE_TOLERANCE)  # e.g. 0.90 if tol=10%
        assert svc._is_borderline("profit_factor", actual, threshold) is True

    def test_just_outside_tolerance(self):
        """One unit past tolerance should NOT be borderline."""
        svc = _make_svc()
        threshold = 1.0
        # miss = threshold * tol + epsilon
        actual = threshold * (1 - BORDERLINE_TOLERANCE) - 0.001
        assert svc._is_borderline("profit_factor", actual, threshold) is False

    def test_negative_threshold_within_tolerance(self):
        """max_drawdown tolerance works with negative threshold value."""
        svc = _make_svc()
        threshold = -0.15
        # tolerance = abs(-0.15) * 0.10 = 0.015
        # borderline if miss < 0.015; use -0.160 → miss = 0.010 < 0.015 ✓
        assert svc._is_borderline("max_drawdown", -0.160, threshold) is True
        # -0.164 → miss = 0.014 < 0.015 → also borderline ✓
        assert svc._is_borderline("max_drawdown", -0.164, threshold) is True

    def test_negative_threshold_outside_tolerance(self):
        """max_drawdown 20 % worse is NOT borderline."""
        svc = _make_svc()
        assert svc._is_borderline("max_drawdown", -0.18, -0.15) is False

    def test_zero_threshold_non_borderline(self):
        """When threshold = 0, tolerance = 0; any negative actual fails but is not borderline."""
        svc = _make_svc()
        # abs(0) * tol = 0 → tolerance = 0 → miss > 0 → not borderline
        assert svc._is_borderline("some_metric", -0.001, 0.0) is False


# ---------------------------------------------------------------------------
# run_ci_for_improvement — async integration test with mocked session
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_ci_sets_running_then_evaluates():
    """run_ci_for_improvement should update the item with a final CI status."""
    agent_id = uuid.uuid4()
    imp_id = "imp-001"

    # Build a fake agent with one pending improvement
    fake_agent = types.SimpleNamespace(
        id=agent_id,
        user_id=uuid.uuid4(),
        pending_improvements={
            "items": [{"id": imp_id, "type": "tighten_stop_loss", "description": "test"}],
            "last_staged_at": datetime.now(timezone.utc).isoformat(),
        },
        updated_at=datetime.now(timezone.utc),
    )

    # Fake backtest with good metrics
    fake_backtest = types.SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=agent_id,
        status="COMPLETED",
        sharpe_ratio=1.0,
        win_rate=0.60,
        max_drawdown=-0.10,
        total_trades=25,
        metrics={"profit_factor": 1.5},
        created_at=datetime.now(timezone.utc),
    )

    # Mock AsyncSession
    session = AsyncMock()

    def _fake_execute(stmt: Any) -> Any:
        """Return fake results based on the model being queried."""
        class _FakeResult:
            def __init__(self, obj: Any) -> None:
                self._obj = obj

            def scalar_one_or_none(self) -> Any:
                return self._obj

        # Inspect the WHERE clause to decide which model to return
        stmt_str = str(stmt)
        if "agent_backtests" in stmt_str:
            return _FakeResult(fake_backtest)
        return _FakeResult(fake_agent)

    session.execute = AsyncMock(side_effect=_fake_execute)
    session.commit = AsyncMock()
    session.add = MagicMock()

    svc = BacktestCIService(session)
    result = await svc.run_ci_for_improvement(agent_id, imp_id)

    assert result["id"] == imp_id
    assert result["backtest_status"] in ("passed", "borderline", "failed")
    assert "backtest_passed" in result
    assert "backtest_metrics" in result
    assert "backtest_run_at" in result
    assert "backtest_thresholds_missed" in result
    # With good metrics it should pass
    assert result["backtest_status"] == "passed"
    assert result["backtest_passed"] is True


@pytest.mark.anyio
async def test_run_ci_raises_key_error_for_unknown_improvement():
    agent_id = uuid.uuid4()
    fake_agent = types.SimpleNamespace(
        id=agent_id,
        user_id=uuid.uuid4(),
        pending_improvements={"items": []},
        updated_at=datetime.now(timezone.utc),
    )

    session = AsyncMock()

    class _R:
        def scalar_one_or_none(self) -> Any:
            return fake_agent

    session.execute = AsyncMock(return_value=_R())
    session.commit = AsyncMock()

    svc = BacktestCIService(session)
    with pytest.raises(KeyError):
        await svc.run_ci_for_improvement(agent_id, "nonexistent-id")


@pytest.mark.anyio
async def test_run_ci_raises_value_error_for_unknown_agent():
    session = AsyncMock()

    class _R:
        def scalar_one_or_none(self) -> Any:
            return None

    session.execute = AsyncMock(return_value=_R())

    svc = BacktestCIService(session)
    with pytest.raises(ValueError):
        await svc.run_ci_for_improvement(uuid.uuid4(), "imp-001")
