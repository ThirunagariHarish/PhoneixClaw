from unittest.mock import AsyncMock

import pytest

from shared.kafka_utils.dlq import DeadLetterQueue


class TestDeadLetterQueue:
    @pytest.mark.asyncio
    async def test_sends_to_dlq_topic(self):
        producer = AsyncMock()
        dlq = DeadLetterQueue(producer)
        msg = {"trade_id": "t1", "ticker": "SPX"}
        await dlq.send("parsed-trades", msg, "Parse error", "PARSE_ERROR")
        producer.send.assert_awaited_once()
        call_args = producer.send.call_args
        assert call_args.args[0] == "dlq-parsed-trades"
        value = call_args.kwargs.get("value") or call_args.args[1]
        assert value["original_topic"] == "parsed-trades"
        assert value["error"] == "Parse error"

    @pytest.mark.asyncio
    async def test_handles_producer_failure(self):
        producer = AsyncMock()
        producer.send.side_effect = Exception("Kafka down")
        dlq = DeadLetterQueue(producer)
        await dlq.send("raw-messages", {}, "test error")  # should not raise
