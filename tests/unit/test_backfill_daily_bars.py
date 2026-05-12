"""Unit tests for backfill_daily_bars.py script."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts to path for import
scripts_path = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(scripts_path))

from backfill_daily_bars import CONTEXT_TICKERS, build_ticker_list, get_database_url  # noqa: E402


def test_context_tickers_defined():
    """Test that context tickers list is defined and has expected symbols."""
    assert len(CONTEXT_TICKERS) > 0
    assert "SPY" in CONTEXT_TICKERS
    assert "QQQ" in CONTEXT_TICKERS
    assert "^VIX" in CONTEXT_TICKERS
    assert "GLD" in CONTEXT_TICKERS


def test_build_ticker_list_deduplicates():
    """Test that build_ticker_list deduplicates and includes both sources."""
    parsed = ["AAPL", "TSLA", "SPY"]
    result = build_ticker_list(parsed)

    # Should include both parsed and context tickers
    assert "AAPL" in result
    assert "TSLA" in result
    assert "SPY" in result
    assert "QQQ" in result

    # Should be deduplicated (SPY appears in both lists)
    assert result.count("SPY") == 1

    # Should be sorted
    assert result == sorted(result)


def test_build_ticker_list_empty_parsed():
    """Test build_ticker_list with no parsed tickers."""
    result = build_ticker_list([])

    # Should still have context tickers
    assert len(result) == len(CONTEXT_TICKERS)
    assert "SPY" in result


def test_build_ticker_list_preserves_special_chars():
    """Test that special characters in tickers are preserved."""
    parsed = ["AAPL", "ES=F", "^GSPC"]
    result = build_ticker_list(parsed)

    assert "ES=F" in result
    assert "^GSPC" in result
    assert "^VIX" in result


def test_get_database_url_missing_env(monkeypatch):
    """Test that get_database_url exits when DATABASE_URL is not set."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        get_database_url()

    assert exc_info.value.code == 1


def test_get_database_url_strips_asyncpg(monkeypatch):
    """Test that get_database_url strips +asyncpg dialect."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db")
    result = get_database_url()

    assert result == "postgresql://user:pass@localhost:5432/db"
    assert "+asyncpg" not in result


def test_get_database_url_preserves_plain_url(monkeypatch):
    """Test that plain postgresql:// URLs are preserved."""
    url = "postgresql://user:pass@localhost:5432/db"
    monkeypatch.setenv("DATABASE_URL", url)
    result = get_database_url()

    assert result == url
