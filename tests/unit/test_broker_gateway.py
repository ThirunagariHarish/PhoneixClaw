"""Unit tests for the Broker Gateway service — multi-account support."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_gateway_state():
    """Reset module-level state before each test."""
    import services.broker_gateway.src.main as gw

    gw._sessions.clear()
    gw._rh_module = None
    yield
    gw._sessions.clear()


def _make_paper_session(account_id: str = "legacy", cash: float = 100_000.00):
    """Create a paper-mode RobinhoodSession for testing."""
    import services.broker_gateway.src.main as gw

    return gw.RobinhoodSession(
        account_id=account_id,
        username="",
        password="",
        paper_mode=True,
        paper_cash=cash,
    )


def _register_session(session):
    """Register a session in the pool."""
    import services.broker_gateway.src.main as gw

    with gw._sessions_lock:
        gw._sessions[session.account_id] = session


@pytest.fixture()
def paper_client(monkeypatch):
    """TestClient with a single legacy paper-mode session."""
    import services.broker_gateway.src.main as gw

    monkeypatch.setattr(gw, "GLOBAL_PAPER_MODE", True)
    monkeypatch.setattr(gw, "RH_USERNAME", "")
    monkeypatch.setattr(gw, "DATABASE_URL", "")

    session = _make_paper_session()
    _register_session(session)

    with TestClient(gw.app) as client:
        yield client


@pytest.fixture()
def multi_paper_client(monkeypatch):
    """TestClient with two paper-mode sessions (acct-A and acct-B)."""
    import services.broker_gateway.src.main as gw

    monkeypatch.setattr(gw, "GLOBAL_PAPER_MODE", True)
    monkeypatch.setattr(gw, "RH_USERNAME", "")
    monkeypatch.setattr(gw, "DATABASE_URL", "")

    _register_session(_make_paper_session("acct-A"))
    _register_session(_make_paper_session("acct-B"))

    with TestClient(gw.app) as client:
        yield client


@pytest.fixture()
def live_client(monkeypatch):
    """TestClient with PAPER_MODE off, mocked robin_stocks session."""
    import services.broker_gateway.src.main as gw

    monkeypatch.setattr(gw, "GLOBAL_PAPER_MODE", False)
    monkeypatch.setattr(gw, "RH_USERNAME", "test@example.com")
    monkeypatch.setattr(gw, "RH_PASSWORD", "secret")
    monkeypatch.setattr(gw, "RH_TOTP_SECRET", "")
    monkeypatch.setattr(gw, "DATABASE_URL", "")

    session = gw.RobinhoodSession(
        account_id="legacy",
        username="test@example.com",
        password="secret",
        paper_mode=False,
        logged_in=True,
        login_time=time.time(),
    )
    _register_session(session)

    with TestClient(gw.app) as client:
        yield client


# ===================================================================
# RobinhoodSession dataclass
# ===================================================================
class TestRobinhoodSession:
    def test_session_age_zero_when_no_login(self):
        import services.broker_gateway.src.main as gw

        s = gw.RobinhoodSession(account_id="test", username="u", password="p")
        assert s.session_age_hours() == 0.0

    def test_session_age_positive(self):
        import services.broker_gateway.src.main as gw

        s = gw.RobinhoodSession(account_id="test", username="u", password="p", login_time=time.time() - 7200)
        age = s.session_age_hours()
        assert 1.9 <= age <= 2.1

    def test_needs_refresh_false_when_fresh(self):
        import services.broker_gateway.src.main as gw

        s = gw.RobinhoodSession(
            account_id="test", username="u", password="p",
            logged_in=True, login_time=time.time(),
        )
        assert s.needs_refresh() is False

    def test_needs_refresh_true_when_old(self):
        import services.broker_gateway.src.main as gw

        s = gw.RobinhoodSession(
            account_id="test", username="u", password="p",
            logged_in=True, login_time=time.time() - (21 * 3600),
        )
        assert s.needs_refresh() is True

    def test_needs_refresh_false_when_not_logged_in(self):
        import services.broker_gateway.src.main as gw

        s = gw.RobinhoodSession(
            account_id="test", username="u", password="p",
            logged_in=False, login_time=time.time() - (21 * 3600),
        )
        assert s.needs_refresh() is False


# ===================================================================
# Account resolution
# ===================================================================
class TestResolveAccountId:
    def test_resolve_explicit_id(self):
        import services.broker_gateway.src.main as gw

        _register_session(_make_paper_session("acct-X"))
        assert gw._resolve_account_id("acct-X") == "acct-X"

    def test_resolve_legacy_fallback(self):
        import services.broker_gateway.src.main as gw

        _register_session(_make_paper_session("legacy"))
        assert gw._resolve_account_id(None) == "legacy"

    def test_resolve_single_account_fallback(self):
        import services.broker_gateway.src.main as gw

        _register_session(_make_paper_session("only-one"))
        assert gw._resolve_account_id(None) == "only-one"

    def test_resolve_requires_id_with_multiple(self):
        import services.broker_gateway.src.main as gw

        _register_session(_make_paper_session("a"))
        _register_session(_make_paper_session("b"))
        with pytest.raises(Exception, match="account_id is required"):
            gw._resolve_account_id(None)

    def test_resolve_no_accounts(self):
        import services.broker_gateway.src.main as gw

        with pytest.raises(Exception, match="No accounts configured"):
            gw._resolve_account_id(None)


# ===================================================================
# Health endpoint
# ===================================================================
class TestHealth:
    def test_health_returns_ok(self, paper_client):
        resp = paper_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["global_paper_mode"] is True
        assert "legacy" in body["accounts"]

    def test_health_multiple_accounts(self, multi_paper_client):
        resp = multi_paper_client.get("/health")
        body = resp.json()
        assert "acct-A" in body["accounts"]
        assert "acct-B" in body["accounts"]


# ===================================================================
# Auth status
# ===================================================================
class TestAuthStatus:
    def test_auth_status_all_accounts(self, multi_paper_client):
        resp = multi_paper_client.get("/auth/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "accounts" in body
        assert len(body["accounts"]) == 2

    def test_auth_status_single_account(self, multi_paper_client):
        resp = multi_paper_client.get("/auth/status", params={"account_id": "acct-A"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["account_id"] == "acct-A"
        assert body["paper_mode"] is True

    def test_auth_status_unknown_account(self, paper_client):
        resp = paper_client.get("/auth/status", params={"account_id": "nonexistent"})
        assert resp.status_code == 404


# ===================================================================
# Auth login
# ===================================================================
class TestAuthLogin:
    def test_login_paper_mode(self, paper_client):
        resp = paper_client.post("/auth/login", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["paper_mode"] is True
        assert body["account_id"] == "legacy"

    def test_login_specific_account(self, multi_paper_client):
        resp = multi_paper_client.post("/auth/login", json={"account_id": "acct-B"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["account_id"] == "acct-B"

    def test_login_live_success(self, live_client, monkeypatch):
        import services.broker_gateway.src.main as gw

        session = gw._sessions["legacy"]
        session.logged_in = False

        def mock_ensure(s):
            s.logged_in = True

        monkeypatch.setattr(gw, "_ensure_login", mock_ensure)
        resp = live_client.post("/auth/login", json={})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_login_live_failure(self, live_client, monkeypatch):
        import services.broker_gateway.src.main as gw

        session = gw._sessions["legacy"]
        session.logged_in = False

        def mock_ensure(s):
            raise ValueError("bad credentials")

        monkeypatch.setattr(gw, "_ensure_login", mock_ensure)
        resp = live_client.post("/auth/login", json={})
        assert resp.status_code == 500

    def test_login_unknown_account(self, paper_client):
        resp = paper_client.post("/auth/login", json={"account_id": "nope"})
        assert resp.status_code == 404


# ===================================================================
# Stock orders
# ===================================================================
class TestStockOrders:
    def test_place_stock_buy_paper(self, paper_client):
        resp = paper_client.post("/orders/stock", json={
            "ticker": "PLTR", "quantity": 10, "side": "buy", "price": 50.0,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["paper_mode"] is True
        assert body["state"] == "filled"
        assert "order_id" in body
        assert body["fill_price"] > 0
        assert body["account_id"] == "legacy"

    def test_place_stock_with_account_id(self, multi_paper_client):
        resp = multi_paper_client.post("/orders/stock", json={
            "ticker": "AAPL", "quantity": 5, "side": "buy", "price": 150.0,
            "account_id": "acct-A",
        })
        assert resp.status_code == 200
        assert resp.json()["account_id"] == "acct-A"

    def test_place_stock_sell_paper(self, paper_client):
        paper_client.post("/orders/stock", json={
            "ticker": "AAPL", "quantity": 5, "side": "buy", "price": 150.0,
        })
        resp = paper_client.post("/orders/stock", json={
            "ticker": "AAPL", "quantity": 5, "side": "sell", "price": 155.0,
        })
        assert resp.status_code == 200
        assert resp.json()["state"] == "filled"

    def test_place_stock_invalid_side(self, paper_client):
        resp = paper_client.post("/orders/stock", json={
            "ticker": "PLTR", "quantity": 10, "side": "short", "price": 50.0,
        })
        assert resp.status_code == 422

    def test_place_stock_missing_ticker(self, paper_client):
        resp = paper_client.post("/orders/stock", json={
            "quantity": 10, "side": "buy", "price": 50.0,
        })
        assert resp.status_code == 422

    def test_orders_isolated_between_accounts(self, multi_paper_client):
        multi_paper_client.post("/orders/stock", json={
            "ticker": "TSLA", "quantity": 3, "side": "buy", "price": 200.0,
            "account_id": "acct-A",
        })
        resp_a = multi_paper_client.get("/positions", params={"account_id": "acct-A"})
        resp_b = multi_paper_client.get("/positions", params={"account_id": "acct-B"})
        assert len(resp_a.json()["positions"]) == 1
        assert len(resp_b.json()["positions"]) == 0

    def test_stock_order_requires_account_id_multi(self, multi_paper_client):
        resp = multi_paper_client.post("/orders/stock", json={
            "ticker": "PLTR", "quantity": 10, "side": "buy", "price": 50.0,
        })
        assert resp.status_code == 400


# ===================================================================
# Option orders
# ===================================================================
class TestOptionOrders:
    def test_place_option_buy_paper(self, paper_client):
        resp = paper_client.post("/orders/option", json={
            "ticker": "PLTR", "strike": 132, "expiry": "2026-04-17",
            "option_type": "call", "side": "buy", "quantity": 1, "price": 2.70,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["paper_mode"] is True
        assert body["state"] == "filled"
        assert body["account_id"] == "legacy"

    def test_place_option_with_account_id(self, multi_paper_client):
        resp = multi_paper_client.post("/orders/option", json={
            "ticker": "PLTR", "strike": 132, "expiry": "2026-04-17",
            "option_type": "call", "side": "buy", "quantity": 1, "price": 2.70,
            "account_id": "acct-B",
        })
        assert resp.status_code == 200
        assert resp.json()["account_id"] == "acct-B"

    def test_place_option_invalid_type(self, paper_client):
        resp = paper_client.post("/orders/option", json={
            "ticker": "PLTR", "strike": 132, "expiry": "2026-04-17",
            "option_type": "straddle", "side": "buy", "quantity": 1, "price": 2.70,
        })
        assert resp.status_code == 422


# ===================================================================
# Positions
# ===================================================================
class TestPositions:
    def test_positions_empty_paper(self, paper_client):
        resp = paper_client.get("/positions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["paper_mode"] is True
        assert body["positions"] == []

    def test_positions_after_buy_paper(self, paper_client):
        paper_client.post("/orders/stock", json={
            "ticker": "TSLA", "quantity": 3, "side": "buy", "price": 200.0,
        })
        resp = paper_client.get("/positions")
        body = resp.json()
        assert len(body["positions"]) == 1
        assert body["positions"][0]["ticker"] == "TSLA"
        assert body["positions"][0]["quantity"] == 3.0

    def test_positions_with_account_id(self, multi_paper_client):
        multi_paper_client.post("/orders/stock", json={
            "ticker": "NVDA", "quantity": 2, "side": "buy", "price": 800.0,
            "account_id": "acct-A",
        })
        resp = multi_paper_client.get("/positions", params={"account_id": "acct-A"})
        assert resp.status_code == 200
        assert resp.json()["account_id"] == "acct-A"
        assert len(resp.json()["positions"]) == 1


# ===================================================================
# Watchlist
# ===================================================================
class TestWatchlist:
    def test_add_to_watchlist_paper(self, paper_client):
        resp = paper_client.post("/watchlist", json={
            "ticker": "PLTR", "watchlist_name": "Phoenix Paper",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "added"
        assert body["paper_mode"] is True
        assert body["account_id"] == "legacy"

    def test_get_watchlist_paper(self, paper_client):
        paper_client.post("/watchlist", json={"ticker": "PLTR"})
        paper_client.post("/watchlist", json={"ticker": "AAPL"})
        resp = paper_client.get("/watchlist", params={"name": "Phoenix Paper"})
        assert resp.status_code == 200
        body = resp.json()
        assert "PLTR" in body["symbols"]
        assert "AAPL" in body["symbols"]
        assert body["count"] == 2

    def test_watchlist_no_duplicates_paper(self, paper_client):
        paper_client.post("/watchlist", json={"ticker": "PLTR"})
        paper_client.post("/watchlist", json={"ticker": "PLTR"})
        resp = paper_client.get("/watchlist", params={"name": "Phoenix Paper"})
        assert resp.json()["count"] == 1

    def test_get_empty_watchlist_paper(self, paper_client):
        resp = paper_client.get("/watchlist", params={"name": "Nonexistent"})
        assert resp.status_code == 200
        assert resp.json()["symbols"] == []

    def test_watchlist_with_account_id(self, multi_paper_client):
        multi_paper_client.post("/watchlist", json={
            "ticker": "TSLA", "account_id": "acct-A",
        })
        resp = multi_paper_client.get("/watchlist", params={
            "name": "Phoenix Paper", "account_id": "acct-A",
        })
        assert resp.status_code == 200
        assert "TSLA" in resp.json()["symbols"]

    def test_watchlist_isolated_between_accounts(self, multi_paper_client):
        multi_paper_client.post("/watchlist", json={
            "ticker": "TSLA", "account_id": "acct-A",
        })
        resp_b = multi_paper_client.get("/watchlist", params={
            "name": "Phoenix Paper", "account_id": "acct-B",
        })
        assert resp_b.json()["count"] == 0


# ===================================================================
# Account
# ===================================================================
class TestAccount:
    def test_account_initial_paper(self, paper_client):
        resp = paper_client.get("/account")
        assert resp.status_code == 200
        body = resp.json()
        assert body["paper_mode"] is True
        assert body["buying_power"] == 100_000.00
        assert body["portfolio_value"] == 100_000.00
        assert body["account_id"] == "legacy"

    def test_account_after_buy_paper(self, paper_client):
        paper_client.post("/orders/stock", json={
            "ticker": "PLTR", "quantity": 10, "side": "buy", "price": 50.0,
        })
        resp = paper_client.get("/account")
        body = resp.json()
        assert body["buying_power"] < 100_000.00

    def test_account_with_account_id(self, multi_paper_client):
        resp = multi_paper_client.get("/account", params={"account_id": "acct-B"})
        assert resp.status_code == 200
        assert resp.json()["account_id"] == "acct-B"

    def test_account_isolated_between_accounts(self, multi_paper_client):
        multi_paper_client.post("/orders/stock", json={
            "ticker": "PLTR", "quantity": 10, "side": "buy", "price": 50.0,
            "account_id": "acct-A",
        })
        resp_a = multi_paper_client.get("/account", params={"account_id": "acct-A"})
        resp_b = multi_paper_client.get("/account", params={"account_id": "acct-B"})
        assert resp_a.json()["buying_power"] < 100_000.00
        assert resp_b.json()["buying_power"] == 100_000.00


# ===================================================================
# Paper fill price
# ===================================================================
class TestPaperFillPrice:
    def test_fill_price_within_slippage(self):
        import services.broker_gateway.src.main as gw

        for _ in range(100):
            fill = gw._paper_fill_price(100.0)
            assert 99.94 <= fill <= 100.06


# ===================================================================
# Ensure login
# ===================================================================
class TestEnsureLogin:
    def test_ensure_login_paper_mode(self):
        import services.broker_gateway.src.main as gw

        s = gw.RobinhoodSession(account_id="t", username="", password="", paper_mode=True)
        gw._ensure_login(s)
        assert s.logged_in is True

    def test_ensure_login_already_logged_in(self):
        import services.broker_gateway.src.main as gw

        s = gw.RobinhoodSession(account_id="t", username="u", password="p", logged_in=True)
        gw._ensure_login(s)
        assert s.logged_in is True

    def test_ensure_login_no_credentials(self):
        import services.broker_gateway.src.main as gw

        s = gw.RobinhoodSession(account_id="t", username="", password="")
        with pytest.raises(ValueError, match="credentials missing"):
            gw._ensure_login(s)

    def test_do_login_uses_persistent_session_pickle(self, monkeypatch, tmp_path):
        import services.broker_gateway.src.main as gw

        session = gw.RobinhoodSession(
            account_id="acct-1",
            username="user@example.com",
            password="secret",
            paper_mode=False,
        )

        login_calls = []

        class FakeRH:
            def login(self, username, password, **kwargs):
                login_calls.append({"username": username, "password": password, **kwargs})
                return {"access_token": "token"}

        monkeypatch.setattr(gw, "_rh_module", FakeRH())
        monkeypatch.setattr(gw, "TOKEN_DIR", tmp_path / ".tokens")

        gw._do_login(session)

        assert session.logged_in is True
        assert login_calls
        call = login_calls[0]
        assert call["store_session"] is True
        assert call["expiresIn"] == 86400
        assert call["pickle_name"].startswith("phoenix_acct-1_user")
        assert (tmp_path / ".tokens").exists()


# ===================================================================
# Retry helper
# ===================================================================
class TestRetry:
    def test_retry_success_first_attempt(self):
        import services.broker_gateway.src.main as gw

        fn = MagicMock(return_value={"ok": True})
        result = gw._retry(fn, "arg1")
        assert result == {"ok": True}
        fn.assert_called_once_with("arg1")

    def test_retry_eventual_success(self):
        import services.broker_gateway.src.main as gw

        fn = MagicMock(side_effect=[RuntimeError("transient"), {"ok": True}])
        result = gw._retry(fn, "a")
        assert result == {"ok": True}
        assert fn.call_count == 2

    def test_retry_all_fail(self):
        import services.broker_gateway.src.main as gw

        fn = MagicMock(side_effect=RuntimeError("permanent"))
        with pytest.raises(RuntimeError, match="permanent"):
            gw._retry(fn)
        assert fn.call_count == gw.MAX_RETRIES

    def test_retry_marks_session_for_renewal_on_401(self):
        import services.broker_gateway.src.main as gw

        s = gw.RobinhoodSession(account_id="t", username="u", password="p", logged_in=True, paper_mode=False)
        fn = MagicMock(side_effect=[RuntimeError("401 unauthorized"), {"ok": True}])

        login_calls = []

        def mock_do_login(sess):
            login_calls.append(sess.account_id)
            sess.logged_in = True

        with patch.object(gw, "_do_login", side_effect=mock_do_login):
            result = gw._retry(fn, "a", session=s)

        assert result == {"ok": True}
        assert len(login_calls) == 1


# ===================================================================
# Rate limiter
# ===================================================================
class TestRateLimiter:
    def test_rate_limiter_enforces_interval(self):
        import services.broker_gateway.src.main as gw

        limiter = gw._RateLimiter(0.1)
        start = time.monotonic()
        limiter.acquire()
        limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.09


# ===================================================================
# DB connector loading
# ===================================================================
class TestLoadConnectorsFromDb:
    def test_no_database_url(self, monkeypatch):
        import services.broker_gateway.src.main as gw

        monkeypatch.setattr(gw, "DATABASE_URL", "")
        result = gw._load_connectors_from_db()
        assert result == []

    def test_load_connectors_success(self, monkeypatch):
        import services.broker_gateway.src.main as gw

        monkeypatch.setattr(gw, "DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setattr(gw, "GLOBAL_PAPER_MODE", False)

        fake_creds = {"username": "user@rh.com", "password": "pass123", "totp_secret": "TOTP"}
        fake_row = ("uuid-1", "encrypted-blob", {"paper_mode": True}, True)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [fake_row]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_engine.dispose = MagicMock()

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            with patch("shared.crypto.credentials.decrypt_credentials", return_value=fake_creds):
                sessions = gw._load_connectors_from_db()

        assert len(sessions) == 1
        assert sessions[0].account_id == "uuid-1"
        assert sessions[0].username == "user@rh.com"
        assert sessions[0].paper_mode is True
        assert sessions[0].totp_secret == "TOTP"

    def test_load_connectors_decrypt_failure(self, monkeypatch):
        import services.broker_gateway.src.main as gw

        monkeypatch.setattr(gw, "DATABASE_URL", "postgresql://localhost/test")

        fake_row = ("uuid-bad", "encrypted-blob", {}, True)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [fake_row]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_engine.dispose = MagicMock()

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            with patch(
                "shared.crypto.credentials.decrypt_credentials",
                side_effect=RuntimeError("bad key"),
            ):
                sessions = gw._load_connectors_from_db()

        assert sessions == []

    def test_load_connectors_no_credentials(self, monkeypatch):
        import services.broker_gateway.src.main as gw

        monkeypatch.setattr(gw, "DATABASE_URL", "postgresql://localhost/test")

        fake_row = ("uuid-empty", None, {}, True)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [fake_row]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_engine.dispose = MagicMock()

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            sessions = gw._load_connectors_from_db()

        assert sessions == []


# ===================================================================
# Init sessions
# ===================================================================
class TestInitSessions:
    def test_init_with_legacy_env_vars(self, monkeypatch):
        import services.broker_gateway.src.main as gw

        monkeypatch.setattr(gw, "DATABASE_URL", "")
        monkeypatch.setattr(gw, "RH_USERNAME", "test@rh.com")
        monkeypatch.setattr(gw, "RH_PASSWORD", "pass")
        monkeypatch.setattr(gw, "RH_TOTP_SECRET", "TOTP123")
        monkeypatch.setattr(gw, "GLOBAL_PAPER_MODE", False)

        gw._init_sessions()

        assert "legacy" in gw._sessions
        s = gw._sessions["legacy"]
        assert s.username == "test@rh.com"
        assert s.totp_secret == "TOTP123"
        assert s.paper_mode is False

    def test_init_no_config_creates_paper_session(self, monkeypatch):
        import services.broker_gateway.src.main as gw

        monkeypatch.setattr(gw, "DATABASE_URL", "")
        monkeypatch.setattr(gw, "RH_USERNAME", "")
        monkeypatch.setattr(gw, "RH_PASSWORD", "")
        monkeypatch.setattr(gw, "GLOBAL_PAPER_MODE", False)

        gw._init_sessions()

        assert "legacy" in gw._sessions
        assert gw._sessions["legacy"].paper_mode is True

    def test_init_with_db_connectors(self, monkeypatch):
        import services.broker_gateway.src.main as gw

        monkeypatch.setattr(gw, "RH_USERNAME", "")

        db_session = gw.RobinhoodSession(
            account_id="db-acct",
            username="db@rh.com",
            password="p",
            paper_mode=True,
        )
        monkeypatch.setattr(gw, "_load_connectors_from_db", lambda: [db_session])

        gw._init_sessions()

        assert "db-acct" in gw._sessions
        assert gw._sessions["db-acct"].username == "db@rh.com"


# ===================================================================
# Get session
# ===================================================================
class TestGetSession:
    def test_get_existing_session(self):
        import services.broker_gateway.src.main as gw

        _register_session(_make_paper_session("test-id"))
        s = gw._get_session("test-id")
        assert s.account_id == "test-id"

    def test_get_missing_session_raises_404(self):
        import services.broker_gateway.src.main as gw

        with pytest.raises(Exception, match="not found"):
            gw._get_session("nonexistent")
