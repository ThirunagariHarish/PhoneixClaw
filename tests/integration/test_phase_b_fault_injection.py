"""Integration tests for Phase B: Agent Wake-on-Discord Flow Hardening (Fault Injection).

Covers B-GAP-03 (correlation ID), B-GAP-04 (DLQ writes), B-GAP-05 (circuit breakers).
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.utils.circuit_breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_parse_signal_failure_writes_dlq():
    """B-GAP-04: parse_signal failure writes DLQ row."""
    from sqlalchemy import text
    from shared.db.engine import get_session

    connector_id = str(uuid.uuid4())
    signal = {"content": "INVALID_SIGNAL", "correlation_id": str(uuid.uuid4())}
    temp_dir = Path("/tmp/test_parse_signal_dlq")
    temp_dir.mkdir(parents=True, exist_ok=True)

    signal_path = temp_dir / "signal.json"
    config_path = temp_dir / "config.json"
    signal_path.write_text(json.dumps(signal))
    config_path.write_text(json.dumps({"connector_id": connector_id}))

    with patch("shared.utils.signal_parser.parse_signal_compat") as mock_parse:
        mock_parse.side_effect = ValueError("Test parse failure")

        import subprocess
        result = subprocess.run(
            ["python3", "agents/templates/live-trader-v1/tools/parse_signal.py",
             "--input", str(signal_path), "--config", str(config_path)],
            capture_output=True,
            text=True,
        )

    assert result.returncode == 1

    async for session in get_session():
        row = (await session.execute(
            text("SELECT * FROM dead_letter_messages WHERE connector_id = :cid ORDER BY created_at DESC LIMIT 1"),
            {"cid": connector_id},
        )).fetchone()

        assert row is not None, "DLQ row not written"
        assert "Test parse failure" in row[3]
        break


@pytest.mark.asyncio
async def test_yfinance_timeout_trips_circuit_breaker():
    """B-GAP-05: yfinance timeout 5x trips circuit breaker to OPEN."""
    breaker = CircuitBreaker("test_yfinance", failure_threshold=5, cooldown_seconds=60)

    for i in range(5):
        try:
            async with breaker:
                raise TimeoutError(f"yfinance timeout {i}")
        except TimeoutError:
            pass

    assert breaker.state == "open"
    assert breaker.status()["total_failures"] == 5


@pytest.mark.asyncio
async def test_robinhood_failure_writes_dlq():
    """B-GAP-05: Robinhood MCP down writes DLQ row."""
    from sqlalchemy import text
    from shared.db.engine import get_session

    connector_id = str(uuid.uuid4())
    decision = {"decision": "EXECUTE", "execution": {"ticker": "SPY"}, "correlation_id": str(uuid.uuid4())}
    config = {"connector_id": connector_id, "agent_id": str(uuid.uuid4())}

    temp_dir = Path("/tmp/test_robinhood_dlq")
    temp_dir.mkdir(parents=True, exist_ok=True)
    decision_path = temp_dir / "decision.json"
    config_path = temp_dir / "config.json"
    decision_path.write_text(json.dumps(decision))
    config_path.write_text(json.dumps(config))

    with patch("agents.templates.live-trader-v1.tools.robinhood_mcp_client.RobinhoodMCPClient") as mock_mcp:
        mock_client = MagicMock()
        mock_client.call.side_effect = ConnectionError("MCP server unreachable")
        mock_mcp.return_value = mock_client

        import subprocess
        result = subprocess.run(
            ["python3", "agents/templates/live-trader-v1/tools/execute_trade.py",
             "--decision", str(decision_path), "--config", str(config_path)],
            capture_output=True,
            text=True,
        )

    assert result.returncode == 1

    async for session in get_session():
        row = (await session.execute(
            text("SELECT * FROM dead_letter_messages WHERE connector_id = :cid ORDER BY created_at DESC LIMIT 1"),
            {"cid": connector_id},
        )).fetchone()

        assert row is not None, "DLQ row not written for MCP failure"
        break


@pytest.mark.asyncio
async def test_correlation_id_propagates_end_to_end():
    """B-GAP-03: correlation_id propagates from ingestion to all tool logs."""
    correlation_id = str(uuid.uuid4())
    connector_id = str(uuid.uuid4())

    temp_dir = Path("/tmp/test_correlation_id")
    temp_dir.mkdir(parents=True, exist_ok=True)

    signal = {
        "content": "BTO $SPY 500c 4/30",
        "author": "test",
        "correlation_id": correlation_id,
        "ticker": "SPY",
        "direction": "buy",
    }

    signal_path = temp_dir / "signal.json"
    config_path = temp_dir / "config.json"
    signal_path.write_text(json.dumps(signal))
    config_path.write_text(json.dumps({"connector_id": connector_id}))

    import subprocess
    result = subprocess.run(
        ["python3", "agents/templates/live-trader-v1/tools/parse_signal.py",
         "--input", str(signal_path), "--config", str(config_path)],
        capture_output=True,
        text=True,
        env={"CORRELATION_ID": correlation_id},
    )

    assert result.returncode == 0
    output = Path("parsed_signal.json").read_text()
    parsed = json.loads(output)
    assert parsed.get("correlation_id") == correlation_id, "correlation_id not propagated to parse_signal output"
