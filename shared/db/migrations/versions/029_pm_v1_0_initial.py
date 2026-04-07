"""Polymarket v1.0 initial schema — pm_* tables + strategies.mode/venue.

Revision ID: 029
Revises: 028
Create Date: 2026-04-07

Phase 1 of the Polymarket tab feature. See:
- docs/prd/polymarket-tab.md
- docs/architecture/polymarket-tab.md  (sections 4.1 - 4.9)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name=:n"),
        {"n": name},
    ).first())


def _has_column(table: str, col: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"),
        {"t": table, "c": col},
    ).first())


def upgrade() -> None:
    # --- strategies.mode + venue (back-compat defaults) ---------------------
    if not _has_column("strategies", "mode"):
        op.add_column(
            "strategies",
            sa.Column("mode", sa.String(10), nullable=False, server_default="PAPER"),
        )
    if not _has_column("strategies", "venue"):
        op.add_column(
            "strategies",
            sa.Column("venue", sa.String(20), nullable=False, server_default="equities"),
        )

    # --- pm_markets ---------------------------------------------------------
    if not _has_table("pm_markets"):
        op.create_table(
            "pm_markets",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("venue", sa.String(20), nullable=False, server_default="polymarket"),
            sa.Column("venue_market_id", sa.String(128), nullable=False),
            sa.Column("slug", sa.String(255), nullable=True),
            sa.Column("question", sa.Text, nullable=False),
            sa.Column("category", sa.String(50), nullable=True),
            sa.Column("outcomes", postgresql.JSONB, nullable=False, server_default="[]"),
            sa.Column("total_volume", sa.Float, nullable=True),
            sa.Column("liquidity_usd", sa.Float, nullable=True),
            sa.Column("expiry", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolution_source", sa.String(255), nullable=True),
            sa.Column("oracle_type", sa.String(30), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
            sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
        )
        op.create_index(
            "ux_pm_markets_venue_market", "pm_markets",
            ["venue", "venue_market_id"], unique=True,
        )
        op.create_index("ix_pm_markets_category_expiry", "pm_markets", ["category", "expiry"])
        op.create_index(
            "ix_pm_markets_active_scanned", "pm_markets",
            ["is_active", "last_scanned_at"],
        )
        op.create_index("ix_pm_markets_total_volume", "pm_markets", ["total_volume"])

    # --- pm_jurisdiction_attestations (created early — referenced by orders/audit)
    if not _has_table("pm_jurisdiction_attestations"):
        op.create_table(
            "pm_jurisdiction_attestations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("attestation_text_hash", sa.String(64), nullable=False),
            sa.Column("acknowledged_geoblock", sa.Boolean, nullable=False,
                      server_default=sa.text("FALSE")),
            sa.Column("ip_at_attestation", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.Text, nullable=True),
            sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
        )
        op.create_index(
            "ix_pm_jurisdiction_user_valid", "pm_jurisdiction_attestations",
            ["user_id", "valid_until"],
        )

    # --- pm_strategies ------------------------------------------------------
    if not _has_table("pm_strategies"):
        op.create_table(
            "pm_strategies",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("strategy_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("strategies.id", ondelete="CASCADE"),
                      nullable=False, unique=True),
            sa.Column("archetype", sa.String(40), nullable=False),
            sa.Column("mode", sa.String(10), nullable=False, server_default="PAPER"),
            sa.Column("bankroll_usd", sa.Float, nullable=False, server_default="5000"),
            sa.Column("max_strategy_notional_usd", sa.Float, nullable=False,
                      server_default="1000"),
            sa.Column("max_trade_notional_usd", sa.Float, nullable=False,
                      server_default="100"),
            sa.Column("kelly_cap", sa.Float, nullable=False, server_default="0.25"),
            sa.Column("min_edge_bps", sa.Integer, nullable=True),
            sa.Column("paused", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
            sa.Column("last_promotion_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
            sa.CheckConstraint("mode IN ('PAPER','LIVE')", name="ck_pm_strategies_mode"),
        )
        op.create_index("ix_pm_strategies_mode_paused", "pm_strategies", ["mode", "paused"])
        op.create_index("ix_pm_strategies_archetype", "pm_strategies", ["archetype"])

    # --- pm_orders ----------------------------------------------------------
    if not _has_table("pm_orders"):
        op.create_table(
            "pm_orders",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("pm_strategy_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("pm_strategies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("pm_market_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("pm_markets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("outcome_token_id", sa.String(128), nullable=False),
            sa.Column("side", sa.String(4), nullable=False),
            sa.Column("qty_shares", sa.Float, nullable=False),
            sa.Column("limit_price", sa.Float, nullable=False),
            sa.Column("mode", sa.String(10), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("venue_order_id", sa.String(128), nullable=True),
            sa.Column("fees_paid_usd", sa.Float, nullable=True),
            sa.Column("slippage_bps", sa.Float, nullable=True),
            sa.Column("f9_score", sa.Float, nullable=True),
            sa.Column("jurisdiction_attestation_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("pm_jurisdiction_attestations.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("arb_group_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
            sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_pm_orders_strategy_submitted", "pm_orders",
                        ["pm_strategy_id", "submitted_at"])
        op.create_index("ix_pm_orders_market_status", "pm_orders",
                        ["pm_market_id", "status"])
        op.create_index("ix_pm_orders_arb_group", "pm_orders", ["arb_group_id"])

    # --- pm_positions -------------------------------------------------------
    if not _has_table("pm_positions"):
        op.create_table(
            "pm_positions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("pm_strategy_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("pm_strategies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("pm_market_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("pm_markets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("outcome_token_id", sa.String(128), nullable=False),
            sa.Column("qty_shares", sa.Float, nullable=False),
            sa.Column("avg_entry_price", sa.Float, nullable=False),
            sa.Column("mode", sa.String(10), nullable=False),
            sa.Column("unrealized_pnl_usd", sa.Float, nullable=True),
            sa.Column("realized_pnl_usd", sa.Float, nullable=True),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ux_pm_positions_open",
            "pm_positions",
            ["pm_strategy_id", "pm_market_id", "outcome_token_id", "mode"],
            unique=True,
            postgresql_where=sa.text("closed_at IS NULL"),
        )

    # --- pm_calibration_snapshots -------------------------------------------
    if not _has_table("pm_calibration_snapshots"):
        op.create_table(
            "pm_calibration_snapshots",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("pm_strategy_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("pm_strategies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("category", sa.String(50), nullable=True),
            sa.Column("window_days", sa.Integer, nullable=False),
            sa.Column("n_trades", sa.Integer, nullable=False, server_default="0"),
            sa.Column("n_resolved", sa.Integer, nullable=False, server_default="0"),
            sa.Column("brier", sa.Float, nullable=True),
            sa.Column("log_loss", sa.Float, nullable=True),
            sa.Column("reliability_bins", postgresql.JSONB, nullable=False, server_default="[]"),
            sa.Column("sharpe", sa.Float, nullable=True),
            sa.Column("max_drawdown_pct", sa.Float, nullable=True),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
        )
        op.create_index("ix_pm_calibration_strategy_time", "pm_calibration_snapshots",
                        ["pm_strategy_id", "computed_at"])

    # --- pm_resolution_scores -----------------------------------------------
    if not _has_table("pm_resolution_scores"):
        op.create_table(
            "pm_resolution_scores",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("pm_market_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("pm_markets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("oracle_type", sa.String(30), nullable=True),
            sa.Column("prior_disputes", sa.Integer, nullable=False, server_default="0"),
            sa.Column("llm_ambiguity_score", sa.Float, nullable=True),
            sa.Column("llm_rationale", sa.Text, nullable=True),
            sa.Column("final_score", sa.Float, nullable=True),
            sa.Column("tradeable", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
            sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
            sa.Column("model_version", sa.String(30), nullable=True),
        )
        op.create_index("ix_pm_resolution_market_time", "pm_resolution_scores",
                        ["pm_market_id", "scored_at"])
        op.create_index("ix_pm_resolution_tradeable", "pm_resolution_scores", ["tradeable"])

    # --- pm_promotion_audit -------------------------------------------------
    if not _has_table("pm_promotion_audit"):
        op.create_table(
            "pm_promotion_audit",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("pm_strategy_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("pm_strategies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("actor_user_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("outcome", sa.String(20), nullable=False),
            sa.Column("gate_evaluations", postgresql.JSONB, nullable=False, server_default="{}"),
            sa.Column("attached_backtest_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("jurisdiction_attestation_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("pm_jurisdiction_attestations.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("previous_mode", sa.String(10), nullable=True),
            sa.Column("new_mode", sa.String(10), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
        )
        op.create_index("ix_pm_promotion_audit_strategy_time", "pm_promotion_audit",
                        ["pm_strategy_id", "created_at"])


def downgrade() -> None:
    # Drop in reverse dependency order.
    for tbl in (
        "pm_promotion_audit",
        "pm_resolution_scores",
        "pm_calibration_snapshots",
        "pm_positions",
        "pm_orders",
        "pm_strategies",
        "pm_jurisdiction_attestations",
        "pm_markets",
    ):
        if _has_table(tbl):
            op.drop_table(tbl)

    if _has_column("strategies", "venue"):
        op.drop_column("strategies", "venue")
    if _has_column("strategies", "mode"):
        op.drop_column("strategies", "mode")
