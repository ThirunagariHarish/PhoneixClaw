
import pytest

from services.api_gateway.src.websocket import _authenticate_ws, _connections, broadcast


class TestWebSocketAuth:
    def test_invalid_token_returns_none(self):
        result = _authenticate_ws("not-a-valid-jwt")
        assert result is None

    def test_empty_token_returns_none(self):
        result = _authenticate_ws("")
        assert result is None


class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self):
        await broadcast("trades", "nonexistent-user", {"test": True})

    @pytest.mark.asyncio
    async def test_connections_dict_structure(self):
        assert isinstance(_connections, dict)
