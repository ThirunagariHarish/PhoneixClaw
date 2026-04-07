"""Unit tests for Alembic migration 032 (agents_tab_fix).

Tests run entirely in process — no live database required.  We patch
``alembic.op`` and the internal ``_has_column`` helper so that each
test controls the initial schema state, then verifies the correct DDL
operations are (or are not) issued.

We also verify that the two new ORM columns are accessible as Python
attributes on the model classes, because that is the contract Phase 1
code will rely on at import time.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_migration():
    """Import (or reload) the migration module freshly each test."""
    mod_path = "shared.db.migrations.versions.032_agents_tab_fix"
    if mod_path in sys.modules:
        return importlib.reload(sys.modules[mod_path])
    return importlib.import_module(mod_path)


# ---------------------------------------------------------------------------
# Migration structural sanity
# ---------------------------------------------------------------------------

class TestMigrationMetadata:
    def test_revision_is_032(self):
        m = _load_migration()
        assert m.revision == "032"

    def test_down_revision_is_031(self):
        m = _load_migration()
        assert m.down_revision == "031"

    def test_branch_labels_none(self):
        m = _load_migration()
        assert m.branch_labels is None

    def test_depends_on_none(self):
        m = _load_migration()
        assert m.depends_on is None


# ---------------------------------------------------------------------------
# upgrade() — adds both columns when they are absent
# ---------------------------------------------------------------------------

class TestUpgrade:
    def _run_upgrade(self, *, has_error_message: bool, has_trading_mode: bool):
        """Patch _has_column + op and invoke upgrade()."""
        m = _load_migration()

        def fake_has_column(table: str, col: str) -> bool:
            return (table == "agents" and col == "error_message" and has_error_message) or (
                table == "agent_sessions" and col == "trading_mode" and has_trading_mode
            )

        mock_op = MagicMock()
        with (
            patch.object(m, "_has_column", side_effect=fake_has_column),
            patch.object(m, "op", mock_op),
        ):
            m.upgrade()
        return mock_op

    def test_upgrade_adds_error_message_column(self):
        mock_op = self._run_upgrade(has_error_message=False, has_trading_mode=True)
        add_calls = mock_op.add_column.call_args_list
        assert len(add_calls) == 1
        table_arg = add_calls[0].args[0]
        assert table_arg == "agents"

    def test_upgrade_adds_trading_mode_column(self):
        mock_op = self._run_upgrade(has_error_message=True, has_trading_mode=False)
        add_calls = mock_op.add_column.call_args_list
        assert len(add_calls) == 1
        table_arg = add_calls[0].args[0]
        assert table_arg == "agent_sessions"

    def test_upgrade_adds_both_columns_when_both_absent(self):
        mock_op = self._run_upgrade(has_error_message=False, has_trading_mode=False)
        tables = [c.args[0] for c in mock_op.add_column.call_args_list]
        assert "agents" in tables
        assert "agent_sessions" in tables
        assert mock_op.add_column.call_count == 2

    def test_upgrade_is_idempotent(self):
        """Running upgrade() when both columns already exist must not call add_column."""
        mock_op = self._run_upgrade(has_error_message=True, has_trading_mode=True)
        assert mock_op.add_column.call_count == 0


# ---------------------------------------------------------------------------
# downgrade() — drops both columns when they exist
# ---------------------------------------------------------------------------

class TestDowngrade:
    def _run_downgrade(self, *, has_error_message: bool, has_trading_mode: bool):
        m = _load_migration()

        def fake_has_column(table: str, col: str) -> bool:
            return (table == "agents" and col == "error_message" and has_error_message) or (
                table == "agent_sessions" and col == "trading_mode" and has_trading_mode
            )

        mock_op = MagicMock()
        with (
            patch.object(m, "_has_column", side_effect=fake_has_column),
            patch.object(m, "op", mock_op),
        ):
            m.downgrade()
        return mock_op

    def test_downgrade_removes_columns(self):
        mock_op = self._run_downgrade(has_error_message=True, has_trading_mode=True)
        drop_calls = mock_op.drop_column.call_args_list
        tables = [c.args[0] for c in drop_calls]
        assert "agents" in tables
        assert "agent_sessions" in tables
        assert mock_op.drop_column.call_count == 2

    def test_downgrade_skips_absent_columns(self):
        """If columns were never created, downgrade must not call drop_column."""
        mock_op = self._run_downgrade(has_error_message=False, has_trading_mode=False)
        assert mock_op.drop_column.call_count == 0

    def test_downgrade_drops_trading_mode_before_error_message(self):
        """Downgrade must drop agent_sessions.trading_mode first (FK-safe order)."""
        mock_op = self._run_downgrade(has_error_message=True, has_trading_mode=True)
        tables = [c.args[0] for c in mock_op.drop_column.call_args_list]
        assert tables.index("agent_sessions") < tables.index("agents")


# ---------------------------------------------------------------------------
# ORM model attribute checks
# ---------------------------------------------------------------------------

class TestAgentModelColumn:
    def test_error_message_attribute_exists(self):
        from shared.db.models.agent import Agent
        assert hasattr(Agent, "error_message"), "Agent.error_message attribute is missing"

    def test_error_message_in_table_columns(self):
        from shared.db.models.agent import Agent
        col_names = {c.name for c in Agent.__table__.columns}
        assert "error_message" in col_names

    def test_error_message_is_nullable(self):
        from shared.db.models.agent import Agent
        col = Agent.__table__.columns["error_message"]
        assert col.nullable is True

    def test_error_message_is_text_type(self):
        from sqlalchemy import Text

        from shared.db.models.agent import Agent
        col = Agent.__table__.columns["error_message"]
        assert isinstance(col.type, Text)


class TestAgentSessionModelColumn:
    def test_trading_mode_attribute_exists(self):
        from shared.db.models.agent_session import AgentSession
        assert hasattr(AgentSession, "trading_mode"), "AgentSession.trading_mode attribute is missing"

    def test_trading_mode_in_table_columns(self):
        from shared.db.models.agent_session import AgentSession
        col_names = {c.name for c in AgentSession.__table__.columns}
        assert "trading_mode" in col_names

    def test_trading_mode_is_not_nullable(self):
        from shared.db.models.agent_session import AgentSession
        col = AgentSession.__table__.columns["trading_mode"]
        assert col.nullable is False

    def test_trading_mode_default_is_live(self):
        from shared.db.models.agent_session import AgentSession
        col = AgentSession.__table__.columns["trading_mode"]
        # ORM-level default (used when Python creates the object)
        assert col.default is not None
        assert col.default.arg == "live"

    def test_trading_mode_is_string_type(self):
        from sqlalchemy import String

        from shared.db.models.agent_session import AgentSession
        col = AgentSession.__table__.columns["trading_mode"]
        assert isinstance(col.type, String)
        assert col.type.length == 20


# ---------------------------------------------------------------------------
# Instantiation sanity — new fields don't break existing constructor calls
# ---------------------------------------------------------------------------

class TestModelInstantiationBackcompat:
    def test_agent_can_be_created_without_error_message(self):
        from shared.db.models.agent import Agent
        a = Agent(name="test-agent", type="trading")
        # error_message defaults to None at ORM level
        assert a.error_message is None

    def test_agent_session_can_be_created_without_trading_mode(self):
        import uuid

        from shared.db.models.agent_session import AgentSession
        s = AgentSession(agent_id=uuid.uuid4())
        # SQLAlchemy 2 applies column defaults at INSERT time, not Python construction
        # time.  The attribute is reachable (no AttributeError) and is either the
        # default value or None before the session flushes.
        assert s.trading_mode is None or s.trading_mode == "live"

    def test_agent_session_trading_mode_can_be_paper(self):
        import uuid

        from shared.db.models.agent_session import AgentSession
        s = AgentSession(agent_id=uuid.uuid4(), trading_mode="paper")
        assert s.trading_mode == "paper"
