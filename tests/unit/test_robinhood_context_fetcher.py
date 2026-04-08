"""Unit tests for RobinhoodContextFetcher and chat_responder live-portfolio injection.

Run with:
    PYTHONPATH=. pytest tests/unit/test_robinhood_context_fetcher.py -v
"""
from __future__ import annotations

import json
import sys
import types
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _live_creds() -> dict:
    return {"username": "trader@example.com", "password": "s3cr3t", "totp_secret": ""}


def _make_mock_session_with_agent(status: str, config: dict):
    """Return (mock_session, agent_row) whose execute() returns agent_row."""
    agent_row = MagicMock()
    agent_row.id = uuid.uuid4()
    agent_row.status = status
    agent_row.config = config

    result = MagicMock()
    result.scalar_one_or_none.return_value = agent_row

    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session, agent_row


def _make_session_no_agent():
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


@contextmanager
def _patch_db_for_fetcher():
    """
    Patch both the Agent import and sqlalchemy.select inside the fetcher so that:
    - ``from shared.db.models.agent import Agent`` returns a MagicMock class
    - ``select(Agent)`` doesn't raise SQLAlchemy validation errors in Python 3.9
    """
    mock_module = types.ModuleType("shared.db.models.agent")
    mock_agent_cls = MagicMock()
    mock_module.Agent = mock_agent_cls  # type: ignore[attr-defined]

    mock_select = MagicMock()
    mock_select.return_value.where.return_value = MagicMock()

    with (
        patch.dict(sys.modules, {"shared.db.models.agent": mock_module}),
        patch("apps.api.src.services.robinhood_context_fetcher.select", mock_select),
    ):
        yield mock_agent_cls


def _rh_mock(mock_rh: MagicMock) -> dict:
    """
    Return a sys.modules patch dict where ``import robin_stocks.robinhood as rh``
    resolves to *mock_rh*.

    Python's import machinery checks sys.modules["robin_stocks.robinhood"] but
    then returns the *attribute* from the parent package mock when it does
    ``import robin_stocks.robinhood``. Setting ``parent.robinhood = mock_rh``
    ensures the same object is returned via both paths.
    """
    mock_pkg = MagicMock()
    mock_pkg.robinhood = mock_rh
    return {"robin_stocks": mock_pkg, "robin_stocks.robinhood": mock_rh}


# ---------------------------------------------------------------------------
# RobinhoodContextFetcher — non-live / no-credentials tests
# ---------------------------------------------------------------------------


class TestRobinhoodContextFetcherNonLive:
    """Agents that should NOT trigger a Robinhood fetch."""

    @pytest.mark.parametrize(
        "status",
        ["PAPER", "CREATED", "BACKTEST_COMPLETE", "PAUSED", "PENDING"],
    )
    async def test_returns_empty_for_non_live_status(self, status: str) -> None:
        from apps.api.src.services.robinhood_context_fetcher import RobinhoodContextFetcher

        session, _ = _make_mock_session_with_agent(
            status=status, config={"robinhood_credentials": _live_creds()}
        )
        with _patch_db_for_fetcher():
            ctx = await RobinhoodContextFetcher(session).fetch(uuid.uuid4())

        assert ctx.positions == []
        assert ctx.account_value is None
        assert ctx.error is None  # empty is NOT an error

    async def test_returns_empty_when_no_credentials(self) -> None:
        from apps.api.src.services.robinhood_context_fetcher import RobinhoodContextFetcher

        session, _ = _make_mock_session_with_agent(status="RUNNING", config={})
        with _patch_db_for_fetcher():
            ctx = await RobinhoodContextFetcher(session).fetch(uuid.uuid4())

        assert ctx.is_empty()
        assert ctx.error is None

    async def test_returns_empty_when_credentials_missing_password(self) -> None:
        from apps.api.src.services.robinhood_context_fetcher import RobinhoodContextFetcher

        session, _ = _make_mock_session_with_agent(
            status="RUNNING",
            config={"robinhood_credentials": {"username": "u@example.com", "password": ""}},
        )
        with _patch_db_for_fetcher():
            ctx = await RobinhoodContextFetcher(session).fetch(uuid.uuid4())

        assert ctx.is_empty()
        assert ctx.error is None

    async def test_returns_empty_when_agent_not_found(self) -> None:
        from apps.api.src.services.robinhood_context_fetcher import RobinhoodContextFetcher

        session = _make_session_no_agent()
        with _patch_db_for_fetcher():
            ctx = await RobinhoodContextFetcher(session).fetch(uuid.uuid4())

        assert ctx.is_empty()
        assert ctx.error is None


# ---------------------------------------------------------------------------
# RobinhoodContextFetcher — graceful fallback (test _fetch_sync directly)
# ---------------------------------------------------------------------------


class TestRobinhoodContextFetcherGracefulFallback:
    """Error handling when robin_stocks raises — _fetch_sync tested directly."""

    def test_graceful_fallback_on_login_error(self) -> None:
        """robin_stocks login raises -> error field set, no crash."""
        from apps.api.src.services.robinhood_context_fetcher import RobinhoodContextFetcher

        fetcher = RobinhoodContextFetcher(AsyncMock())

        mock_rh = MagicMock()
        mock_rh.login.side_effect = RuntimeError("invalid credentials")
        mock_rh.authentication.logout.return_value = None

        with patch.dict(sys.modules, _rh_mock(mock_rh)):
            ctx = fetcher._fetch_sync({"username": "u", "password": "p", "totp_secret": ""})

        assert ctx.positions == []
        assert ctx.error is not None
        assert "invalid credentials" in ctx.error
        assert ctx.last_updated_at  # timestamp always set

    def test_graceful_fallback_on_positions_error(self) -> None:
        """Login succeeds, get_open_stock_positions raises -> error set."""
        from apps.api.src.services.robinhood_context_fetcher import RobinhoodContextFetcher

        fetcher = RobinhoodContextFetcher(AsyncMock())

        mock_rh = MagicMock()
        mock_rh.login.return_value = {"access_token": "tok"}
        mock_rh.account.get_open_stock_positions.side_effect = ConnectionError("network err")
        mock_rh.authentication.logout.return_value = None

        with patch.dict(sys.modules, _rh_mock(mock_rh)):
            ctx = fetcher._fetch_sync({"username": "u", "password": "p", "totp_secret": ""})

        assert "network err" in (ctx.error or "")

    def test_graceful_fallback_when_robin_stocks_not_installed(self) -> None:
        """ImportError -> error field set, no crash, no ImportError propagated."""
        from apps.api.src.services.robinhood_context_fetcher import RobinhoodContextFetcher

        fetcher = RobinhoodContextFetcher(AsyncMock())

        # Hide both keys so the import inside _fetch_sync raises ImportError
        saved_rh = sys.modules.pop("robin_stocks.robinhood", None)
        saved_rs = sys.modules.pop("robin_stocks", None)
        try:
            ctx = fetcher._fetch_sync({"username": "u", "password": "p", "totp_secret": ""})
        finally:
            if saved_rh is not None:
                sys.modules["robin_stocks.robinhood"] = saved_rh
            if saved_rs is not None:
                sys.modules["robin_stocks"] = saved_rs

        # Must not raise — error set or positions empty
        assert ctx is not None


# ---------------------------------------------------------------------------
# RobinhoodContextFetcher — correct position/account mapping
# ---------------------------------------------------------------------------


class TestRobinhoodContextFetcherPositionMapping:
    """Correct mapping when robin_stocks returns data — _fetch_sync tested directly."""

    def test_positions_mapped_correctly(self) -> None:
        from apps.api.src.services.robinhood_context_fetcher import RobinhoodContextFetcher

        fetcher = RobinhoodContextFetcher(AsyncMock())

        mock_rh = MagicMock()
        mock_rh.login.return_value = {"access_token": "tok"}
        mock_rh.account.get_open_stock_positions.return_value = [
            {
                "instrument": "https://api.robinhood.com/instruments/abc/",
                "quantity": "10",
                "average_buy_price": "150.00",
                "last_trade_price": "155.00",
            }
        ]
        mock_rh.stocks.get_instrument_by_url.return_value = {"symbol": "AAPL"}
        mock_rh.profiles.load_portfolio_profile.return_value = {"equity": "15500.00"}
        mock_rh.profiles.load_account_profile.return_value = {
            "buying_power": "4500.00",
            "cash": "4500.00",
        }
        mock_rh.authentication.logout.return_value = None

        with patch.dict(sys.modules, _rh_mock(mock_rh)):
            ctx = fetcher._fetch_sync({"username": "u", "password": "p", "totp_secret": ""})

        assert len(ctx.positions) == 1
        pos = ctx.positions[0]
        assert pos["ticker"] == "AAPL"
        assert pos["quantity"] == 10.0
        assert pos["avg_cost"] == 150.0
        assert pos["current_price"] == 155.0
        assert pos["market_value"] == 1550.0
        assert ctx.account_value == 15500.0
        assert ctx.buying_power == 4500.0
        assert ctx.cash == 4500.0
        assert ctx.error is None

    def test_to_dict_serializable(self) -> None:
        """LivePortfolioContext.to_dict() must be JSON-serializable."""
        from apps.api.src.services.robinhood_context_fetcher import LivePortfolioContext

        ctx = LivePortfolioContext(
            positions=[
                {
                    "ticker": "TSLA",
                    "quantity": 5.0,
                    "avg_cost": 200.0,
                    "current_price": 210.0,
                    "market_value": 1050.0,
                }
            ],
            account_value=10500.0,
            buying_power=3000.0,
            cash=3000.0,
            last_updated_at="2026-04-08T10:00:00+00:00",
            error=None,
        )
        d = ctx.to_dict()
        serialized = json.dumps(d)  # must not raise
        assert "TSLA" in serialized


# ---------------------------------------------------------------------------
# chat_responder — live portfolio injection into workdir + prompt
# ---------------------------------------------------------------------------


class TestChatResponderLivePortfolioInjection:
    """Verify _prepare_workdir injects live_portfolio and _build_prompt hints correctly."""

    def test_live_portfolio_written_to_context_file(self, tmp_path: Path) -> None:
        import apps.api.src.services.chat_responder as cr

        original_dir = cr.CHAT_SESSIONS_DIR
        cr.CHAT_SESSIONS_DIR = tmp_path
        try:
            agent_id = uuid.uuid4()
            ctx = {
                "agent": {"id": str(agent_id), "name": "Arty", "status": "RUNNING"},
                "chat": [],
                "trades": [],
                "_rh_creds": {},
            }
            live_portfolio = {
                "positions": [{"ticker": "NVDA", "quantity": 2.0}],
                "account_value": 8000.0,
                "buying_power": 2000.0,
                "cash": 2000.0,
                "last_updated_at": "2026-04-08T10:00:00Z",
                "error": None,
            }

            work_dir = cr._prepare_workdir(
                agent_id,
                ctx,
                "What are my positions?",
                live_portfolio=live_portfolio,
                rh_creds=None,
            )

            written = json.loads((work_dir / "agent_context.json").read_text())
            assert "live_portfolio" in written
            assert written["live_portfolio"]["positions"][0]["ticker"] == "NVDA"
            assert written["live_portfolio"]["account_value"] == 8000.0
        finally:
            cr.CHAT_SESSIONS_DIR = original_dir

    def test_no_live_portfolio_for_paper_agent(self, tmp_path: Path) -> None:
        """Paper agent: live_portfolio=None -> no live_portfolio key in agent_context.json."""
        import apps.api.src.services.chat_responder as cr

        original_dir = cr.CHAT_SESSIONS_DIR
        cr.CHAT_SESSIONS_DIR = tmp_path
        try:
            agent_id = uuid.uuid4()
            ctx = {
                "agent": {"id": str(agent_id), "name": "Arty", "status": "PAPER"},
                "chat": [],
                "trades": [],
                "_rh_creds": {},
            }

            work_dir = cr._prepare_workdir(
                agent_id,
                ctx,
                "How am I doing?",
                live_portfolio=None,
                rh_creds=None,
            )

            written = json.loads((work_dir / "agent_context.json").read_text())
            assert "live_portfolio" not in written
        finally:
            cr.CHAT_SESSIONS_DIR = original_dir

    def test_prompt_includes_live_portfolio_hint_for_live_agent(self) -> None:
        import apps.api.src.services.chat_responder as cr

        ctx = {"agent": {"name": "Arty", "character": "aggressive"}}
        prompt = cr._build_prompt(ctx, "show me positions", has_live_portfolio=True, has_mcp_tools=False)
        assert "LIVE Portfolio" in prompt

    def test_prompt_does_not_include_live_portfolio_section_for_paper_agent(self) -> None:
        import apps.api.src.services.chat_responder as cr

        ctx = {"agent": {"name": "Arty", "character": "conservative"}}
        prompt = cr._build_prompt(ctx, "show me positions", has_live_portfolio=False, has_mcp_tools=False)
        assert "LIVE Portfolio" not in prompt

    def test_prompt_includes_mcp_section_when_mcp_enabled(self) -> None:
        import apps.api.src.services.chat_responder as cr

        ctx = {"agent": {"name": "Arty", "character": "aggressive"}}
        prompt = cr._build_prompt(ctx, "show me positions", has_live_portfolio=True, has_mcp_tools=True)
        assert "robinhood_login" in prompt.lower() or "MCP" in prompt


# ---------------------------------------------------------------------------
# Security: workdir cleanup after respond_to_chat
# ---------------------------------------------------------------------------


class TestWorkdirCleanup:
    """Verify that the per-message workdir is always removed when respond_to_chat exits."""

    async def test_workdir_cleaned_up_after_session(self, tmp_path: Path) -> None:
        """work_dir must not exist on disk after respond_to_chat() completes."""
        import apps.api.src.services.chat_responder as cr

        # Capture the work_dir path created during the call
        captured_work_dirs: list[Path] = []
        original_prepare = cr._prepare_workdir

        def _spy_prepare(*args, **kwargs) -> Path:
            wd = original_prepare(*args, **kwargs)
            captured_work_dirs.append(wd)
            return wd

        agent_id = uuid.uuid4()

        # Minimal agent context returned by _load_context
        valid_ctx = {
            "agent": {
                "id": str(agent_id),
                "name": "TestAgent",
                "type": "PAPER",
                "status": "PAPER",
                "character": "test",
                "rules": {},
                "win_rate": None,
                "total_trades": 0,
                "daily_pnl": None,
                "total_pnl": None,
            },
            "chat": [],
            "trades": [],
            "_rh_creds": {},
        }

        with (
            patch.object(cr, "CHAT_SESSIONS_DIR", tmp_path),
            patch.object(cr, "_prepare_workdir", side_effect=_spy_prepare),
            # Bypass DB entirely — return a known-good ctx
            patch.object(cr, "_load_context", AsyncMock(return_value=valid_ctx)),
            patch("apps.api.src.services.chat_responder.ENABLE_SMART_CONTEXT", False),
            # Prevent _write_fallback_reply from touching the DB
            patch.object(cr, "_write_fallback_reply", AsyncMock()),
            # Make claude_agent_sdk unavailable — triggers ImportError path inside
            # the try block, which must still fire the finally cleanup
            patch.dict("sys.modules", {"claude_agent_sdk": None}),
        ):
            await cr.respond_to_chat(agent_id, "hello")

        # A workdir must have been created
        assert captured_work_dirs, "expected _prepare_workdir to be called"
        for wd in captured_work_dirs:
            assert not wd.exists(), f"workdir {wd} was not cleaned up"


# ---------------------------------------------------------------------------
# Security: _sanitize_error removes credentials from error messages
# ---------------------------------------------------------------------------


class TestSanitizeError:
    """Ensure _sanitize_error scrubs credential values and caps length."""

    def test_error_sanitization_removes_credentials(self) -> None:
        from apps.api.src.services.robinhood_context_fetcher import _sanitize_error

        exc = ValueError("Login failed for user hunter2 — bad password hunter2")
        result = _sanitize_error(exc, creds={"password": "hunter2"})

        assert "hunter2" not in result, "password must be scrubbed from error string"
        assert "***" in result, "scrubbed value should be replaced with ***"

    def test_error_sanitization_caps_length(self) -> None:
        from apps.api.src.services.robinhood_context_fetcher import _sanitize_error

        long_msg = "x" * 500
        exc = RuntimeError(long_msg)
        result = _sanitize_error(exc)

        # Format is "ClassName: <msg capped at 200>", so total must be ≤ len("RuntimeError: ") + 200
        assert len(result) <= len("RuntimeError: ") + 200

    def test_error_sanitization_includes_type_prefix(self) -> None:
        from apps.api.src.services.robinhood_context_fetcher import _sanitize_error

        exc = ConnectionError("timeout")
        result = _sanitize_error(exc)

        assert result.startswith("ConnectionError:")

    def test_error_sanitization_scrubs_username_and_totp(self) -> None:
        from apps.api.src.services.robinhood_context_fetcher import _sanitize_error

        creds = {"username": "secret@example.com", "password": "p@ss", "totp_secret": "JBSWY3DP"}
        exc = RuntimeError("auth failed for secret@example.com with JBSWY3DP")
        result = _sanitize_error(exc, creds=creds)

        assert "secret@example.com" not in result
        assert "JBSWY3DP" not in result

    def test_error_sanitization_no_creds_is_safe(self) -> None:
        """Calling without creds still works — just caps the length."""
        from apps.api.src.services.robinhood_context_fetcher import _sanitize_error

        exc = OSError("disk full")
        result = _sanitize_error(exc)

        assert "OSError" in result
        assert "disk full" in result
