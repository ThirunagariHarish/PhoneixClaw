"""Unit tests for Phase 1 backend fixes in agent_gateway.py.

Requires Python 3.11+ (project runtime).  Run with:
    python3.13 -m pytest tests/unit/test_agent_gateway_error_path.py -v --tb=short

Tests covered:
  1.1  _mark_backtest_failed  — agent.status = "ERROR" and agent.error_message is set
  1.1  _mark_backtest_completed — agent.error_message cleared to None on retry success
  1.2  AgentResponse.error_message field present and mapped from model
  1.3  _prepare_analyst_directory — connector_id in config.json
  1.3  _prepare_analyst_directory — paper agent has NO robinhood_credentials in config.json
  1.4  create_analyst — PAPER agent status stays "PAPER"; live becomes "RUNNING"
  1.4  create_analyst — AgentSession.trading_mode = "paper" for PAPER agent
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper factories — lightweight stand-ins for ORM objects
# ---------------------------------------------------------------------------

def _make_agent(status: str = "BACKTESTING", *, config: dict | None = None) -> MagicMock:
    a = MagicMock()
    a.id = uuid.uuid4()
    a.name = "TestAgent"
    a.status = status
    a.error_message = None
    a.worker_status = "STOPPED"
    a.updated_at = datetime.now(timezone.utc)
    a.config = config if config is not None else {}
    a.manifest = {}
    a.channel_name = "test-channel"
    a.analyst_name = "TestAnalyst"
    a.current_mode = "conservative"
    a.phoenix_api_key = ""
    return a


def _make_backtest(status: str = "RUNNING") -> MagicMock:
    bt = MagicMock()
    bt.id = uuid.uuid4()
    bt.status = status
    bt.error_message = None
    bt.metrics = {}
    bt.completed_at = None
    bt.total_trades = 0
    bt.win_rate = None
    bt.sharpe_ratio = None
    bt.max_drawdown = None
    bt.total_return = None
    bt.progress_pct = 0
    bt.current_step = "running"
    return bt


def _make_async_db(
    agent: MagicMock, backtest: MagicMock | None = None
) -> AsyncMock:
    """Build an async DB session mock.

    execute() rotates through backtest then agent on successive calls,
    which mirrors the two-query pattern in _mark_backtest_* functions.
    """
    call_count = {"n": 0}

    async def _execute(stmt):
        result = MagicMock()
        call_count["n"] += 1
        if call_count["n"] == 1:
            result.scalar_one_or_none.return_value = backtest
        else:
            result.scalar_one_or_none.return_value = agent
        return result

    db = AsyncMock()
    db.execute.side_effect = _execute
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


async def _async_db_gen(db: AsyncMock):
    """Minimal async generator that mimics _get_session()."""
    yield db


# ---------------------------------------------------------------------------
# 1.1  _mark_backtest_failed
# ---------------------------------------------------------------------------

class TestMarkBacktestFailed:

    async def test_mark_backtest_failed_sets_error_status(self):
        from apps.api.src.services.agent_gateway import _mark_backtest_failed

        agent = _make_agent(status="BACKTESTING")
        bt = _make_backtest()
        db = _make_async_db(agent, bt)

        error_msg = "Claude SDK unavailable: ANTHROPIC_API_KEY not set"
        await _mark_backtest_failed(db, agent.id, bt.id, step="preflight", error_msg=error_msg)

        assert agent.status == "ERROR", f"Expected ERROR, got {agent.status!r}"

    async def test_mark_backtest_failed_writes_error_message(self):
        from apps.api.src.services.agent_gateway import _mark_backtest_failed

        agent = _make_agent(status="BACKTESTING")
        bt = _make_backtest()
        db = _make_async_db(agent, bt)

        error_msg = "Claude SDK unavailable: ANTHROPIC_API_KEY not set"
        await _mark_backtest_failed(db, agent.id, bt.id, step="preflight", error_msg=error_msg)

        assert agent.error_message == error_msg

    async def test_mark_backtest_failed_sets_backtest_status_failed(self):
        from apps.api.src.services.agent_gateway import _mark_backtest_failed

        agent = _make_agent(status="BACKTESTING")
        bt = _make_backtest()
        db = _make_async_db(agent, bt)

        await _mark_backtest_failed(db, agent.id, bt.id, step="preflight", error_msg="boom")

        assert bt.status == "FAILED"

    async def test_mark_backtest_failed_commits(self):
        from apps.api.src.services.agent_gateway import _mark_backtest_failed

        agent = _make_agent()
        bt = _make_backtest()
        db = _make_async_db(agent, bt)

        await _mark_backtest_failed(db, agent.id, bt.id, step="preflight", error_msg="err")

        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 1.1  _mark_backtest_completed
# ---------------------------------------------------------------------------

class TestMarkBacktestCompleted:

    async def test_mark_backtest_completed_clears_error(self):
        from apps.api.src.services.agent_gateway import _mark_backtest_completed

        agent = _make_agent(status="BACKTESTING")
        agent.error_message = "previous error"
        bt = _make_backtest(status="RUNNING")
        db = _make_async_db(agent, bt)

        await _mark_backtest_completed(db, agent.id, bt.id)

        assert agent.error_message is None, f"Expected None, got {agent.error_message!r}"

    async def test_mark_backtest_completed_sets_backtest_complete_status(self):
        from apps.api.src.services.agent_gateway import _mark_backtest_completed

        agent = _make_agent()
        bt = _make_backtest()
        db = _make_async_db(agent, bt)

        await _mark_backtest_completed(db, agent.id, bt.id)

        assert agent.status == "BACKTEST_COMPLETE"
        assert bt.status == "COMPLETED"


# ---------------------------------------------------------------------------
# 1.3  _prepare_analyst_directory
# ---------------------------------------------------------------------------

class TestPrepareAnalystDirectory:

    async def test_prepare_analyst_dir_includes_connector_id(self, tmp_path: Path):
        import apps.api.src.services.agent_gateway as gw

        connector_uuid = str(uuid.uuid4())
        agent = _make_agent(
            status="BACKTEST_COMPLETE",
            config={"connector_ids": [connector_uuid]},
        )
        db = _make_async_db(agent)
        gateway = gw.AgentGateway()

        with (
            patch.object(gw, "DATA_DIR", tmp_path),
            patch.object(gw, "LIVE_TEMPLATE", tmp_path / "template"),
            patch("shutil.rmtree", MagicMock()),
            patch("shutil.copytree", MagicMock()),
            patch("shutil.copy2", MagicMock()),
        ):
            (tmp_path / "template").mkdir()
            gateway._render_claude_md = MagicMock()
            work_dir = await gateway._prepare_analyst_directory(agent, db)

        cfg = json.loads((work_dir / "config.json").read_text())
        assert "connector_id" in cfg, f"config.json missing 'connector_id'; keys={list(cfg)}"
        assert cfg["connector_id"] == connector_uuid

    async def test_prepare_analyst_dir_empty_connector_ids_uses_empty_string(self, tmp_path: Path):
        import apps.api.src.services.agent_gateway as gw

        agent = _make_agent(status="BACKTEST_COMPLETE", config={})
        db = _make_async_db(agent)
        gateway = gw.AgentGateway()

        with (
            patch.object(gw, "DATA_DIR", tmp_path),
            patch.object(gw, "LIVE_TEMPLATE", tmp_path / "template"),
            patch("shutil.rmtree", MagicMock()),
            patch("shutil.copytree", MagicMock()),
            patch("shutil.copy2", MagicMock()),
        ):
            (tmp_path / "template").mkdir()
            gateway._render_claude_md = MagicMock()
            work_dir = await gateway._prepare_analyst_directory(agent, db)

        cfg = json.loads((work_dir / "config.json").read_text())
        assert cfg["connector_id"] == "", f"Expected empty string, got {cfg['connector_id']!r}"

    async def test_prepare_analyst_dir_paper_mode_no_robinhood(self, tmp_path: Path):
        """PAPER agent must NOT receive robinhood_credentials in config.json (AC2.5.1)."""
        import apps.api.src.services.agent_gateway as gw

        connector_uuid = str(uuid.uuid4())
        rh_creds = {"username": "trader@example.com", "password": "secret", "mfa_code": "123456"}
        agent = _make_agent(
            status="PAPER",
            config={"connector_ids": [connector_uuid], "robinhood_credentials": rh_creds},
        )
        db = _make_async_db(agent)
        gateway = gw.AgentGateway()

        with (
            patch.object(gw, "DATA_DIR", tmp_path),
            patch.object(gw, "LIVE_TEMPLATE", tmp_path / "template"),
            patch("shutil.rmtree", MagicMock()),
            patch("shutil.copytree", MagicMock()),
            patch("shutil.copy2", MagicMock()),
        ):
            (tmp_path / "template").mkdir()
            gateway._render_claude_md = MagicMock()
            work_dir = await gateway._prepare_analyst_directory(agent, db)

        cfg = json.loads((work_dir / "config.json").read_text())
        assert "robinhood_credentials" not in cfg, "Paper agent MUST NOT receive robinhood_credentials"
        assert "robinhood" not in cfg, "Paper agent MUST NOT receive 'robinhood' key"
        assert cfg.get("paper_mode") is True

    async def test_prepare_analyst_dir_live_agent_receives_robinhood(self, tmp_path: Path):
        """Live agent with valid credentials must receive robinhood_credentials."""
        import apps.api.src.services.agent_gateway as gw

        rh_creds = {"username": "trader@example.com", "password": "hunter2", "mfa_code": "000000"}
        agent = _make_agent(
            status="BACKTEST_COMPLETE",
            config={"robinhood_credentials": rh_creds},
        )
        db = _make_async_db(agent)
        gateway = gw.AgentGateway()

        with (
            patch.object(gw, "DATA_DIR", tmp_path),
            patch.object(gw, "LIVE_TEMPLATE", tmp_path / "template"),
            patch("shutil.rmtree", MagicMock()),
            patch("shutil.copytree", MagicMock()),
            patch("shutil.copy2", MagicMock()),
        ):
            (tmp_path / "template").mkdir()
            gateway._render_claude_md = MagicMock()
            work_dir = await gateway._prepare_analyst_directory(agent, db)

        cfg = json.loads((work_dir / "config.json").read_text())
        assert "robinhood_credentials" in cfg, "Live agent should receive robinhood_credentials"
        assert cfg.get("paper_mode") is False


# ---------------------------------------------------------------------------
# 1.4  create_analyst — paper status preservation + trading_mode column
# ---------------------------------------------------------------------------

class TestCreateAnalystPaperStatus:

    async def _run_create_analyst(self, agent: MagicMock, tmp_path: Path) -> list:
        """Run create_analyst with all external calls stubbed out.

        Returns the list of objects passed to db.add().
        """
        import apps.api.src.services.agent_gateway as gw

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=agent)
        ))
        added: list = []
        db.add = MagicMock(side_effect=added.append)
        db.commit = AsyncMock()

        gateway = gw.AgentGateway()

        # Stub budget check (always OK)
        import sys, types as _types
        budget_stub = _types.ModuleType("apps.api.src.services.budget_enforcer")
        budget_stub.check_budget = AsyncMock(return_value={"ok": True})
        sys.modules["apps.api.src.services.budget_enforcer"] = budget_stub

        with (
            patch.object(gw, "_get_session", return_value=_async_db_gen(db)),
            patch.object(gateway, "_prepare_analyst_directory", AsyncMock(return_value=tmp_path)),
            patch.object(gateway, "_run_analyst", AsyncMock()),
            patch("asyncio.create_task", return_value=MagicMock()),
        ):
            await gateway.create_analyst(agent.id)

        return added

    async def test_create_analyst_preserves_paper_status(self, tmp_path: Path):
        agent = _make_agent(status="PAPER")
        await self._run_create_analyst(agent, tmp_path)

        assert agent.status == "PAPER", f"Expected PAPER, got {agent.status!r}"
        assert agent.worker_status == "STARTING"

    async def test_create_analyst_live_agent_becomes_running(self, tmp_path: Path):
        agent = _make_agent(status="BACKTEST_COMPLETE")
        await self._run_create_analyst(agent, tmp_path)

        assert agent.status == "RUNNING", f"Expected RUNNING, got {agent.status!r}"

    async def test_create_analyst_paper_session_has_trading_mode_paper(self, tmp_path: Path):
        from shared.db.models.agent_session import AgentSession

        agent = _make_agent(status="PAPER")
        added = await self._run_create_analyst(agent, tmp_path)

        sessions = [o for o in added if isinstance(o, AgentSession)]
        assert sessions, "No AgentSession was added"
        assert sessions[0].trading_mode == "paper", f"Expected 'paper', got {sessions[0].trading_mode!r}"

    async def test_create_analyst_live_session_has_trading_mode_live(self, tmp_path: Path):
        from shared.db.models.agent_session import AgentSession

        agent = _make_agent(status="BACKTEST_COMPLETE")
        added = await self._run_create_analyst(agent, tmp_path)

        sessions = [o for o in added if isinstance(o, AgentSession)]
        assert sessions, "No AgentSession was added"
        assert sessions[0].trading_mode == "live", f"Expected 'live', got {sessions[0].trading_mode!r}"


# ---------------------------------------------------------------------------
# 1.2  AgentResponse — error_message field
# ---------------------------------------------------------------------------

class TestAgentResponseErrorMessage:

    def _make_full_agent_mock(
        self, status: str = "ERROR", error_message: str | None = None
    ) -> MagicMock:
        a = MagicMock()
        a.id = uuid.uuid4()
        a.name = "TestAgent"
        a.type = "trading"
        a.status = status
        a.worker_status = "ERROR"
        a.last_activity_at = None
        a.config = {}
        a.channel_name = None
        a.analyst_name = None
        a.model_type = None
        a.model_accuracy = None
        a.daily_pnl = 0.0
        a.total_pnl = 0.0
        a.total_trades = 0
        a.win_rate = 0.0
        a.current_mode = "conservative"
        a.rules_version = 1
        a.last_signal_at = None
        a.last_trade_at = None
        a.created_at = datetime.now(timezone.utc)
        a.error_message = error_message
        return a

    def test_error_message_populated_when_error_status(self):
        from apps.api.src.routes.agents import AgentResponse

        agent = self._make_full_agent_mock(status="ERROR", error_message="Claude SDK unavailable")
        resp = AgentResponse.from_model(agent)

        assert resp.error_message == "Claude SDK unavailable"
        assert resp.status == "ERROR"

    def test_error_message_is_none_when_running(self):
        from apps.api.src.routes.agents import AgentResponse

        agent = self._make_full_agent_mock(status="RUNNING", error_message=None)
        resp = AgentResponse.from_model(agent)

        assert resp.error_message is None

    def test_error_message_field_declared_on_agent_response(self):
        from apps.api.src.routes.agents import AgentResponse

        assert "error_message" in AgentResponse.model_fields, (
            "AgentResponse must declare error_message as a Pydantic field"
        )
