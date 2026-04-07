"""Smoke tests for Polymarket Phase 1 ORM models.

We don't spin up a DB here — JSONB/UUID PG types do not run on SQLite.
We just verify imports, table names, and column presence so the model
file is exercised by CI (and so any future drift from the architecture
spec fails loudly).
"""

from shared.db.models import (
    PMCalibrationSnapshot,
    PMJurisdictionAttestation,
    PMMarket,
    PMOrder,
    PMPosition,
    PMPromotionAudit,
    PMResolutionScore,
    PMStrategy,
    Strategy,
)


def test_pm_market_columns():
    assert PMMarket.__tablename__ == "pm_markets"
    for col in (
        "venue", "venue_market_id", "question", "category", "outcomes",
        "total_volume", "expiry", "oracle_type", "is_active", "last_scanned_at",
    ):
        assert hasattr(PMMarket, col), col


def test_pm_strategy_columns():
    assert PMStrategy.__tablename__ == "pm_strategies"
    for col in (
        "strategy_id", "archetype", "mode", "bankroll_usd",
        "max_strategy_notional_usd", "max_trade_notional_usd",
        "kelly_cap", "min_edge_bps", "paused", "last_promotion_attempt_id",
    ):
        assert hasattr(PMStrategy, col), col


def test_pm_order_columns():
    assert PMOrder.__tablename__ == "pm_orders"
    for col in (
        "pm_strategy_id", "pm_market_id", "outcome_token_id", "side",
        "qty_shares", "limit_price", "mode", "status", "venue_order_id",
        "fees_paid_usd", "slippage_bps", "f9_score",
        "jurisdiction_attestation_id", "arb_group_id",
        "submitted_at", "filled_at", "cancelled_at",
    ):
        assert hasattr(PMOrder, col), col


def test_pm_position_columns():
    assert PMPosition.__tablename__ == "pm_positions"
    for col in (
        "pm_strategy_id", "pm_market_id", "outcome_token_id", "qty_shares",
        "avg_entry_price", "mode", "unrealized_pnl_usd", "realized_pnl_usd",
        "opened_at", "closed_at",
    ):
        assert hasattr(PMPosition, col), col


def test_pm_calibration_columns():
    assert PMCalibrationSnapshot.__tablename__ == "pm_calibration_snapshots"
    for col in (
        "pm_strategy_id", "category", "window_days", "n_trades", "n_resolved",
        "brier", "log_loss", "reliability_bins", "sharpe", "max_drawdown_pct",
    ):
        assert hasattr(PMCalibrationSnapshot, col), col


def test_pm_resolution_columns():
    assert PMResolutionScore.__tablename__ == "pm_resolution_scores"
    for col in (
        "pm_market_id", "oracle_type", "prior_disputes", "llm_ambiguity_score",
        "llm_rationale", "final_score", "tradeable", "scored_at", "model_version",
    ):
        assert hasattr(PMResolutionScore, col), col


def test_pm_promotion_audit_columns():
    assert PMPromotionAudit.__tablename__ == "pm_promotion_audit"
    for col in (
        "pm_strategy_id", "actor_user_id", "action", "outcome",
        "gate_evaluations", "attached_backtest_id",
        "jurisdiction_attestation_id", "previous_mode", "new_mode", "notes",
    ):
        assert hasattr(PMPromotionAudit, col), col


def test_pm_jurisdiction_attestation_columns():
    assert PMJurisdictionAttestation.__tablename__ == "pm_jurisdiction_attestations"
    for col in (
        "user_id", "attestation_text_hash", "acknowledged_geoblock",
        "ip_at_attestation", "user_agent", "valid_until", "created_at",
    ):
        assert hasattr(PMJurisdictionAttestation, col), col


def test_strategy_has_mode_and_venue():
    """Phase 1 also adds mode/venue to the existing strategies table."""
    assert hasattr(Strategy, "mode")
    assert hasattr(Strategy, "venue")
