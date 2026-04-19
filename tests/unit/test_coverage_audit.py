"""Unit tests for coverage_audit CLI.

Tests:
- Pass/fail logic with known counts and dates
- JSON schema validation
- Multiple channels handling
- Edge cases (no messages, partial coverage)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.coverage_audit import run_coverage_audit


class TestCoverageAuditLogic:
    """Test core audit logic with mocked DB."""

    @pytest.mark.asyncio
    async def test_all_channels_pass(self):
        """Channels with sufficient history and messages should pass."""
        # Mock DB session
        mock_session = AsyncMock()

        # Connector query result
        connector_row = (
            "conn-uuid-1",
            "test-connector",
            {"channel_ids": ["123456789012345678"]},
        )

        # Message stats: 2+ years, 200 messages
        now = datetime.now(timezone.utc)
        earliest = now - timedelta(days=800)
        latest = now

        message_row = (200, earliest, latest)

        # Setup mock execute to return appropriate results
        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if params and "cid" in params:
                # Channel message query
                mock_result.fetchone.return_value = message_row
            else:
                # Connector query
                mock_result.fetchall.return_value = [connector_row]
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.coverage_audit.async_session", return_value=mock_session):
            result = await run_coverage_audit(min_months=24, min_messages=100)

        assert result["channels_total"] == 1
        assert result["channels_pass"] == 1
        assert result["channels_fail"] == 0
        assert len(result["passes"]) == 1
        assert len(result["failures"]) == 0

        # Validate pass record structure
        pass_record = result["passes"][0]
        assert pass_record["connector_id"] == "conn-uuid-1"
        assert pass_record["channel_id"] == "123456789012345678"
        assert pass_record["message_count"] == 200
        assert pass_record["date_range_days"] == 800

    @pytest.mark.asyncio
    async def test_insufficient_history_fails(self):
        """Channel with less than required months should fail."""
        mock_session = AsyncMock()

        connector_row = (
            "conn-uuid-1",
            "test-connector",
            {"channel_ids": ["123456789012345678"]},
        )

        # Only 6 months of history
        now = datetime.now(timezone.utc)
        earliest = now - timedelta(days=180)
        latest = now

        message_row = (500, earliest, latest)  # Enough messages, but short history

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if params and "cid" in params:
                mock_result.fetchone.return_value = message_row
            else:
                mock_result.fetchall.return_value = [connector_row]
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.coverage_audit.async_session", return_value=mock_session):
            result = await run_coverage_audit(min_months=24, min_messages=100)

        assert result["channels_fail"] == 1
        assert len(result["failures"]) == 1

        failure = result["failures"][0]
        assert "Insufficient history" in failure["reason"]
        assert failure["date_range_days"] == 180
        assert "recommended_backfill" in failure
        assert "python -m tools.backfill" in failure["recommended_backfill"]

    @pytest.mark.asyncio
    async def test_insufficient_messages_fails(self):
        """Channel with less than required messages should fail."""
        mock_session = AsyncMock()

        connector_row = (
            "conn-uuid-1",
            "test-connector",
            {"channel_ids": ["123456789012345678"]},
        )

        # Long history but few messages
        now = datetime.now(timezone.utc)
        earliest = now - timedelta(days=800)
        latest = now

        message_row = (50, earliest, latest)  # Only 50 messages

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if params and "cid" in params:
                mock_result.fetchone.return_value = message_row
            else:
                mock_result.fetchall.return_value = [connector_row]
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.coverage_audit.async_session", return_value=mock_session):
            result = await run_coverage_audit(min_months=24, min_messages=100)

        assert result["channels_fail"] == 1
        failure = result["failures"][0]
        assert "Insufficient messages" in failure["reason"]
        assert failure["message_count"] == 50

    @pytest.mark.asyncio
    async def test_no_messages_fails(self):
        """Channel with zero messages should fail with specific reason."""
        mock_session = AsyncMock()

        connector_row = (
            "conn-uuid-1",
            "test-connector",
            {"channel_ids": ["123456789012345678"]},
        )

        message_row = (0, None, None)

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if params and "cid" in params:
                mock_result.fetchone.return_value = message_row
            else:
                mock_result.fetchall.return_value = [connector_row]
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.coverage_audit.async_session", return_value=mock_session):
            result = await run_coverage_audit(min_months=24, min_messages=100)

        assert result["channels_fail"] == 1
        failure = result["failures"][0]
        assert failure["reason"] == "No messages found in database"
        assert failure["message_count"] == 0

    @pytest.mark.asyncio
    async def test_multiple_channels_mixed_results(self):
        """Test audit with multiple channels having different outcomes."""
        mock_session = AsyncMock()

        connector_row = (
            "conn-uuid-1",
            "test-connector",
            {"channel_ids": ["111111111111111111", "222222222222222222"]},
        )

        now = datetime.now(timezone.utc)

        # Channel 1: passes
        ch1_row = (300, now - timedelta(days=800), now)
        # Channel 2: fails (insufficient history)
        ch2_row = (200, now - timedelta(days=100), now)

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if params and "cid" in params:
                if params["ch_id"] == "111111111111111111":
                    mock_result.fetchone.return_value = ch1_row
                else:
                    mock_result.fetchone.return_value = ch2_row
            else:
                mock_result.fetchall.return_value = [connector_row]
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.coverage_audit.async_session", return_value=mock_session):
            result = await run_coverage_audit(min_months=24, min_messages=100)

        assert result["channels_total"] == 2
        assert result["channels_pass"] == 1
        assert result["channels_fail"] == 1

    @pytest.mark.asyncio
    async def test_json_schema_required_keys(self):
        """Validate that result JSON contains all required keys."""
        mock_session = AsyncMock()

        connector_row = (
            "conn-uuid-1",
            "test-connector",
            {"channel_ids": ["123456789012345678"]},
        )

        now = datetime.now(timezone.utc)
        message_row = (200, now - timedelta(days=800), now)

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if params and "cid" in params:
                mock_result.fetchone.return_value = message_row
            else:
                mock_result.fetchall.return_value = [connector_row]
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.coverage_audit.async_session", return_value=mock_session):
            result = await run_coverage_audit(min_months=24, min_messages=100)

        # Required top-level keys from architecture doc §5.2
        required_keys = {
            "audit_timestamp",
            "threshold_months",
            "channels_total",
            "channels_pass",
            "channels_fail",
            "failures",
            "passes",
        }
        assert required_keys.issubset(result.keys())

        # Validate JSON serialization
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["channels_total"] == 1

    @pytest.mark.asyncio
    async def test_no_connectors_returns_empty(self):
        """No active Discord connectors should return empty results."""
        mock_session = AsyncMock()

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.coverage_audit.async_session", return_value=mock_session):
            result = await run_coverage_audit()

        assert result["channels_total"] == 0
        assert result["channels_pass"] == 0
        assert result["channels_fail"] == 0
        assert result["failures"] == []
        assert result["passes"] == []

    @pytest.mark.asyncio
    async def test_exact_threshold_values_pass(self):
        """Channels at exactly threshold values should pass."""
        mock_session = AsyncMock()

        connector_row = (
            "conn-uuid-1",
            "test-connector",
            {"channel_ids": ["123456789012345678"]},
        )

        now = datetime.now(timezone.utc)
        # Exactly 24 months (720 days) and exactly 100 messages
        earliest = now - timedelta(days=720)
        message_row = (100, earliest, now)

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if params and "cid" in params:
                mock_result.fetchone.return_value = message_row
            else:
                mock_result.fetchall.return_value = [connector_row]
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.coverage_audit.async_session", return_value=mock_session):
            result = await run_coverage_audit(min_months=24, min_messages=100)

        assert result["channels_pass"] == 1
        assert result["channels_fail"] == 0
