"""Polymarket v1.0 hardening — paper_mode_since + immutable audit + RESTRICT FKs.

Revision ID: 030
Revises: 029
Create Date: 2026-04-07

Cortex review fixes:
- M2: add `pm_strategies.paper_mode_since` (UTC) for promotion gate soak window.
- M3: change `pm_promotion_audit.pm_strategy_id` FK CASCADE -> RESTRICT and
  install a Postgres trigger that raises on UPDATE/DELETE so audit rows are
  immutable at the database layer.
- M4: change `pm_orders.pm_market_id` and `pm_orders.pm_strategy_id` FKs
  CASCADE -> RESTRICT.
"""
from __future__ import annotations
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, col: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"),
        {"t": table, "c": col},
    ).first())


def _fk_name(table: str, column: str) -> str | None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT tc.constraint_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "WHERE tc.constraint_type='FOREIGN KEY' "
            "  AND tc.table_name=:t AND kcu.column_name=:c"
        ),
        {"t": table, "c": column},
    ).first()
    return row[0] if row else None


def upgrade() -> None:
    # --- M2: paper_mode_since ----------------------------------------------
    if not _has_column("pm_strategies", "paper_mode_since"):
        op.add_column(
            "pm_strategies",
            sa.Column(
                "paper_mode_since",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
        )

    # --- M3 + M4: re-create FKs as RESTRICT --------------------------------
    for table, col, ref_table in (
        ("pm_promotion_audit", "pm_strategy_id", "pm_strategies"),
        ("pm_orders", "pm_strategy_id", "pm_strategies"),
        ("pm_orders", "pm_market_id", "pm_markets"),
    ):
        existing = _fk_name(table, col)
        if existing:
            op.drop_constraint(existing, table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_{col}_restrict",
            table,
            ref_table,
            [col],
            ["id"],
            ondelete="RESTRICT",
        )

    # --- M3: immutable audit trigger ---------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION pm_promotion_audit_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'pm_promotion_audit rows are immutable (op=%)', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS pm_promotion_audit_no_update ON pm_promotion_audit;")
    op.execute(
        """
        CREATE TRIGGER pm_promotion_audit_no_update
        BEFORE UPDATE OR DELETE ON pm_promotion_audit
        FOR EACH ROW EXECUTE FUNCTION pm_promotion_audit_immutable();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS pm_promotion_audit_no_update ON pm_promotion_audit;")
    op.execute("DROP FUNCTION IF EXISTS pm_promotion_audit_immutable();")

    for table, col, ref_table in (
        ("pm_promotion_audit", "pm_strategy_id", "pm_strategies"),
        ("pm_orders", "pm_strategy_id", "pm_strategies"),
        ("pm_orders", "pm_market_id", "pm_markets"),
    ):
        existing = _fk_name(table, col)
        if existing:
            op.drop_constraint(existing, table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_{col}_cascade",
            table,
            ref_table,
            [col],
            ["id"],
            ondelete="CASCADE",
        )

    if _has_column("pm_strategies", "paper_mode_since"):
        op.drop_column("pm_strategies", "paper_mode_since")
