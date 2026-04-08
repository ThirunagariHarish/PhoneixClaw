"""Unit tests for write_wiki_entry agent tool."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# We test by importing the module directly from the tools directory.
# ---------------------------------------------------------------------------
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agents" / "templates" / "live-trader-v1" / "tools"))

from write_wiki_entry import (
    _default_is_shared,
    get_wiki_summary,
    query_wiki,
    write_wiki_entry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "phoenix_api_url": "http://localhost:8011",
    "agent_id": "agent-uuid-123",
    "phoenix_api_key": "test-key",
}

SAMPLE_ENTRY = {
    "category": "TRADE_OBSERVATION",
    "title": "AAPL bearish reversal at resistance",
    "content": "Observed clean bearish engulfing candle at $185 resistance level.",
    "tags": ["bearish", "reversal", "resistance"],
    "symbols": ["AAPL"],
    "confidence_score": 0.75,
    "trade_ref_ids": ["trade-uuid-abc"],
}

CREATED_WIKI_RESPONSE = {
    "id": "wiki-entry-uuid-xyz",
    "agent_id": "agent-uuid-123",
    "category": "TRADE_OBSERVATION",
    "title": "AAPL bearish reversal at resistance",
    "content": "Observed clean bearish engulfing candle at $185 resistance level.",
    "tags": ["bearish", "reversal", "resistance"],
    "symbols": ["AAPL"],
    "confidence_score": 0.75,
    "trade_ref_ids": ["trade-uuid-abc"],
    "is_shared": False,
    "version": 1,
    "created_at": "2025-01-15T10:00:00Z",
    "updated_at": "2025-01-15T10:00:00Z",
}


# ---------------------------------------------------------------------------
# Helper: build a mock httpx response
# ---------------------------------------------------------------------------

def _mock_response(status_code: int, body: dict | list) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = body
    if status_code >= 400:
        import httpx
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=mock_resp,
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# Tests: _default_is_shared
# ---------------------------------------------------------------------------

class TestDefaultIsShared:
    def test_trade_observation_not_shared(self) -> None:
        assert _default_is_shared("TRADE_OBSERVATION") is False

    def test_general_not_shared(self) -> None:
        assert _default_is_shared("GENERAL") is False

    def test_market_pattern_shared(self) -> None:
        assert _default_is_shared("MARKET_PATTERN") is True

    def test_strategy_learning_shared(self) -> None:
        assert _default_is_shared("STRATEGY_LEARNING") is True

    def test_risk_note_shared(self) -> None:
        assert _default_is_shared("RISK_NOTE") is True

    def test_sector_insight_shared(self) -> None:
        assert _default_is_shared("SECTOR_INSIGHT") is True

    def test_indicator_note_shared(self) -> None:
        assert _default_is_shared("INDICATOR_NOTE") is True

    def test_earnings_playbook_shared(self) -> None:
        assert _default_is_shared("EARNINGS_PLAYBOOK") is True

    def test_case_insensitive(self) -> None:
        assert _default_is_shared("market_pattern") is True
        assert _default_is_shared("trade_observation") is False


# ---------------------------------------------------------------------------
# Tests: write_wiki_entry — happy path
# ---------------------------------------------------------------------------

class TestWriteWikiEntry:
    @pytest.mark.asyncio
    async def test_happy_path_returns_dict(self) -> None:
        mock_resp = _mock_response(201, CREATED_WIKI_RESPONSE)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await write_wiki_entry(SAMPLE_CONFIG, SAMPLE_ENTRY)

        assert result["id"] == "wiki-entry-uuid-xyz"
        assert result["category"] == "TRADE_OBSERVATION"
        assert result["title"] == "AAPL bearish reversal at resistance"

    @pytest.mark.asyncio
    async def test_correct_endpoint_called(self) -> None:
        mock_resp = _mock_response(201, CREATED_WIKI_RESPONSE)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await write_wiki_entry(SAMPLE_CONFIG, SAMPLE_ENTRY)

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:8011/api/v2/agents/agent-uuid-123/wiki"

    @pytest.mark.asyncio
    async def test_trade_observation_defaults_is_shared_false(self) -> None:
        mock_resp = _mock_response(201, CREATED_WIKI_RESPONSE)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await write_wiki_entry(SAMPLE_CONFIG, SAMPLE_ENTRY)

        posted_payload = mock_client.post.call_args[1]["json"]
        assert posted_payload["is_shared"] is False

    @pytest.mark.asyncio
    async def test_market_pattern_defaults_is_shared_true(self) -> None:
        entry = {**SAMPLE_ENTRY, "category": "MARKET_PATTERN"}
        mock_resp = _mock_response(201, {**CREATED_WIKI_RESPONSE, "category": "MARKET_PATTERN", "is_shared": True})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await write_wiki_entry(SAMPLE_CONFIG, entry)

        posted_payload = mock_client.post.call_args[1]["json"]
        assert posted_payload["is_shared"] is True

    @pytest.mark.asyncio
    async def test_is_shared_override(self) -> None:
        """Explicitly passing is_shared=True overrides the default."""
        entry = {**SAMPLE_ENTRY, "is_shared": True}
        mock_resp = _mock_response(201, {**CREATED_WIKI_RESPONSE, "is_shared": True})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await write_wiki_entry(SAMPLE_CONFIG, entry)

        posted_payload = mock_client.post.call_args[1]["json"]
        assert posted_payload["is_shared"] is True

    @pytest.mark.asyncio
    async def test_authorization_header_sent(self) -> None:
        mock_resp = _mock_response(201, CREATED_WIKI_RESPONSE)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await write_wiki_entry(SAMPLE_CONFIG, SAMPLE_ENTRY)

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test-key"

    @pytest.mark.asyncio
    async def test_4xx_raises_http_status_error(self) -> None:
        import httpx
        mock_resp = _mock_response(422, {"detail": "Validation error"})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await write_wiki_entry(SAMPLE_CONFIG, SAMPLE_ENTRY)

    @pytest.mark.asyncio
    async def test_5xx_raises_http_status_error(self) -> None:
        import httpx
        mock_resp = _mock_response(500, {"detail": "Internal server error"})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await write_wiki_entry(SAMPLE_CONFIG, SAMPLE_ENTRY)


# ---------------------------------------------------------------------------
# Tests: query_wiki
# ---------------------------------------------------------------------------

SAMPLE_WIKI_LIST_RESPONSE = {
    "entries": [
        {
            "id": "entry-1",
            "category": "TRADE_OBSERVATION",
            "title": "AAPL test",
            "content": "content",
            "tags": [],
            "symbols": ["AAPL"],
            "confidence_score": 0.8,
            "version": 1,
            "created_at": "2025-01-15T10:00:00Z",
        }
    ],
    "total": 1,
    "page": 1,
    "per_page": 10,
}


class TestQueryWiki:
    @pytest.mark.asyncio
    async def test_happy_path_returns_list(self) -> None:
        mock_resp = _mock_response(200, SAMPLE_WIKI_LIST_RESPONSE)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await query_wiki(SAMPLE_CONFIG, "AAPL resistance")

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["id"] == "entry-1"

    @pytest.mark.asyncio
    async def test_category_filter_passed_as_param(self) -> None:
        mock_resp = _mock_response(200, SAMPLE_WIKI_LIST_RESPONSE)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await query_wiki(SAMPLE_CONFIG, "test", category="MARKET_PATTERN")

        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["category"] == "MARKET_PATTERN"

    @pytest.mark.asyncio
    async def test_no_category_filter_omits_param(self) -> None:
        mock_resp = _mock_response(200, SAMPLE_WIKI_LIST_RESPONSE)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await query_wiki(SAMPLE_CONFIG, "test")

        call_params = mock_client.get.call_args[1]["params"]
        assert "category" not in call_params

    @pytest.mark.asyncio
    async def test_4xx_raises(self) -> None:
        import httpx
        mock_resp = _mock_response(400, {"detail": "Bad request"})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await query_wiki(SAMPLE_CONFIG, "test")


# ---------------------------------------------------------------------------
# Tests: get_wiki_summary
# ---------------------------------------------------------------------------

SAMPLE_SUMMARY = {
    "total": 42,
    "by_category": {
        "TRADE_OBSERVATION": 20,
        "MARKET_PATTERN": 8,
        "STRATEGY_LEARNING": 5,
        "GENERAL": 9,
    },
}


class TestGetWikiSummary:
    @pytest.mark.asyncio
    async def test_happy_path_returns_summary_dict(self) -> None:
        mock_resp = _mock_response(200, SAMPLE_SUMMARY)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_wiki_summary(SAMPLE_CONFIG)

        assert result["total"] == 42
        assert "by_category" in result

    @pytest.mark.asyncio
    async def test_categories_filter_joined_as_csv(self) -> None:
        mock_resp = _mock_response(200, SAMPLE_SUMMARY)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await get_wiki_summary(SAMPLE_CONFIG, categories=["TRADE_OBSERVATION", "MARKET_PATTERN"])

        call_params = mock_client.get.call_args[1]["params"]
        assert "TRADE_OBSERVATION" in call_params["categories"]
        assert "MARKET_PATTERN" in call_params["categories"]

    @pytest.mark.asyncio
    async def test_no_categories_omits_param(self) -> None:
        mock_resp = _mock_response(200, SAMPLE_SUMMARY)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await get_wiki_summary(SAMPLE_CONFIG)

        call_params = mock_client.get.call_args[1]["params"]
        assert "categories" not in call_params

    @pytest.mark.asyncio
    async def test_4xx_raises(self) -> None:
        import httpx
        mock_resp = _mock_response(404, {"detail": "Not found"})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await get_wiki_summary(SAMPLE_CONFIG)
