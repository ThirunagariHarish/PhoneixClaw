"""Unit tests for the Discord Ingestion Service."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.discord_ingestion.src.main import (
    ConnectorState,
    _basic_sentiment,
    _extract_channel_ids,
    _extract_tickers,
    _persist_message,
    _write_sentiment_feature,
    app,
)


class TestExtractTickers:
    def test_single_ticker(self):
        assert _extract_tickers("Buy $AAPL now") == ["AAPL"]

    def test_multiple_tickers(self):
        result = _extract_tickers("Watch $AAPL and $TSLA today")
        assert sorted(result) == ["AAPL", "TSLA"]

    def test_no_tickers(self):
        assert _extract_tickers("No tickers here") == []

    def test_duplicate_tickers(self):
        result = _extract_tickers("$AAPL is great, $AAPL again")
        assert result == ["AAPL"]

    def test_lowercase_not_matched(self):
        assert _extract_tickers("$aapl lowercase") == []

    def test_ticker_too_long(self):
        assert _extract_tickers("$ABCDEF is too long") == []

    def test_single_char_ticker(self):
        assert _extract_tickers("$X is a ticker") == ["X"]


class TestBasicSentiment:
    def test_positive(self):
        assert _basic_sentiment("Very bullish on this breakout!") == "positive"

    def test_negative(self):
        assert _basic_sentiment("Bearish, puts are printing, dump incoming") == "negative"

    def test_neutral(self):
        assert _basic_sentiment("Just some random message") == "neutral"

    def test_mixed_leans_positive(self):
        assert _basic_sentiment("Bullish breakout but slight bearish") == "positive"

    def test_mixed_leans_negative(self):
        assert _basic_sentiment("Puts and sell but calls") == "negative"

    def test_empty_string(self):
        assert _basic_sentiment("") == "neutral"


class TestExtractChannelIds:
    def test_channel_ids_list(self):
        config = {"channel_ids": ["123", "456"]}
        assert _extract_channel_ids(config) == ["123", "456"]

    def test_channel_id_single(self):
        config = {"channel_id": "789"}
        assert _extract_channel_ids(config) == ["789"]

    def test_selected_channels_dict(self):
        config = {"selected_channels": [{"channel_id": "111"}, {"channel_id": "222"}]}
        assert _extract_channel_ids(config) == ["111", "222"]

    def test_selected_channels_strings(self):
        config = {"selected_channels": ["333", "444"]}
        assert _extract_channel_ids(config) == ["333", "444"]

    def test_none_config(self):
        assert _extract_channel_ids(None) == []

    def test_empty_config(self):
        assert _extract_channel_ids({}) == []

    def test_channel_ids_priority_over_single(self):
        config = {"channel_ids": ["100"], "channel_id": "200"}
        assert _extract_channel_ids(config) == ["100"]

    def test_empty_channel_ids_falls_through(self):
        config = {"channel_ids": [], "channel_id": "999"}
        assert _extract_channel_ids(config) == ["999"]

    def test_numeric_channel_ids_converted(self):
        config = {"channel_ids": [123, 456]}
        assert _extract_channel_ids(config) == ["123", "456"]


class TestConnectorState:
    def test_initial_state(self):
        state = ConnectorState(
            connector_id="abc-123",
            channel_name="#day-trades",
            channel_ids=["1", "2"],
            token="fake-token",
        )
        assert state.connector_id == "abc-123"
        assert state.channel_name == "#day-trades"
        assert state.connected is False
        assert state.messages_received == 0
        assert state.task is None
        assert state.channel_ids == ["1", "2"]
        assert state.token == "fake-token"


class TestPersistMessage:
    @pytest.mark.asyncio
    async def test_persist_inserts_and_publishes(self):
        connector_id = str(uuid.uuid4())
        state = ConnectorState(connector_id=connector_id, channel_name="#test", channel_ids=[], token="t")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        mock_redis = AsyncMock()

        with patch("services.discord_ingestion.src.main._get_redis", return_value=mock_redis):
            with patch("services.discord_ingestion.src.main._write_sentiment_feature", new_callable=AsyncMock):
                await _persist_message(
                    session_factory=mock_factory,
                    state=state,
                    channel_name="#day-trades",
                    author="TestUser",
                    content="Buy $AAPL calls",
                    raw_data={"id": "msg-1"},
                    platform_message_id="msg-1",
                    posted_at=datetime.now(timezone.utc),
                )

        assert state.messages_received == 1
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_increments_counter(self):
        connector_id = str(uuid.uuid4())
        state = ConnectorState(connector_id=connector_id, channel_name="#test", channel_ids=[], token="t")
        state.messages_received = 5

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        with patch("services.discord_ingestion.src.main._get_redis", return_value=AsyncMock()):
            with patch("services.discord_ingestion.src.main._write_sentiment_feature", new_callable=AsyncMock):
                await _persist_message(
                    session_factory=mock_factory,
                    state=state,
                    channel_name="#test",
                    author="User",
                    content="Hello",
                    raw_data={},
                    platform_message_id="m2",
                    posted_at=datetime.now(timezone.utc),
                )

        assert state.messages_received == 6

    @pytest.mark.asyncio
    async def test_persist_handles_redis_none(self):
        connector_id = str(uuid.uuid4())
        state = ConnectorState(connector_id=connector_id, channel_name="#test", channel_ids=[], token="t")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        with patch("services.discord_ingestion.src.main._get_redis", return_value=None):
            with patch("services.discord_ingestion.src.main._write_sentiment_feature", new_callable=AsyncMock):
                await _persist_message(
                    session_factory=mock_factory,
                    state=state,
                    channel_name="#test",
                    author="User",
                    content="No redis",
                    raw_data={},
                    platform_message_id="m3",
                    posted_at=datetime.now(timezone.utc),
                )

        assert state.messages_received == 1
        mock_session.execute.assert_called_once()


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_connectors(self):
        from httpx import ASGITransport, AsyncClient

        with patch.dict("services.discord_ingestion.src.main._connectors", {
            "c1": ConnectorState("c1", "#ch1", [], "t"),
        }):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/health")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "ok"
                assert len(data["connectors"]) == 1
                assert data["connectors"][0]["id"] == "c1"
                assert data["connectors"][0]["connected"] is False
                assert data["connectors"][0]["messages_received"] == 0


class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status_returns_detail(self):
        from httpx import ASGITransport, AsyncClient

        state = ConnectorState("c2", "#signals", ["111", "222"], "t")
        state.connected = True
        state.messages_received = 42

        with patch.dict("services.discord_ingestion.src.main._connectors", {"c2": state}):
            with patch("services.discord_ingestion.src.main._running", True):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/status")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["service"] == "discord-ingestion"
                    assert data["total_connectors"] == 1
                    connector = data["connectors"][0]
                    assert connector["connected"] is True
                    assert connector["messages_received"] == 42
                    assert connector["channel_ids"] == ["111", "222"]


class TestWriteSentimentFeature:
    @pytest.mark.asyncio
    async def test_skips_when_no_tickers(self):
        with patch("services.discord_ingestion.src.main._get_session_factory") as mock_sf:
            await _write_sentiment_feature("conn-1", [], "some content")
            mock_sf.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_feature_store_error(self):
        with patch("services.discord_ingestion.src.main._get_session_factory", side_effect=Exception("no db")):
            await _write_sentiment_feature("conn-1", ["AAPL"], "bullish")
