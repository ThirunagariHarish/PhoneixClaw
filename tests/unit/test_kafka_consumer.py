from unittest.mock import AsyncMock, patch

import pytest

from shared.kafka_utils.consumer import KafkaConsumerWrapper


class TestKafkaConsumerWrapper:
    def test_not_started_initially(self):
        consumer = KafkaConsumerWrapper("test-topic", "test-group")
        assert not consumer.is_started

    @pytest.mark.asyncio
    async def test_consume_before_start_raises(self):
        consumer = KafkaConsumerWrapper("test-topic", "test-group")
        with pytest.raises(RuntimeError, match="not started"):
            await consumer.consume(AsyncMock())

    @pytest.mark.asyncio
    async def test_start_creates_consumer(self):
        consumer = KafkaConsumerWrapper("test-topic", "test-group")
        mock_aio = AsyncMock()
        with patch("shared.kafka_utils.consumer.AIOKafkaConsumer", return_value=mock_aio):
            await consumer.start()
            assert consumer.is_started
            mock_aio.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_shuts_down(self):
        consumer = KafkaConsumerWrapper("test-topic", "test-group")
        mock_aio = AsyncMock()
        with patch("shared.kafka_utils.consumer.AIOKafkaConsumer", return_value=mock_aio):
            await consumer.start()
            await consumer.stop()
            mock_aio.stop.assert_awaited_once()
