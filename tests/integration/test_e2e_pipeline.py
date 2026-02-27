"""End-to-end pipeline integration tests.

Tests the full flow: raw message -> trade parser -> parsed trade output,
and verifies the auth refresh preserves admin status.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trade_parser.src.parser import parse_trade_message


class TestTradeParserE2E:
    """Verify messages that look like Discord trade signals parse correctly end-to-end."""

    VALID_SIGNALS = [
        ("Bought SPX 6940C at 4.80", "BUY", "SPX", 6940.0, "CALL", 4.80),
        ("Sold 50% SPX 6950C at 6.50", "SELL", "SPX", 6950.0, "CALL", 6.50),
        ("Bought IWM 250P at 1.50 Exp: 02/20/2026", "BUY", "IWM", 250.0, "PUT", 1.50),
        ("Buy AAPL 190C at 3.50", "BUY", "AAPL", 190.0, "CALL", 3.50),
        ("Sold TSLA 250P at 5.00", "SELL", "TSLA", 250.0, "PUT", 5.00),
    ]

    @pytest.mark.parametrize("msg,action,ticker,strike,opt_type,price", VALID_SIGNALS)
    def test_valid_trade_signals(self, msg, action, ticker, strike, opt_type, price):
        result = parse_trade_message(msg)
        assert len(result["actions"]) >= 1, f"Expected trade from: {msg}"
        act = result["actions"][0]
        assert act["action"] == action
        assert act["ticker"] == ticker
        assert act["strike"] == strike
        assert act["option_type"] == opt_type
        assert act["price"] == price
        assert result["raw_message"] == msg

    NOISE_MESSAGES = [
        "Hey everyone, market looks bullish today!",
        "I think SPX will hit 7000 by Friday",
        "Good morning traders!",
        "What do you think about AAPL earnings?",
        "https://www.example.com/chart.png",
    ]

    @pytest.mark.parametrize("msg", NOISE_MESSAGES)
    def test_noise_messages_produce_no_trades(self, msg):
        result = parse_trade_message(msg)
        assert len(result["actions"]) == 0, f"Should not parse trade from: {msg}"


class TestRawMessagePipeline:
    """Test the raw message writer's message transformation logic."""

    def test_raw_message_dict_shape(self):
        """Verify the shape of a raw message dict as produced by DiscordIngestor."""
        raw_msg = {
            "content": "Bought SPX 6940C at 4.80",
            "message_id": "123456789",
            "source_message_id": "123456789",
            "author": "trader#1234",
            "channel_name": "alerts",
            "channel_id": "999888777",
            "guild_id": "111222333",
            "user_id": str(uuid.uuid4()),
            "data_source_id": str(uuid.uuid4()),
            "source": "discord",
            "source_type": "discord",
            "timestamp": "2026-02-20T10:00:00+00:00",
        }

        assert raw_msg["content"]
        assert raw_msg["user_id"]
        assert raw_msg["data_source_id"]
        assert raw_msg["source_type"] == "discord"

        result = parse_trade_message(raw_msg["content"])
        assert len(result["actions"]) == 1
        assert result["actions"][0]["ticker"] == "SPX"

    @pytest.mark.asyncio
    async def test_raw_message_writer_flush(self):
        """Test RawMessageWriterService can flush messages with mocked DB."""
        from services.audit_writer.src.raw_message_writer import RawMessageWriterService

        svc = RawMessageWriterService()
        user_id = str(uuid.uuid4())
        ds_id = str(uuid.uuid4())

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        with patch(
            "services.audit_writer.src.raw_message_writer.AsyncSessionLocal",
            return_value=mock_session,
        ):
            svc._buffer = [
                {
                    "content": "Bought SPX 6940C at 4.80",
                    "user_id": user_id,
                    "data_source_id": ds_id,
                    "source_type": "discord",
                    "channel_name": "alerts",
                    "author": "trader",
                    "source_message_id": "msg-1",
                    "raw_metadata": {},
                },
            ]
            await svc._flush()

        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()
        assert svc._total_written == 1

    @pytest.mark.asyncio
    async def test_raw_message_writer_retries_on_failure(self):
        """Test that flush retries on transient DB errors."""
        from services.audit_writer.src.raw_message_writer import RawMessageWriterService

        svc = RawMessageWriterService()
        user_id = str(uuid.uuid4())

        fail_session = AsyncMock()
        fail_session.__aenter__ = AsyncMock(return_value=fail_session)
        fail_session.__aexit__ = AsyncMock(return_value=False)
        fail_session.add = MagicMock()
        fail_session.commit = AsyncMock(side_effect=Exception("DB down"))

        with patch(
            "services.audit_writer.src.raw_message_writer.AsyncSessionLocal",
            return_value=fail_session,
        ), patch(
            "services.audit_writer.src.raw_message_writer.RETRY_DELAY_SECONDS", 0.01,
        ):
            svc._buffer = [
                {
                    "content": "test msg",
                    "user_id": user_id,
                    "source_type": "discord",
                },
            ]
            await svc._flush()

        assert fail_session.commit.await_count == 3
        assert svc._total_errors > 0


class TestAuthRefreshAdmin:
    """Verify that the refresh endpoint preserves admin status."""

    def test_create_access_token_includes_admin(self):
        from services.auth_service.src.auth import create_access_token, decode_token

        token = create_access_token("user-123", is_admin=True)
        payload = decode_token(token)
        assert payload["admin"] is True
        assert payload["sub"] == "user-123"

    def test_create_access_token_default_not_admin(self):
        from services.auth_service.src.auth import create_access_token, decode_token

        token = create_access_token("user-456")
        payload = decode_token(token)
        assert payload["admin"] is False


class TestChannelSync:
    """Test the _ensure_channels_from_credentials helper with various formats."""

    @pytest.mark.asyncio
    async def test_channel_ids_as_string(self):
        from services.api_gateway.src.routes.sources import _ensure_channels_from_credentials

        mock_source = MagicMock()
        mock_source.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()

        creds = {"channel_ids": "123,456,789"}
        created = await _ensure_channels_from_credentials(mock_source, creds, mock_session)
        assert created == 3
        assert mock_session.add.call_count == 3

    @pytest.mark.asyncio
    async def test_channel_ids_as_list(self):
        from services.api_gateway.src.routes.sources import _ensure_channels_from_credentials

        mock_source = MagicMock()
        mock_source.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()

        creds = {"channel_ids": [123, 456]}
        created = await _ensure_channels_from_credentials(mock_source, creds, mock_session)
        assert created == 2

    @pytest.mark.asyncio
    async def test_channel_ids_skips_existing(self):
        from services.api_gateway.src.routes.sources import _ensure_channels_from_credentials

        mock_source = MagicMock()
        mock_source.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("123",)]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()

        creds = {"channel_ids": "123,456"}
        created = await _ensure_channels_from_credentials(mock_source, creds, mock_session)
        assert created == 1

    @pytest.mark.asyncio
    async def test_empty_channel_ids(self):
        from services.api_gateway.src.routes.sources import _ensure_channels_from_credentials

        mock_source = MagicMock()
        mock_source.id = uuid.uuid4()
        mock_session = AsyncMock()

        creds = {"channel_ids": ""}
        created = await _ensure_channels_from_credentials(mock_source, creds, mock_session)
        assert created == 0

        creds_none = {}
        created = await _ensure_channels_from_credentials(mock_source, creds_none, mock_session)
        assert created == 0
