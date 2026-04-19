"""Unit tests for Robinhood broker adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared.broker.robinhood_adapter import BrokerAPIError, RobinhoodBrokerAdapter


class TestRobinhoodAdapter:
    """Test Robinhood adapter with mocked httpx.AsyncClient."""

    @pytest.fixture
    def adapter(self):
        return RobinhoodBrokerAdapter(mcp_url="http://test-mcp:8080")

    @pytest.fixture
    def mock_client(self):
        """Mock httpx.AsyncClient with configurable responses."""
        client = AsyncMock(spec=httpx.AsyncClient)
        return client

    @pytest.mark.asyncio
    async def test_place_limit_order_success(self, adapter, mock_client):
        """Test successful limit order placement."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"order_id": "RH123"}
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        adapter._client = mock_client

        order_id = await adapter.place_limit_order("SPY260616C00600000", 1, "buy", 3.50)
        assert order_id == "RH123"
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://test-mcp:8080/place_order"
        assert call_args[1]["json"]["symbol"] == "SPY 6/16/26 600C"
        assert call_args[1]["json"]["quantity"] == 1
        assert call_args[1]["json"]["side"] == "buy"

    @pytest.mark.asyncio
    async def test_place_limit_order_http_error(self, adapter, mock_client):
        """Test limit order with HTTP error."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad request", request=MagicMock(), response=mock_response
        )
        mock_client.post = AsyncMock(return_value=mock_response)

        adapter._client = mock_client

        with pytest.raises(BrokerAPIError) as exc_info:
            await adapter.place_limit_order("SPY260616C00600000", 1, "buy", 3.50)
        assert "MCP server error 400" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_place_bracket_order(self, adapter, mock_client):
        """Test bracket order placement."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"order_id": "RH456"}
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        adapter._client = mock_client

        order_id = await adapter.place_bracket_order("AAPL", 10, "buy", 180.0, 190.0, 170.0)
        assert order_id == "RH456"
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["take_profit"] == 190.0
        assert payload["stop_loss"] == 170.0

    @pytest.mark.asyncio
    async def test_cancel_order(self, adapter, mock_client):
        """Test order cancellation."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        adapter._client = mock_client

        result = await adapter.cancel_order("RH123")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_order_status(self, adapter, mock_client):
        """Test get order status."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "filled",
            "filled_quantity": 10,
            "fill_price": 180.50,
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        adapter._client = mock_client

        status = await adapter.get_order_status("RH123")
        assert status["status"] == "filled"
        assert status["filled_qty"] == 10
        assert status["fill_price"] == 180.50

    @pytest.mark.asyncio
    async def test_get_positions(self, adapter, mock_client):
        """Test get positions."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "positions": [
                {
                    "symbol": "SPY 6/16/26 600C",
                    "quantity": 5,
                    "avg_cost": 3.40,
                    "current_price": 3.50,
                    "pnl": 50.0,
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        adapter._client = mock_client

        positions = await adapter.get_positions()
        assert len(positions) == 1
        # Symbol should be converted back to OCC
        assert positions[0]["symbol"] == "SPY260616C00600000"
        assert positions[0]["quantity"] == 5

    @pytest.mark.asyncio
    async def test_get_quote(self, adapter, mock_client):
        """Test get quote."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "bid": 3.40,
            "ask": 3.50,
            "last": 3.45,
            "timestamp": "2026-04-18T10:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        adapter._client = mock_client

        quote = await adapter.get_quote("SPY260616C00600000")
        assert quote["bid"] == 3.40
        assert quote["ask"] == 3.50
        assert quote["last"] == 3.45

    @pytest.mark.asyncio
    async def test_get_account(self, adapter, mock_client):
        """Test get account."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "buying_power": 25000.0,
            "cash": 10000.0,
            "equity": 50000.0,
            "portfolio_value": 50000.0,
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        adapter._client = mock_client

        account = await adapter.get_account()
        assert account["buying_power"] == 25000.0
        assert account["equity"] == 50000.0

    @pytest.mark.asyncio
    async def test_close_position(self, adapter, mock_client):
        """Test close position."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        adapter._client = mock_client

        result = await adapter.close_position("SPY260616C00600000")
        assert result is True
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["symbol"] == "SPY 6/16/26 600C"

    def test_format_option_symbol(self, adapter):
        """Test format_option_symbol returns human-readable format."""
        result = adapter.format_option_symbol("SPY", "2026-06-16", "C", 600.0)
        assert result == "SPY 6/16/26 600C"

        result = adapter.format_option_symbol("AAPL", "2026-04-18", "P", 190.5)
        assert result == "AAPL 4/18/26 190.5P"

    def test_occ_to_robinhood_conversion(self, adapter):
        """Test OCC to Robinhood symbol conversion."""
        # SPY option: SPY260616C00600000 -> SPY 6/16/26 600C
        result = adapter._occ_to_robinhood("SPY260616C00600000")
        assert result == "SPY 6/16/26 600C"

        # Stock: AAPL -> AAPL (unchanged)
        result = adapter._occ_to_robinhood("AAPL")
        assert result == "AAPL"

        # Decimal strike: SPY260616C00599500 -> SPY 6/16/26 599.5C
        result = adapter._occ_to_robinhood("SPY260616C00599500")
        assert result == "SPY 6/16/26 599.5C"

        # Put option
        result = adapter._occ_to_robinhood("QQQ260418P00450000")
        assert result == "QQQ 4/18/26 450P"

    def test_robinhood_to_occ_conversion(self, adapter):
        """Test Robinhood to OCC symbol conversion."""
        # SPY 6/16/26 600C -> SPY260616C00600000
        result = adapter._robinhood_to_occ("SPY 6/16/26 600C")
        assert result == "SPY260616C00600000"

        # Stock: AAPL -> AAPL (unchanged)
        result = adapter._robinhood_to_occ("AAPL")
        assert result == "AAPL"

        # Decimal strike: SPY 6/16/26 599.5C -> SPY260616C00599500
        result = adapter._robinhood_to_occ("SPY 6/16/26 599.5C")
        assert result == "SPY260616C00599500"

    def test_symbol_conversion_round_trip(self, adapter):
        """Test OCC -> Robinhood -> OCC round-trip."""
        occ_symbols = [
            "SPY260616C00600000",
            "AAPL260418P00190000",
            "QQQ260516C00450000",
            "SPX261218C06950000",
        ]

        for occ in occ_symbols:
            rh = adapter._occ_to_robinhood(occ)
            back_to_occ = adapter._robinhood_to_occ(rh)
            assert back_to_occ == occ, f"Round-trip failed for {occ}: {rh} -> {back_to_occ}"

    @pytest.mark.asyncio
    async def test_close_client(self, adapter, mock_client):
        """Test closing the HTTP client."""
        adapter._client = mock_client
        await adapter.close()
        mock_client.aclose.assert_called_once()
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_request_error_handling(self, adapter, mock_client):
        """Test handling of network errors."""
        mock_client.post = AsyncMock(side_effect=httpx.RequestError("Connection refused"))
        adapter._client = mock_client

        with pytest.raises(BrokerAPIError) as exc_info:
            await adapter.place_limit_order("SPY260616C00600000", 1, "buy", 3.50)
        assert "MCP server unreachable" in str(exc_info.value)
