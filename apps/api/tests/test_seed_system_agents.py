"""
Unit tests for _seed_system_agents().

Covers:
  1. Idempotency — calling the function twice executes exactly 5 × 2 = 10 INSERTs
     without raising.
  2. All 5 reserved UUIDs are included in the INSERT calls.
  3. Error propagation — a DB error is NOT swallowed; it propagates out of
     _seed_system_agents() so lifespan()'s _log.exception handler sees it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_UUIDS = {
    "00000000-0000-0000-0000-000000000001",
    "00000000-0000-0000-0000-000000000002",
    "00000000-0000-0000-0000-000000000003",
    "00000000-0000-0000-0000-000000000004",
    "00000000-0000-0000-0000-000000000005",
}


def _make_mock_engine():
    """Return a mock async engine whose begin() context manager works cleanly."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _fake_begin():
        yield mock_conn

    mock_engine = MagicMock()
    mock_engine.begin = _fake_begin
    return mock_engine, mock_conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_idempotency_executes_10_inserts():
    """Calling _seed_system_agents() twice must fire exactly 10 INSERT calls."""
    from apps.api.src.main import _seed_system_agents

    mock_engine, mock_conn = _make_mock_engine()

    with patch("shared.db.engine.get_engine", return_value=mock_engine):
        await _seed_system_agents()
        await _seed_system_agents()

    assert mock_conn.execute.call_count == 10, (
        f"Expected 10 INSERT executions (5 agents × 2 calls), "
        f"got {mock_conn.execute.call_count}"
    )


@pytest.mark.asyncio
async def test_seed_covers_all_five_uuids():
    """All 5 reserved UUIDs must appear in the INSERT parameters."""
    from apps.api.src.main import _seed_system_agents

    mock_engine, mock_conn = _make_mock_engine()
    seen_ids: set[str] = set()

    async def _capture_execute(stmt, params=None):
        if params and "id" in params:
            seen_ids.add(params["id"])

    mock_conn.execute = AsyncMock(side_effect=_capture_execute)

    with patch("shared.db.engine.get_engine", return_value=mock_engine):
        await _seed_system_agents()

    assert seen_ids == EXPECTED_UUIDS, (
        f"Missing UUIDs: {EXPECTED_UUIDS - seen_ids}; "
        f"unexpected UUIDs: {seen_ids - EXPECTED_UUIDS}"
    )


@pytest.mark.asyncio
async def test_seed_propagates_db_error():
    """A DB error must propagate out of _seed_system_agents() — not be swallowed."""
    from apps.api.src.main import _seed_system_agents

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=RuntimeError("DB connection failed"))

    @asynccontextmanager
    async def _failing_begin():
        yield mock_conn

    mock_engine = MagicMock()
    mock_engine.begin = _failing_begin

    with patch("shared.db.engine.get_engine", return_value=mock_engine):
        with pytest.raises(RuntimeError, match="DB connection failed"):
            await _seed_system_agents()
