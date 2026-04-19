"""Tests for enricher."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from services.pipeline_worker.src.pipeline.enricher import enrich_signal


class TestEnrichSignal:
    @pytest.mark.asyncio
    async def test_returns_features_on_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"rsi": 45.0, "macd": 0.5})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await enrich_signal("AAPL", mock_client, "http://fake:8050")
        assert result == {"rsi": 45.0, "macd": 0.5}
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_failure(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        result = await enrich_signal("AAPL", mock_client, "http://fake:8050")
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_http_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "500", request=httpx.Request("GET", "http://fake"), response=mock_response
        ))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await enrich_signal("AAPL", mock_client, "http://fake:8050")
        assert result == {}
