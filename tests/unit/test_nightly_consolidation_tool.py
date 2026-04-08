"""Unit tests for nightly_consolidation.py CLI tool (no network / no DB required)."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load the tool module without triggering the full agent PYTHONPATH
# ---------------------------------------------------------------------------

_TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "agents/templates/live-trader-v1/tools/nightly_consolidation.py"
)


def _load_tool():
    spec = importlib.util.spec_from_file_location("nightly_consolidation", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _load_tool()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_CONFIG = {
    "agent_id": str(uuid.uuid4()),
    "phoenix_api_url": "http://localhost:8011",
    "phoenix_api_key": "test-key",
}

_COMPLETED_RUN = {
    "id": str(uuid.uuid4()),
    "status": "completed",
    "trades_analyzed": 14,
    "patterns_found": 3,
    "wiki_entries_written": 2,
    "wiki_entries_updated": 1,
    "wiki_entries_pruned": 0,
    "rules_proposed": 1,
    "consolidation_report": "# Report\nAll good.",
    "error_message": None,
}

_PENDING_RUN = dict(_COMPLETED_RUN, status="pending")
_FAILED_RUN = dict(_COMPLETED_RUN, status="failed", error_message="out of memory")


# ---------------------------------------------------------------------------
# dry-run: should return 0 and print without hitting the network
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_returns_zero(tmp_path, capsys):
    """--dry-run should exit 0 without any HTTP requests."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(_SAMPLE_CONFIG))

    with patch.object(tool, "_load_config", return_value=_SAMPLE_CONFIG):
        exit_code = await tool._cli_main(dry_run=True)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()
    assert _SAMPLE_CONFIG["agent_id"] in out


# ---------------------------------------------------------------------------
# happy path: trigger → one pending poll → completed poll
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_completes(capsys):
    """Full successful run: trigger + 1 pending poll + 1 completed poll → exit 0."""
    pending_resp = dict(_PENDING_RUN)
    completed_resp = dict(_COMPLETED_RUN)

    with (
        patch.object(tool, "_load_config", return_value=_SAMPLE_CONFIG),
        patch.object(tool, "trigger_consolidation", new=AsyncMock(return_value=pending_resp)),
        patch.object(
            tool,
            "get_consolidation_status",
            new=AsyncMock(side_effect=[pending_resp, completed_resp]),
        ),
        patch("asyncio.sleep", new=AsyncMock()),  # skip actual sleeps
    ):
        exit_code = await tool._cli_main(dry_run=False)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "# Report" in out
    assert "14 trades" in out


# ---------------------------------------------------------------------------
# failed run: trigger succeeds but run ends in failed → exit 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_run_returns_2(capsys):
    """If the consolidation run ends with status=failed, exit code is 2."""
    pending_resp = dict(_PENDING_RUN)

    with (
        patch.object(tool, "_load_config", return_value=_SAMPLE_CONFIG),
        patch.object(tool, "trigger_consolidation", new=AsyncMock(return_value=pending_resp)),
        patch.object(
            tool,
            "get_consolidation_status",
            new=AsyncMock(return_value=_FAILED_RUN),
        ),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        exit_code = await tool._cli_main(dry_run=False)

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "failed" in err.lower() or "out of memory" in err.lower()


# ---------------------------------------------------------------------------
# missing config.json → exit 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_config_returns_2(capsys):
    """If config.json cannot be found, exit code is 2."""
    with patch.object(tool, "_load_config", side_effect=FileNotFoundError("config.json not found")):
        exit_code = await tool._cli_main(dry_run=False)

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "ERROR" in err


# ---------------------------------------------------------------------------
# config missing agent_id → exit 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_missing_agent_id_returns_2(capsys):
    """If config.json has no agent_id, exit code is 2 with a descriptive error."""
    bad_config = {"phoenix_api_url": "http://localhost:8011"}
    with patch.object(tool, "_load_config", return_value=bad_config):
        exit_code = await tool._cli_main(dry_run=False)

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "agent_id" in err


# ---------------------------------------------------------------------------
# trigger HTTP error → exit 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_http_error_returns_2(capsys):
    """If POST /consolidation/run raises, exit code is 2."""
    with (
        patch.object(tool, "_load_config", return_value=_SAMPLE_CONFIG),
        patch.object(
            tool,
            "trigger_consolidation",
            new=AsyncMock(side_effect=RuntimeError("connection refused")),
        ),
    ):
        exit_code = await tool._cli_main(dry_run=False)

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "ERROR" in err
