"""Unit tests for broker connector ↔ trading_account auto-linkage.

Adding a `robinhood`/`alpaca`/`ibkr`/`tradier` connector must create a
matching TradingAccount row so the agent creation wizard's broker-account
dropdown populates. Historical connectors are backfilled on first call
to GET /api/v2/trading-accounts?category=broker.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _mock_execute_returning_scalars(values: list):
    """Build an AsyncMock session.execute(...) that returns a result whose
    .scalars() iterates over `values`. `add` stays sync to match SQLAlchemy."""
    session = AsyncMock()
    session.add = MagicMock()
    scalars = MagicMock()
    scalars.__iter__ = lambda self: iter(values)
    scalars.all = MagicMock(return_value=list(values))
    result = MagicMock()
    result.scalars.return_value = scalars
    session.execute.return_value = result
    return session


def _make_connector(connector_type: str = "robinhood", **overrides):
    connector = MagicMock()
    connector.id = overrides.get("id", uuid.uuid4())
    connector.user_id = overrides.get("user_id", uuid.uuid4())
    connector.type = connector_type
    connector.name = overrides.get("name", "Test Broker")
    connector.config = overrides.get("config", {"paper_mode": True})
    connector.credentials_encrypted = overrides.get("credentials_encrypted", b"enc")
    return connector


def test_account_type_from_config_defaults_to_paper():
    from apps.api.src.routes.connectors import _account_type_from_config

    assert _account_type_from_config({}) == "paper"
    assert _account_type_from_config({"paper_mode": True}) == "paper"
    assert _account_type_from_config({"mode": "paper"}) == "paper"


def test_account_type_from_config_detects_live():
    from apps.api.src.routes.connectors import _account_type_from_config

    assert _account_type_from_config({"paper_mode": False}) == "live"
    assert _account_type_from_config({"mode": "live"}) == "live"
    assert _account_type_from_config({"mode": "REAL"}) == "live"
    assert _account_type_from_config({"mode": "production"}) == "live"


@pytest.mark.asyncio
async def test_ensure_trading_account_creates_row_for_broker_connector():
    from apps.api.src.routes.connectors import _ensure_trading_account_for_connector

    connector = _make_connector("robinhood")
    session = _mock_execute_returning_scalars([])

    account, created = await _ensure_trading_account_for_connector(session, connector)

    assert created is True
    assert account is not None
    assert account.broker == "robinhood"
    assert account.user_id == connector.user_id
    assert account.name == connector.name
    assert account.account_type == "paper"
    assert account.credentials_encrypted == connector.credentials_encrypted
    assert account.config == {"connector_id": str(connector.id)}
    session.add.assert_called_once()
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_ensure_trading_account_ignores_non_broker_types():
    from apps.api.src.routes.connectors import _ensure_trading_account_for_connector

    connector = _make_connector("discord")
    session = AsyncMock()

    account, created = await _ensure_trading_account_for_connector(session, connector)

    assert account is None
    assert created is False
    session.add.assert_not_called()
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_trading_account_is_idempotent():
    """If a TradingAccount already links to this connector, return it without
    creating a duplicate."""
    from apps.api.src.routes.connectors import _ensure_trading_account_for_connector

    connector = _make_connector("robinhood")
    existing = MagicMock()
    existing.config = {"connector_id": str(connector.id)}
    session = _mock_execute_returning_scalars([existing])

    account, created = await _ensure_trading_account_for_connector(session, connector)

    assert created is False
    assert account is existing
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_trading_account_distinguishes_different_connectors():
    """A TradingAccount linked to a DIFFERENT connector must not be reused."""
    from apps.api.src.routes.connectors import _ensure_trading_account_for_connector

    connector = _make_connector("robinhood")
    other = MagicMock()
    other.config = {"connector_id": str(uuid.uuid4())}
    session = _mock_execute_returning_scalars([other])

    account, created = await _ensure_trading_account_for_connector(session, connector)

    assert created is True
    assert account is not other
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_trading_account_derives_live_account_type():
    from apps.api.src.routes.connectors import _ensure_trading_account_for_connector

    connector = _make_connector("alpaca", config={"mode": "live"})
    session = _mock_execute_returning_scalars([])

    account, _ = await _ensure_trading_account_for_connector(session, connector)

    assert account.account_type == "live"
    assert account.broker == "alpaca"
