"""Integration tests for backtest API (mocked Discord, real DB)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.api_gateway.src.middleware import JWTMiddleware
from services.api_gateway.src.routes.backtest import router as backtest_router
from services.auth_service.src.auth import create_access_token
from shared.crypto.credentials import encrypt_credentials
from shared.models.database import get_session
from shared.models.trade import Base, Channel, DataSource, TradingAccount, User


@pytest.fixture
def test_db_url():
    return "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_engine(test_db_url):
    engine = create_async_engine(test_db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_engine):
    return async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


@pytest.fixture
def app(test_session_factory):
    """Create minimal app with backtest router."""

    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    app = FastAPI()
    app.add_middleware(JWTMiddleware)
    app.include_router(backtest_router)
    app.dependency_overrides[get_session] = override_get_session
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
async def test_user(test_session_factory):
    """Create test user and return (user_id, session)."""
    from services.auth_service.src.auth import hash_password

    async with test_session_factory() as session:
        user = User(
            id=uuid.uuid4(),
            email="backtest@test.com",
            password_hash=hash_password("test123"),
            name="Backtest User",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return str(user.id)


@pytest.fixture
async def test_data(test_session_factory, test_user):
    """Create DataSource, Channel, TradingAccount for test user."""
    user_id = uuid.UUID(test_user) if isinstance(test_user, str) else test_user
    creds_enc = encrypt_credentials({"user_token": "fake-discord-token"})

    async with test_session_factory() as session:
        ds = DataSource(
            id=uuid.uuid4(),
            user_id=user_id,
            source_type="discord",
            display_name="Test Discord",
            auth_type="user_token",
            credentials_encrypted=creds_enc,
        )
        session.add(ds)
        await session.flush()

        ch = Channel(
            id=uuid.uuid4(),
            data_source_id=ds.id,
            channel_identifier="123456789",
            display_name="Test Channel",
        )
        session.add(ch)
        await session.flush()

        acc_creds = encrypt_credentials({"api_key": "fake", "secret_key": "fake"})
        acc = TradingAccount(
            id=uuid.uuid4(),
            user_id=user_id,
            broker_type="alpaca",
            display_name="Test Account",
            credentials_encrypted=acc_creds,
        )
        session.add(acc)
        await session.commit()
        await session.refresh(ds)
        await session.refresh(ch)
        await session.refresh(acc)

    return {
        "data_source_id": str(ds.id),
        "channel_id": str(ch.id),
        "trading_account_id": str(acc.id),
    }


@pytest.mark.asyncio
async def test_backtest_api_creates_run_and_trades(
    test_session_factory,
    test_user,
    test_data,
    client,
):
    """POST /api/v1/backtest creates run and computes trades when Discord is mocked."""
    user_id = test_user
    ds_id = test_data["data_source_id"]
    ch_id = test_data["channel_id"]
    acc_id = test_data["trading_account_id"]

    synthetic_messages = [
        {
            "content": "BTO AAPL 190C 3/21 @ 2.50",
            "timestamp": datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            "author": "user",
            "message_id": "1",
        },
        {
            "content": "STC AAPL 190C @ 3.00",
            "timestamp": datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
            "author": "user",
            "message_id": "2",
        },
    ]

    token = create_access_token(user_id)

    with patch(
        "services.api_gateway.src.routes.backtest.fetch_channel_history",
        new_callable=AsyncMock,
        return_value=synthetic_messages,
    ):
        resp = client.post(
            "/api/v1/backtest",
            json={
                "start_date": "2025-01-15T00:00:00Z",
                "end_date": "2025-01-16T00:00:00Z",
                "data_source_id": ds_id,
                "channel_id": ch_id,
                "trading_account_id": acc_id,
                "name": "Integration Test Run",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "completed"
    assert data["summary"] is not None
    assert data["summary"]["executed_trades"] == 1
    assert data["summary"]["total_trades"] == 1

    run_id = data["id"]
    trades_resp = client.get(
        f"/api/v1/backtest/{run_id}/trades",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trades_resp.status_code == 200
    trades_data = trades_resp.json()
    assert "trades" in trades_data
    assert len(trades_data["trades"]) == 1
    assert trades_data["trades"][0]["ticker"] == "AAPL"
    assert trades_data["trades"][0]["realized_pnl"] == 0.5
