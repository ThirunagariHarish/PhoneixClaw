from unittest.mock import AsyncMock, patch

import pytest

from shared.kafka_utils.producer import KafkaProducerWrapper


class TestKafkaProducerWrapper:
    def test_not_started_initially(self):
        producer = KafkaProducerWrapper()
        assert not producer.is_started

    @pytest.mark.asyncio
    async def test_send_before_start_raises(self):
        producer = KafkaProducerWrapper()
        with pytest.raises(RuntimeError, match="not started"):
            await producer.send("topic", {"key": "value"})

    @pytest.mark.asyncio
    async def test_send_and_wait_before_start_raises(self):
        producer = KafkaProducerWrapper()
        with pytest.raises(RuntimeError, match="not started"):
            await producer.send_and_wait("topic", {"key": "value"})

    @pytest.mark.asyncio
    async def test_start_creates_producer(self):
        producer = KafkaProducerWrapper()
        mock_aio = AsyncMock()
        with patch("shared.kafka_utils.producer.AIOKafkaProducer", return_value=mock_aio):
            await producer.start()
            assert producer.is_started
            mock_aio.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_delegates_to_producer(self):
        producer = KafkaProducerWrapper()
        mock_aio = AsyncMock()
        with patch("shared.kafka_utils.producer.AIOKafkaProducer", return_value=mock_aio):
            await producer.start()
            await producer.send("raw-messages", {"data": "test"}, key="msg-1")
            mock_aio.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_shuts_down(self):
        producer = KafkaProducerWrapper()
        mock_aio = AsyncMock()
        with patch("shared.kafka_utils.producer.AIOKafkaProducer", return_value=mock_aio):
            await producer.start()
            await producer.stop()
            mock_aio.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_with_headers(self):
        producer = KafkaProducerWrapper()
        mock_aio = AsyncMock()
        with patch("shared.kafka_utils.producer.AIOKafkaProducer", return_value=mock_aio):
            await producer.start()
            headers = [("user_id", b"abc-123")]
            await producer.send("topic", {"msg": "test"}, headers=headers)
            call_kwargs = mock_aio.send.call_args
            assert call_kwargs.kwargs.get("headers") == headers
