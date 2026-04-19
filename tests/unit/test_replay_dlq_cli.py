"""Unit tests for replay_dlq CLI script."""

import subprocess
import sys
from pathlib import Path


def test_replay_dlq_help():
    """CLI --help flag works."""
    result = subprocess.run(
        [sys.executable, "scripts/replay_dlq.py", "--help"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0
    assert "Batch replay DLQ messages" in result.stdout
    assert "--connector-id" in result.stdout
    assert "--limit" in result.stdout


def test_replay_dlq_missing_connector_id():
    """CLI fails without --connector-id."""
    result = subprocess.run(
        [sys.executable, "scripts/replay_dlq.py"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode != 0
    assert "required" in result.stderr.lower() or "error" in result.stderr.lower()
