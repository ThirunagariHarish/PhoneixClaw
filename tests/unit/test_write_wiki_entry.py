"""Unit tests for agents/templates/live-trader-v1/tools/write_wiki_entry.py

Tests cover:
- DEFAULT_CONFIDENCE values per category
- _SHARED_BY_DEFAULT membership
- _get_api_url() env-var override and config fallback
- _get_api_token() priority: config -> env -> empty
- CLI validation: title-too-long -> exit 1
- CLI validation: confidence out of range -> exit 1
- CLI --dry-run: correct JSON output, no HTTP call
- CLI API error: non-fatal, exit 2, warns to stderr
- CLI success path: prints expected line, exit 0
- --is-shared flag overrides category default
- write_wiki_entry() async helper builds correct payload and uses Bearer auth
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Make the tools directory importable without installing the package
# ---------------------------------------------------------------------------
TOOL_DIR = Path(__file__).parent.parent.parent / "agents" / "templates" / "live-trader-v1" / "tools"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import write_wiki_entry as wwe  # noqa: E402

SCRIPT = str(TOOL_DIR / "write_wiki_entry.py")
PYTHON = sys.executable

# ---------------------------------------------------------------------------
# Shared config fixture
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "phoenix_api_url": "http://test-phoenix:8011",
    "agent_id": "agent-uuid-123",
    "api_token": "test-bearer-token",
}


# ---------------------------------------------------------------------------
# Helper: build a mock httpx async client that returns a canned response
# ---------------------------------------------------------------------------

def _mock_httpx_client(status_code: int = 201, body: dict | None = None) -> MagicMock:
    if body is None:
        body = {"id": "entry-uuid-001", "category": "MISTAKES"}

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}", request=MagicMock(), response=mock_resp
        )
    mock_resp.json.return_value = body

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.get = AsyncMock(return_value=mock_resp)

    return mock_client


# ===========================================================================
# 1. Constants
# ===========================================================================

class TestConstants:
    def test_all_eight_categories_present(self):
        expected = {
            "MARKET_PATTERNS", "SYMBOL_PROFILES", "STRATEGY_LEARNINGS",
            "MISTAKES", "WINNING_CONDITIONS", "SECTOR_NOTES",
            "MACRO_CONTEXT", "TRADE_OBSERVATION",
        }
        assert wwe.VALID_CATEGORIES == expected

    def test_default_confidence_trade_observation(self):
        assert wwe.DEFAULT_CONFIDENCE["TRADE_OBSERVATION"] == pytest.approx(0.5)

    def test_default_confidence_mistakes(self):
        assert wwe.DEFAULT_CONFIDENCE["MISTAKES"] == pytest.approx(0.85)

    def test_default_confidence_winning_conditions(self):
        assert wwe.DEFAULT_CONFIDENCE["WINNING_CONDITIONS"] == pytest.approx(0.75)

    def test_default_confidence_market_patterns(self):
        assert wwe.DEFAULT_CONFIDENCE["MARKET_PATTERNS"] == pytest.approx(0.65)

    def test_default_confidence_strategy_learnings(self):
        assert wwe.DEFAULT_CONFIDENCE["STRATEGY_LEARNINGS"] == pytest.approx(0.70)

    def test_default_confidence_symbol_profiles(self):
        assert wwe.DEFAULT_CONFIDENCE["SYMBOL_PROFILES"] == pytest.approx(0.60)

    def test_default_confidence_sector_notes(self):
        assert wwe.DEFAULT_CONFIDENCE["SECTOR_NOTES"] == pytest.approx(0.55)

    def test_default_confidence_macro_context(self):
        assert wwe.DEFAULT_CONFIDENCE["MACRO_CONTEXT"] == pytest.approx(0.55)

    def test_mistakes_not_shared_by_default(self):
        assert "MISTAKES" not in wwe._SHARED_BY_DEFAULT

    def test_trade_observation_not_shared_by_default(self):
        assert "TRADE_OBSERVATION" not in wwe._SHARED_BY_DEFAULT

    def test_market_patterns_shared_by_default(self):
        assert "MARKET_PATTERNS" in wwe._SHARED_BY_DEFAULT

    def test_winning_conditions_shared_by_default(self):
        assert "WINNING_CONDITIONS" in wwe._SHARED_BY_DEFAULT

    def test_strategy_learnings_shared_by_default(self):
        assert "STRATEGY_LEARNINGS" in wwe._SHARED_BY_DEFAULT


# ===========================================================================
# 2. _get_api_url
# ===========================================================================

class TestGetApiUrl:
    def test_env_var_overrides_config(self, monkeypatch):
        monkeypatch.setenv("PHOENIX_API_URL", "http://override:9999")
        assert wwe._get_api_url({"phoenix_api_url": "http://config:8011"}) == "http://override:9999"

    def test_config_used_when_no_env(self, monkeypatch):
        monkeypatch.delenv("PHOENIX_API_URL", raising=False)
        assert wwe._get_api_url({"phoenix_api_url": "http://config:8011"}) == "http://config:8011"

    def test_default_localhost_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("PHOENIX_API_URL", raising=False)
        assert wwe._get_api_url({}) == "http://localhost:8011"


# ===========================================================================
# 3. _get_api_token
# ===========================================================================

class TestGetApiToken:
    def test_config_token_takes_priority_over_env(self, monkeypatch):
        monkeypatch.setenv("PHOENIX_API_TOKEN", "env-token")
        assert wwe._get_api_token({"api_token": "config-token"}) == "config-token"

    def test_env_token_used_when_no_config_token(self, monkeypatch):
        monkeypatch.setenv("PHOENIX_API_TOKEN", "env-token")
        assert wwe._get_api_token({}) == "env-token"

    def test_empty_string_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("PHOENIX_API_TOKEN", raising=False)
        assert wwe._get_api_token({}) == ""


# ===========================================================================
# 4. CLI Validation (subprocess)
# ===========================================================================

class TestCLIValidation:
    def test_title_too_long_exits_1(self):
        long = "x" * 256
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES", "--title", long, "--content", "test"],
            capture_output=True, text=True,
        )
        assert r.returncode == 1
        assert "255" in r.stderr

    def test_confidence_above_1_exits_1(self):
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES", "--title", "T", "--content", "C",
             "--confidence", "1.5"],
            capture_output=True, text=True,
        )
        assert r.returncode == 1

    def test_confidence_below_0_exits_1(self):
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES", "--title", "T", "--content", "C",
             "--confidence", "-0.1"],
            capture_output=True, text=True,
        )
        assert r.returncode == 1

    def test_invalid_category_exits_nonzero(self):
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "BOGUS", "--title", "T", "--content", "C"],
            capture_output=True, text=True,
        )
        assert r.returncode != 0

    def test_missing_title_exits_nonzero(self):
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES", "--content", "C"],
            capture_output=True, text=True,
        )
        assert r.returncode != 0

    def test_missing_content_exits_nonzero(self):
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES", "--title", "T"],
            capture_output=True, text=True,
        )
        assert r.returncode != 0


# ===========================================================================
# 5. --dry-run (subprocess)
# ===========================================================================

class TestDryRun:
    """--dry-run must print valid JSON without making HTTP calls."""

    def _run_dry(self, *extra: str) -> dict:
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES",
             "--title", "NVDA over-sized position", "--content", "Lesson learned",
             *extra, "--dry-run"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        lines = r.stdout.split("\n", 1)
        return json.loads(lines[1])

    def test_exits_0(self):
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES", "--title", "T",
             "--content", "C", "--dry-run"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0

    def test_category_in_output(self):
        assert self._run_dry()["category"] == "MISTAKES"

    def test_title_in_output(self):
        assert "NVDA" in self._run_dry()["title"]

    def test_default_confidence_for_mistakes(self):
        assert self._run_dry()["confidence_score"] == pytest.approx(0.85)

    def test_custom_confidence_respected(self):
        assert self._run_dry("--confidence", "0.9")["confidence_score"] == pytest.approx(0.9)

    def test_symbols_parsed_and_uppercased(self):
        data = self._run_dry("--symbols", "nvda,tsla")
        assert "NVDA" in data["symbols"]
        assert "TSLA" in data["symbols"]

    def test_tags_parsed_and_lowercased(self):
        data = self._run_dry("--tags", "Earnings,LOSS")
        assert "earnings" in data["tags"]
        assert "loss" in data["tags"]

    def test_trade_id_in_trade_ref_ids(self):
        assert "abc-123" in self._run_dry("--trade-id", "abc-123")["trade_ref_ids"]

    def test_is_shared_flag_overrides_default(self):
        assert self._run_dry("--is-shared")["is_shared"] is True

    def test_mistakes_not_shared_by_default(self):
        assert self._run_dry()["is_shared"] is False

    def test_market_patterns_shared_by_default(self):
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MARKET_PATTERNS", "--title", "Bull flag",
             "--content", "Pattern noted", "--dry-run"],
            capture_output=True, text=True,
        )
        lines = r.stdout.split("\n", 1)
        assert json.loads(lines[1])["is_shared"] is True

    def test_subcategory_included(self):
        assert self._run_dry("--subcategory", "options")["subcategory"] == "options"

    def test_no_subcategory_key_absent(self):
        data = self._run_dry()
        assert "subcategory" not in data


# ===========================================================================
# 6. write_wiki_entry() async helper
# ===========================================================================

class TestWriteWikiEntryAsync:
    @pytest.mark.asyncio
    async def test_posts_to_correct_url(self):
        mock_client = _mock_httpx_client(201, {"id": "e-001", "category": "MISTAKES"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await wwe.write_wiki_entry(
                SAMPLE_CONFIG,
                {"category": "MISTAKES", "title": "T", "content": "C"},
            )
        url = mock_client.post.call_args[0][0]
        assert "agent-uuid-123" in url
        assert "/wiki" in url
        assert result["id"] == "e-001"

    @pytest.mark.asyncio
    async def test_default_confidence_injected(self):
        mock_client = _mock_httpx_client(201, {"id": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            await wwe.write_wiki_entry(
                SAMPLE_CONFIG,
                {"category": "MISTAKES", "title": "T", "content": "C"},
            )
        payload = mock_client.post.call_args[1]["json"]
        assert payload["confidence_score"] == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_bearer_token_in_header(self):
        mock_client = _mock_httpx_client(201, {"id": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            await wwe.write_wiki_entry(
                SAMPLE_CONFIG,
                {"category": "TRADE_OBSERVATION", "title": "T", "content": "C"},
            )
        headers = mock_client.post.call_args[1]["headers"]
        assert headers.get("Authorization") == "Bearer test-bearer-token"

    @pytest.mark.asyncio
    async def test_no_auth_header_when_token_empty(self, monkeypatch):
        monkeypatch.delenv("PHOENIX_API_TOKEN", raising=False)
        config_no_token = {"phoenix_api_url": "http://test:8011", "agent_id": "agent-uuid"}
        mock_client = _mock_httpx_client(201, {"id": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            await wwe.write_wiki_entry(
                config_no_token,
                {"category": "TRADE_OBSERVATION", "title": "T", "content": "C"},
            )
        headers = mock_client.post.call_args[1]["headers"]
        assert headers == {}

    @pytest.mark.asyncio
    async def test_is_shared_defaults_false_for_mistakes(self):
        mock_client = _mock_httpx_client(201, {"id": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            await wwe.write_wiki_entry(
                SAMPLE_CONFIG,
                {"category": "MISTAKES", "title": "T", "content": "C"},
            )
        assert mock_client.post.call_args[1]["json"]["is_shared"] is False

    @pytest.mark.asyncio
    async def test_is_shared_defaults_true_for_market_patterns(self):
        mock_client = _mock_httpx_client(201, {"id": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            await wwe.write_wiki_entry(
                SAMPLE_CONFIG,
                {"category": "MARKET_PATTERNS", "title": "T", "content": "C"},
            )
        assert mock_client.post.call_args[1]["json"]["is_shared"] is True

    @pytest.mark.asyncio
    async def test_4xx_raises_http_status_error(self):
        import httpx
        mock_client = _mock_httpx_client(422, {"detail": "Validation error"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await wwe.write_wiki_entry(
                    SAMPLE_CONFIG,
                    {"category": "MISTAKES", "title": "T", "content": "C"},
                )

    @pytest.mark.asyncio
    async def test_5xx_raises_http_status_error(self):
        import httpx
        mock_client = _mock_httpx_client(500, {"detail": "Internal server error"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await wwe.write_wiki_entry(
                    SAMPLE_CONFIG,
                    {"category": "MISTAKES", "title": "T", "content": "C"},
                )


# ===========================================================================
# 7. CLI error handling (subprocess)
# ===========================================================================

class TestCLIErrorHandling:
    """API errors must be non-fatal: exit 2, warn to stderr, never traceback."""

    def test_api_error_exits_2(self):
        import os
        env = {**os.environ, "PHOENIX_API_URL": "http://localhost:19999"}
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES", "--title", "Test", "--content", "C"],
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert r.returncode == 2

    def test_api_error_prints_warning_to_stderr(self):
        import os
        env = {**os.environ, "PHOENIX_API_URL": "http://localhost:19999"}
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES", "--title", "Test", "--content", "C"],
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert "non-fatal" in r.stderr

    def test_api_error_no_traceback_in_stdout(self):
        import os
        env = {**os.environ, "PHOENIX_API_URL": "http://localhost:19999"}
        r = subprocess.run(
            [PYTHON, SCRIPT, "--category", "MISTAKES", "--title", "Test", "--content", "C"],
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert "Traceback" not in r.stdout


# ===========================================================================
# 8. CLI success output format (mocked via inline Python)
# ===========================================================================

class TestCLISuccessOutput:
    def test_success_output_format(self):
        mock_script = (
            "import sys, json\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import unittest.mock as mock\n"
            "mock_resp = mock.MagicMock()\n"
            "mock_resp.raise_for_status = mock.MagicMock()\n"
            "mock_resp.json.return_value = {'id': 'wiki-entry-uuid-001', 'category': 'MISTAKES'}\n"
            "mock_client = mock.AsyncMock()\n"
            "mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)\n"
            "mock_client.__aexit__ = mock.AsyncMock(return_value=False)\n"
            "mock_client.post = mock.AsyncMock(return_value=mock_resp)\n"
            "with mock.patch('httpx.AsyncClient', return_value=mock_client):\n"
            "    import write_wiki_entry as wwe\n"
            "    sys.argv = ['write_wiki_entry.py', '--category', 'MISTAKES',\n"
            "                '--title', 'NVDA over-sized position',\n"
            "                '--content', 'Lesson learned', '--confidence', '0.9']\n"
            "    wwe.main()\n"
        )
        r = subprocess.run(
            [PYTHON, "-c", mock_script, str(TOOL_DIR)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        assert "Wiki entry written:" in r.stdout
        assert "wiki-entry-uuid-001" in r.stdout
        assert "[MISTAKES]" in r.stdout
        assert "NVDA over-sized position" in r.stdout
        assert "90%" in r.stdout
