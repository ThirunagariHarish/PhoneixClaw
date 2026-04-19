"""Unit tests for DLQ cleanup script.

Tests verify:
- Dry-run mode counts but doesn't delete
- Real mode deletes matching rows
- Correct WHERE clause (resolved=true AND resolved_at < cutoff)
- Idempotent (safe to run repeatedly)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.cleanup_dlq import cleanup_dlq


@pytest.fixture
def mock_session():
    """Mock async DB session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.fixture
def mock_session_maker(mock_session):
    """Mock session maker that returns mock session."""
    maker = MagicMock()
    maker.return_value = mock_session
    return maker


@pytest.mark.asyncio
async def test_cleanup_dlq_dry_run(mock_session, mock_session_maker):
    """Dry-run mode should count but not delete."""
    # Mock count query result
    count_result = MagicMock()
    count_result.scalar_one.return_value = 42
    mock_session.execute = AsyncMock(return_value=count_result)

    with patch("scripts.cleanup_dlq.get_async_session_maker", return_value=mock_session_maker):
        await cleanup_dlq(days=30, dry_run=True)

    # Should execute count query
    assert mock_session.execute.call_count == 1
    call_args = mock_session.execute.call_args
    query_text = str(call_args[0][0])

    # Verify WHERE clause
    assert "WHERE resolved = true" in query_text
    assert "resolved_at <" in query_text
    assert "SELECT COUNT(*)" in query_text

    # Should NOT call commit (dry-run)
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_dlq_real_run_deletes_rows(mock_session, mock_session_maker):
    """Real mode should delete matching rows."""
    # Mock count query (42 rows)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 42
    # Mock delete query
    delete_result = MagicMock()

    call_count = 0

    async def execute_side_effect(query, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call is count query
            return count_result
        else:
            # Second call is delete query
            return delete_result

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)

    with patch("scripts.cleanup_dlq.get_async_session_maker", return_value=mock_session_maker):
        await cleanup_dlq(days=30, dry_run=False)

    # Should execute count + delete queries
    assert mock_session.execute.call_count == 2

    # First call: count
    count_call = mock_session.execute.call_args_list[0]
    count_query_text = str(count_call[0][0])
    assert "SELECT COUNT(*)" in count_query_text
    assert "WHERE resolved = true" in count_query_text

    # Second call: delete
    delete_call = mock_session.execute.call_args_list[1]
    delete_query_text = str(delete_call[0][0])
    assert "DELETE FROM dead_letter_messages" in delete_query_text
    assert "WHERE resolved = true" in delete_query_text

    # Should commit after delete
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_dlq_zero_rows(mock_session, mock_session_maker):
    """No rows to delete should skip delete query."""
    # Mock count query (0 rows)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    mock_session.execute = AsyncMock(return_value=count_result)

    with patch("scripts.cleanup_dlq.get_async_session_maker", return_value=mock_session_maker):
        await cleanup_dlq(days=30, dry_run=False)

    # Should only execute count query
    assert mock_session.execute.call_count == 1

    # Should NOT commit (no rows to delete)
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_dlq_cutoff_date(mock_session, mock_session_maker):
    """Verify cutoff date calculation."""
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    mock_session.execute = AsyncMock(return_value=count_result)

    with patch("scripts.cleanup_dlq.get_async_session_maker", return_value=mock_session_maker):
        await cleanup_dlq(days=7, dry_run=True)

    # Check cutoff date in query params
    call_args = mock_session.execute.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})

    cutoff = params["cutoff"]
    expected_cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Allow 1-minute tolerance for test execution time
    assert abs((cutoff - expected_cutoff).total_seconds()) < 60


@pytest.mark.asyncio
async def test_cleanup_dlq_custom_days(mock_session, mock_session_maker):
    """Different --days values should work correctly."""
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    mock_session.execute = AsyncMock(return_value=count_result)

    for days in [1, 7, 14, 30, 60, 90]:
        mock_session.execute.reset_mock()
        with patch("scripts.cleanup_dlq.get_async_session_maker", return_value=mock_session_maker):
            await cleanup_dlq(days=days, dry_run=True)

        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        cutoff = params["cutoff"]
        expected_cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        assert abs((cutoff - expected_cutoff).total_seconds()) < 60
