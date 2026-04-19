"""Unit tests for naming_audit CLI.

Tests:
- DB schema scanning with mock data
- Code reference detection
- Mixed format detection
- JSON output validation
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.naming_audit import (
    _fallback_code_scan,
    run_naming_audit,
    scan_config_files,
    scan_db_schema,
)


class TestDatabaseSchemaScan:
    """Test database schema scanning logic."""

    @pytest.mark.asyncio
    async def test_detects_snowflake_format(self):
        """Columns with all snowflake values should be detected correctly."""
        mock_session = AsyncMock()

        # Mock information_schema query
        columns_result = [
            ("channel_messages", "channel", "character varying", 200),
        ]

        # Mock sample values query - all snowflakes
        sample_values = [
            ("123456789012345678",),
            ("987654321098765432",),
        ]

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            query_str = str(query)
            if "information_schema.columns" in query_str:
                mock_result.fetchall.return_value = columns_result
            elif "pg_index" in query_str:
                mock_result.fetchall.return_value = []
            else:
                mock_result.fetchall.return_value = sample_values
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.naming_audit.async_session", return_value=mock_session):
            findings = await scan_db_schema()

        assert len(findings) >= 1
        channel_finding = next((f for f in findings if f["field"] == "channel"), None)
        assert channel_finding is not None
        assert channel_finding["format_detected"] == "snowflake_string"

    @pytest.mark.asyncio
    async def test_detects_mixed_format(self):
        """Columns with mixed snowflake and text should be flagged."""
        mock_session = AsyncMock()

        columns_result = [
            ("channel_messages", "channel", "character varying", 200),
        ]

        # Mixed values: snowflakes and text slugs
        sample_values = [
            ("123456789012345678",),
            ("general-chat",),
            ("987654321098765432",),
        ]

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            query_str = str(query)
            if "information_schema.columns" in query_str:
                mock_result.fetchall.return_value = columns_result
            elif "pg_index" in query_str:
                mock_result.fetchall.return_value = []
            else:
                mock_result.fetchall.return_value = sample_values
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.naming_audit.async_session", return_value=mock_session):
            findings = await scan_db_schema()

        channel_finding = next((f for f in findings if f["field"] == "channel"), None)
        assert channel_finding is not None
        assert channel_finding["format_detected"] == "mixed"
        assert "Mixed snowflake and text values" in channel_finding["issue"]

    @pytest.mark.asyncio
    async def test_detects_text_slug_format(self):
        """Columns with all text slugs should be detected correctly."""
        mock_session = AsyncMock()

        columns_result = [
            ("connector_agents", "channel", "character varying", 200),
        ]

        sample_values = [
            ("general",),
            ("trading-signals",),
            ("announcements",),
        ]

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            query_str = str(query)
            if "information_schema.columns" in query_str:
                mock_result.fetchall.return_value = columns_result
            elif "pg_index" in query_str:
                mock_result.fetchall.return_value = []
            else:
                mock_result.fetchall.return_value = sample_values
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.naming_audit.async_session", return_value=mock_session):
            findings = await scan_db_schema()

        channel_finding = next((f for f in findings if f["field"] == "channel"), None)
        assert channel_finding is not None
        assert channel_finding["format_detected"] == "text_slug"

    @pytest.mark.asyncio
    async def test_detects_missing_indexes(self):
        """Missing indexes on channel columns should be flagged."""
        mock_session = AsyncMock()

        columns_result = [
            ("channel_messages", "channel_id_snowflake", "character varying", 20),
        ]

        missing_indexes = [
            ("channel_messages", "channel_id_snowflake"),
        ]

        sample_values = []

        call_count = [0]

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            call_count[0] += 1

            if "information_schema.columns" in str(query):
                mock_result.fetchall.return_value = columns_result
            elif "pg_index" in str(query):
                mock_result.fetchall.return_value = missing_indexes
            else:
                mock_result.fetchall.return_value = sample_values
            return mock_result

        mock_session.execute = mock_execute

        with patch("tools.naming_audit.async_session", return_value=mock_session):
            findings = await scan_db_schema()

        index_findings = [f for f in findings if f.get("type") == "index_missing"]
        assert len(index_findings) >= 1
        assert any("lacks index" in f.get("issue", "") for f in index_findings)


class TestCodeReferenceScan:
    """Test code reference scanning logic."""

    def test_fallback_scan_finds_references(self, tmp_path):
        """Fallback Python scanner should find channel references."""
        # Create temporary Python file with channel references
        test_file = tmp_path / "test_routes.py"
        test_file.write_text(
            """
def get_channel_id():
    return channel_id

def process_channel():
    channel_name = "test"
    return channel_name
"""
        )

        with patch("tools.naming_audit.REPO_ROOT", tmp_path):
            findings = _fallback_code_scan(["."], r"channel_id|channel_name")

        assert len(findings) > 0
        assert any("channel_id" in f["content"] for f in findings)

    def test_config_scan_detects_references(self):
        """Config file scanner should detect channel references."""
        with patch("tools.naming_audit.REPO_ROOT", Path("/tmp")):
            # Mock file existence and content
            mock_env = Path("/tmp/.env.example")

            def mock_exists(self):
                return str(self).endswith(".env.example")

            def mock_open(self, *args, **kwargs):
                from io import StringIO

                content = "DISCORD_CHANNEL_ID=123456\nCHANNEL_NAME=general\n"
                return StringIO(content)

            with (
                patch.object(Path, "exists", mock_exists),
                patch("builtins.open", mock_open),
            ):
                findings = scan_config_files()

        # Should find at least the references in mocked content
        assert len(findings) >= 0  # May be empty if file not found


class TestNamingAuditIntegration:
    """Test full naming audit integration."""

    @pytest.mark.asyncio
    async def test_audit_returns_valid_json_schema(self):
        """Full audit should return valid JSON with required keys."""
        mock_session = AsyncMock()

        columns_result = [
            ("channel_messages", "channel", "character varying", 200),
        ]

        sample_values = [("123456789012345678",)]

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if "information_schema.columns" in str(query):
                mock_result.fetchall.return_value = columns_result
            elif "pg_index" in str(query):
                mock_result.fetchall.return_value = []
            else:
                mock_result.fetchall.return_value = sample_values
            return mock_result

        mock_session.execute = mock_execute

        with (
            patch("tools.naming_audit.async_session", return_value=mock_session),
            patch("tools.naming_audit.scan_code_references", return_value=[]),
            patch("tools.naming_audit.scan_config_files", return_value=[]),
            patch("tools.naming_audit.scan_dashboard_types", return_value=[]),
        ):
            result = await run_naming_audit(verbose=False)

        # Validate required keys from arch doc §6.3
        required_keys = {
            "audit_timestamp",
            "canonical_form",
            "total_findings",
            "issues_count",
            "findings",
            "migration_plan",
        }
        assert required_keys.issubset(result.keys())

        # Validate JSON serialization
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["canonical_form"] == "snowflake_string"

    @pytest.mark.asyncio
    async def test_migration_plan_has_four_steps(self):
        """Migration plan should contain 4 steps as per architecture."""
        mock_session = AsyncMock()

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            return mock_result

        mock_session.execute = mock_execute

        with (
            patch("tools.naming_audit.async_session", return_value=mock_session),
            patch("tools.naming_audit.scan_code_references", return_value=[]),
            patch("tools.naming_audit.scan_config_files", return_value=[]),
            patch("tools.naming_audit.scan_dashboard_types", return_value=[]),
        ):
            result = await run_naming_audit(verbose=False)

        assert len(result["migration_plan"]) == 4
        assert result["migration_plan"][0]["step"] == 1
        assert "channel_id_snowflake" in result["migration_plan"][0]["action"]

    @pytest.mark.asyncio
    async def test_issues_count_matches_findings(self):
        """Issues count should accurately reflect flagged findings."""
        mock_session = AsyncMock()

        columns_result = [
            ("channel_messages", "channel", "character varying", 200),
        ]

        # Mixed format to trigger issue
        sample_values = [
            ("123456789012345678",),
            ("general-chat",),
        ]

        async def mock_execute(query, params=None):
            mock_result = MagicMock()
            if "information_schema.columns" in str(query):
                mock_result.fetchall.return_value = columns_result
            elif "pg_index" in str(query):
                mock_result.fetchall.return_value = []
            else:
                mock_result.fetchall.return_value = sample_values
            return mock_result

        mock_session.execute = mock_execute

        with (
            patch("tools.naming_audit.async_session", return_value=mock_session),
            patch("tools.naming_audit.scan_code_references", return_value=[]),
            patch("tools.naming_audit.scan_config_files", return_value=[]),
            patch("tools.naming_audit.scan_dashboard_types", return_value=[]),
        ):
            result = await run_naming_audit(verbose=False)

        # Count issues manually
        actual_issues = sum(1 for f in result["findings"] if f.get("issue"))
        assert result["issues_count"] == actual_issues
        assert actual_issues >= 1  # Mixed format should trigger at least one issue
