"""sync_agent_model_schema

Revision ID: 09b0dd176f5d
Revises: 032
Create Date: 2026-04-07 13:20:57.634183

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '09b0dd176f5d'
down_revision: Union[str, None] = '032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    from sqlalchemy import inspect, text
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": column})
    return result.scalar() is not None


def upgrade() -> None:
    # --- agents: add missing columns (idempotent) ---
    if not _has_column('agents', 'phoenix_api_key'):
        op.add_column('agents', sa.Column('phoenix_api_key', sa.String(200), nullable=True))
    if not _has_column('agents', 'worker_container_id'):
        op.add_column('agents', sa.Column('worker_container_id', sa.String(100), nullable=True))
    if not _has_column('agents', 'worker_status'):
        op.add_column('agents', sa.Column('worker_status', sa.String(30), nullable=False, server_default='STOPPED'))
    if not _has_column('agents', 'source'):
        op.add_column('agents', sa.Column('source', sa.String(50), nullable=False, server_default='manual'))
    if not _has_column('agents', 'channel_name'):
        op.add_column('agents', sa.Column('channel_name', sa.String(100), nullable=True))
    if not _has_column('agents', 'analyst_name'):
        op.add_column('agents', sa.Column('analyst_name', sa.String(100), nullable=True))
    if not _has_column('agents', 'model_type'):
        op.add_column('agents', sa.Column('model_type', sa.String(50), nullable=True))
    if not _has_column('agents', 'model_accuracy'):
        op.add_column('agents', sa.Column('model_accuracy', sa.Float(), nullable=True))
    if not _has_column('agents', 'daily_pnl'):
        op.add_column('agents', sa.Column('daily_pnl', sa.Float(), nullable=False, server_default='0'))
    if not _has_column('agents', 'total_pnl'):
        op.add_column('agents', sa.Column('total_pnl', sa.Float(), nullable=False, server_default='0'))
    if not _has_column('agents', 'total_trades'):
        op.add_column('agents', sa.Column('total_trades', sa.Integer(), nullable=False, server_default='0'))
    if not _has_column('agents', 'win_rate'):
        op.add_column('agents', sa.Column('win_rate', sa.Float(), nullable=False, server_default='0'))
    if not _has_column('agents', 'last_signal_at'):
        op.add_column('agents', sa.Column('last_signal_at', sa.DateTime(timezone=True), nullable=True))
    if not _has_column('agents', 'last_trade_at'):
        op.add_column('agents', sa.Column('last_trade_at', sa.DateTime(timezone=True), nullable=True))
    if not _has_column('agents', 'manifest'):
        op.add_column('agents', sa.Column('manifest', postgresql.JSONB(), nullable=False, server_default='{}'))
    if not _has_column('agents', 'current_mode'):
        op.add_column('agents', sa.Column('current_mode', sa.String(30), nullable=False, server_default='conservative'))
    if not _has_column('agents', 'rules_version'):
        op.add_column('agents', sa.Column('rules_version', sa.Integer(), nullable=False, server_default='1'))
    if not _has_column('agents', 'pending_improvements'):
        op.add_column('agents', sa.Column('pending_improvements', postgresql.JSONB(), nullable=False, server_default='{}'))
    if not _has_column('agents', 'last_research_at'):
        op.add_column('agents', sa.Column('last_research_at', sa.DateTime(timezone=True), nullable=True))

    # NOTE: instance_id intentionally kept — still referenced by routes/services

    # --- agent_backtests: add missing columns (idempotent) ---
    if not _has_column('agent_backtests', 'current_step'):
        op.add_column('agent_backtests', sa.Column('current_step', sa.String(100), nullable=True))
    if not _has_column('agent_backtests', 'progress_pct'):
        op.add_column('agent_backtests', sa.Column('progress_pct', sa.Integer(), nullable=False, server_default='0'))
    if not _has_column('agent_backtests', 'model_selection'):
        op.add_column('agent_backtests', sa.Column('model_selection', postgresql.JSONB(), nullable=False, server_default='{}'))
    if not _has_column('agent_backtests', 'backtesting_version'):
        op.add_column('agent_backtests', sa.Column('backtesting_version', sa.Integer(), nullable=False, server_default='1'))

    # --- index cleanup (trade_signals) ---
    from sqlalchemy import text
    conn = op.get_bind()
    def _has_index(idx: str) -> bool:
        r = conn.execute(text("SELECT 1 FROM pg_indexes WHERE indexname=:i"), {"i": idx})
        return r.scalar() is not None

    for old_idx in ['idx_trade_signals_agent', 'idx_trade_signals_created',
                    'idx_trade_signals_decision', 'idx_trade_signals_missed',
                    'idx_trade_signals_ticker']:
        if _has_index(old_idx):
            op.drop_index(old_idx, table_name='trade_signals')

    if not _has_index('ix_trade_signals_agent_id'):
        op.create_index('ix_trade_signals_agent_id', 'trade_signals', ['agent_id'])
    if not _has_index('ix_trade_signals_created_at'):
        op.create_index('ix_trade_signals_created_at', 'trade_signals', ['created_at'])
    if not _has_index('ix_trade_signals_decision'):
        op.create_index('ix_trade_signals_decision', 'trade_signals', ['decision'])
    if not _has_index('ix_trade_signals_ticker'):
        op.create_index('ix_trade_signals_ticker', 'trade_signals', ['ticker'])


def downgrade() -> None:
    for col in ['last_research_at', 'pending_improvements', 'rules_version', 'current_mode',
                'manifest', 'last_trade_at', 'last_signal_at', 'win_rate', 'total_trades',
                'total_pnl', 'daily_pnl', 'model_accuracy', 'model_type', 'analyst_name',
                'channel_name', 'source', 'worker_status', 'worker_container_id', 'phoenix_api_key']:
        if _has_column('agents', col):
            op.drop_column('agents', col)

    for col in ['backtesting_version', 'model_selection', 'progress_pct', 'current_step']:
        if _has_column('agent_backtests', col):
            op.drop_column('agent_backtests', col)
