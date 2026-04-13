"""Add feature_store_features, model_bundles, and predictions tables.

These three tables form the ML platform foundation:
- feature_store_features: pre-computed features for training/serving parity
- model_bundles: versioned model artifacts tracked in MinIO
- predictions: every inference logged for accuracy monitoring and drift detection

Revision ID: 044_ml_platform_tables
Revises: 043_channel_messages
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "044_ml_platform_tables"
down_revision = "043_channel_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_store_features",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("feature_group", sa.String(50), nullable=False),
        sa.Column("features", JSONB, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_fs_ticker_group_time",
        "feature_store_features",
        ["ticker", "feature_group", sa.text("computed_at DESC")],
    )

    op.create_table(
        "model_bundles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("minio_path", sa.Text, nullable=False),
        sa.Column("primary_model", sa.String(50), nullable=True),
        sa.Column("accuracy", sa.Float, nullable=True),
        sa.Column("auc_roc", sa.Float, nullable=True),
        sa.Column("sharpe_ratio", sa.Float, nullable=True),
        sa.Column("training_trades", sa.Integer, nullable=True),
        sa.Column("feature_count", sa.Integer, nullable=True),
        sa.Column("feature_schema", JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("validation_passed", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_model_bundles_agent_id", "model_bundles", ["agent_id"])
    op.create_index(
        "uq_model_bundle_agent_version",
        "model_bundles",
        ["agent_id", "version"],
        unique=True,
    )

    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=False),
        sa.Column("model_bundle_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("signal_content", sa.Text, nullable=True),
        sa.Column("features_snapshot", JSONB, nullable=True),
        sa.Column("prediction", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("reasoning", sa.Text, nullable=True),
        sa.Column("predicted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("actual_outcome", sa.String(20), nullable=True),
        sa.Column("actual_pnl", sa.Float, nullable=True),
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pred_agent_time", "predictions", ["agent_id", sa.text("predicted_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_pred_agent_time", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("uq_model_bundle_agent_version", table_name="model_bundles")
    op.drop_index("ix_model_bundles_agent_id", table_name="model_bundles")
    op.drop_table("model_bundles")
    op.drop_index("ix_fs_ticker_group_time", table_name="feature_store_features")
    op.drop_table("feature_store_features")
