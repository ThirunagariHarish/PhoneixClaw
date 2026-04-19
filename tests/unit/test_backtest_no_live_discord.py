"""Static analysis test: backtesting tools must not call Discord API.

Enforces Phase C.4 requirement: no live Discord API calls in backtest pipeline.
Uses ripgrep to assert zero matches for Discord API patterns.
"""

import subprocess
from pathlib import Path

import pytest


def test_no_discord_api_in_backtest_tools():
    """Backtest tools must not contain Discord API URLs or httpx Discord calls."""
    # Get project root (3 levels up from this test file)
    project_root = Path(__file__).parent.parent.parent

    backtest_tools_dir = project_root / "agents" / "backtesting" / "tools"

    if not backtest_tools_dir.exists():
        pytest.skip(f"Backtest tools directory not found: {backtest_tools_dir}")

    # Pattern matches:
    # - discord.com/api (Discord API URL)
    # - httpx.*discord (httpx calls to Discord)
    # Use grep with -E for extended regex (works on all systems)
    pattern = r"discord\.com/api|httpx.*discord"

    # Try rg first, fall back to grep
    try:
        result = subprocess.run(
            ["rg", pattern, str(backtest_tools_dir), "--type", "py"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        # Fallback to grep
        result = subprocess.run(
            ["grep", "-r", "-E", pattern, str(backtest_tools_dir), "--include=*.py"],
            capture_output=True,
            text=True,
        )

    # Exit code 1 means no matches (success for both rg and grep)
    # Exit code 0 means matches found (failure)
    # Exit code 2+ means error
    if result.returncode == 0:
        pytest.fail(
            f"Found Discord API calls in backtest tools (forbidden in Phase C.4):\n{result.stdout}"
        )
    elif result.returncode >= 2:
        pytest.fail(f"grep/rg error: {result.stderr}")

    # returncode == 1 means no matches — test passes
    assert result.returncode == 1, "Expected no Discord API calls in backtest tools"


def test_transform_raises_on_discord_source():
    """transform.py --source discord must raise ValueError."""
    project_root = Path(__file__).parent.parent.parent
    transform_py = project_root / "agents" / "backtesting" / "tools" / "transform.py"

    if not transform_py.exists():
        pytest.skip(f"transform.py not found: {transform_py}")

    # Read file and check for the ValueError
    content = transform_py.read_text()

    # Should contain the deprecation error
    assert 'raise ValueError(' in content and 'deprecated' in content and 'backfill' in content, \
        "transform.py must raise ValueError when --source discord is used"

    # Should NOT contain fetch_discord_history function definition
    assert 'async def fetch_discord_history' not in content, \
        "fetch_discord_history function should be removed in Phase C.4"
