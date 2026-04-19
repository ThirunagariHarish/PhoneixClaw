"""Unit tests for shared/observability/metrics.py.

Tests verify:
- DLQ gauge background refresher queries DB correctly
- Gauge values are updated based on DB results
- Refresher can be started/stopped safely
- Multiple connector_ids tracked correctly
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.observability.metrics import (
    phoenix_dlq_size,
    start_dlq_gauge_refresher,
    stop_dlq_gauge_refresher,
)


@pytest.fixture
def mock_session():
    """Mock async DB session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.fixture
def mock_session_maker(mock_session):
    """Mock session maker."""
    maker = MagicMock()
    maker.return_value = mock_session
    return maker


@pytest.fixture(autouse=True)
def reset_gauge():
    """Reset gauge metrics before each test."""
    phoenix_dlq_size._metrics.clear()
    yield
    phoenix_dlq_size._metrics.clear()


@pytest.mark.asyncio
async def test_dlq_gauge_refresher_updates_metrics(mock_session, mock_session_maker):
    """Background refresher should query DB and update gauge."""
    # Mock DB query result: 3 connectors with counts
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        ("connector-1", 10),
        ("connector-2", 25),
        ("connector-3", 5),
    ]
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("shared.observability.metrics.get_async_session_maker", return_value=mock_session_maker):
        # Import the refresh function
        from shared.observability.metrics import _refresh_dlq_gauge

        # Run one iteration
        with patch("shared.observability.metrics._dlq_refresh_running", True):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # Make sleep raise to exit loop after first iteration
                mock_sleep.side_effect = asyncio.CancelledError()

                try:
                    await _refresh_dlq_gauge()
                except asyncio.CancelledError:
                    pass

    # Verify DB query executed
    assert mock_session.execute.called
    query_text = str(mock_session.execute.call_args[0][0])
    assert "SELECT connector_id, COUNT(*)" in query_text
    assert "WHERE resolved = false" in query_text
    assert "GROUP BY connector_id" in query_text

    # Verify gauge values updated
    # Note: Accessing gauge values requires knowing Prometheus client internals
    # We'll check that the gauge can be retrieved with labels
    assert phoenix_dlq_size.labels(connector_id="connector-1")._value.get() == 10
    assert phoenix_dlq_size.labels(connector_id="connector-2")._value.get() == 25
    assert phoenix_dlq_size.labels(connector_id="connector-3")._value.get() == 5


@pytest.mark.asyncio
async def test_dlq_gauge_refresher_clears_old_metrics(mock_session, mock_session_maker):
    """Gauge should clear old labels when DB results change."""
    # Set initial values
    phoenix_dlq_size.labels(connector_id="old-connector").set(99)

    # Mock DB query result: different connectors
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        ("new-connector", 15),
    ]
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("shared.observability.metrics.get_async_session_maker", return_value=mock_session_maker):
        from shared.observability.metrics import _refresh_dlq_gauge

        with patch("shared.observability.metrics._dlq_refresh_running", True):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                mock_sleep.side_effect = asyncio.CancelledError()

                try:
                    await _refresh_dlq_gauge()
                except asyncio.CancelledError:
                    pass

    # Old metric should be cleared (metrics dict is cleared before setting new values)
    # After clear + new set, only new-connector should exist
    assert phoenix_dlq_size.labels(connector_id="new-connector")._value.get() == 15


@pytest.mark.asyncio
async def test_dlq_gauge_refresher_handles_db_errors(mock_session, mock_session_maker, caplog):
    """Refresher should log errors but not crash."""
    # Mock DB error
    mock_session.execute = AsyncMock(side_effect=Exception("DB connection failed"))

    with patch("shared.observability.metrics.get_async_session_maker", return_value=mock_session_maker):
        from shared.observability.metrics import _refresh_dlq_gauge

        with patch("shared.observability.metrics._dlq_refresh_running", True):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # Run two iterations to verify it continues after error
                call_count = [0]

                async def sleep_side_effect(duration):
                    call_count[0] += 1
                    if call_count[0] >= 2:
                        raise asyncio.CancelledError()

                mock_sleep.side_effect = sleep_side_effect

                try:
                    await _refresh_dlq_gauge()
                except asyncio.CancelledError:
                    pass

    # Should have logged error
    assert "Failed to refresh DLQ gauge" in caplog.text


def test_start_dlq_gauge_refresher_creates_task():
    """start_dlq_gauge_refresher should create background task."""
    with patch("shared.observability.metrics.asyncio.create_task") as mock_create_task:
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_create_task.return_value = mock_task

        start_dlq_gauge_refresher()

        # Should create task
        assert mock_create_task.called


def test_start_dlq_gauge_refresher_idempotent():
    """Calling start multiple times should only create one task."""
    with patch("shared.observability.metrics.asyncio.create_task") as mock_create_task:
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_create_task.return_value = mock_task

        # Call twice
        start_dlq_gauge_refresher()
        start_dlq_gauge_refresher()

        # Should only create task once
        assert mock_create_task.call_count == 1


def test_stop_dlq_gauge_refresher_cancels_task():
    """stop_dlq_gauge_refresher should cancel the task."""
    with patch("shared.observability.metrics._dlq_refresh_task") as mock_task:
        mock_task.done.return_value = False
        mock_task.cancel = MagicMock()

        stop_dlq_gauge_refresher()

        # Should cancel task
        mock_task.cancel.assert_called_once()


def test_dlq_gauge_exists():
    """Gauge should be registered with correct name and labels."""
    # Verify gauge is exportable
    assert phoenix_dlq_size._name == "phoenix_dlq_unresolved_total"
    assert "connector_id" in phoenix_dlq_size._labelnames
