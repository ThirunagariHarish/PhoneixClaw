"""Unit tests for V3 multi-tenancy scoping (shared.db.tenant).

Replaces V1 tests that imported from shared.models.tenant (removed).
Uses lightweight in-memory models to avoid PostgreSQL JSONB/SQLite incompatibility.
"""

import uuid

import pytest
from sqlalchemy import ForeignKey, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from shared.db.tenant import get_by_id_scoped, scoped_query


class _TestBase(DeclarativeBase):
    pass


class _TestUser(_TestBase):
    __tablename__ = "test_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), nullable=False)


class _TestAccount(_TestBase):
    __tablename__ = "test_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


@pytest.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        uid1 = str(uuid.uuid4())
        uid2 = str(uuid.uuid4())
        u1 = _TestUser(id=uid1, email="u1@test.com")
        u2 = _TestUser(id=uid2, email="u2@test.com")
        session.add_all([u1, u2])
        await session.flush()

        a1 = _TestAccount(user_id=uid1, name="User1 Paper")
        a2 = _TestAccount(user_id=uid2, name="User2 Live")
        session.add_all([a1, a2])
        await session.commit()

        yield session, uid1, uid2

    await engine.dispose()


class TestScopedQuery:
    @pytest.mark.asyncio
    async def test_returns_only_matching_user(self, async_session):
        session, uid1, uid2 = async_session
        accounts = await scoped_query(session, _TestAccount, uid1)
        assert len(accounts) == 1
        assert accounts[0].name == "User1 Paper"

    @pytest.mark.asyncio
    async def test_other_user_not_returned(self, async_session):
        session, uid1, uid2 = async_session
        accounts = await scoped_query(session, _TestAccount, uid1)
        names = [a.name for a in accounts]
        assert "User2 Live" not in names


class TestGetByIdScoped:
    @pytest.mark.asyncio
    async def test_returns_matching_record(self, async_session):
        session, uid1, uid2 = async_session
        accounts = await scoped_query(session, _TestAccount, uid1)
        acct = accounts[0]
        result = await get_by_id_scoped(session, _TestAccount, acct.id, uid1)
        assert result is not None
        assert result.name == "User1 Paper"

    @pytest.mark.asyncio
    async def test_wrong_user_returns_none(self, async_session):
        session, uid1, uid2 = async_session
        accounts = await scoped_query(session, _TestAccount, uid1)
        acct = accounts[0]
        result = await get_by_id_scoped(session, _TestAccount, acct.id, uid2)
        assert result is None
