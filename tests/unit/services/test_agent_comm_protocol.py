from unittest.mock import AsyncMock

import pytest

from services.agent_comm.src.protocol import (
    MessageEnvelope,
    MessageType,
    ProtocolHandler,
)


class TestMessageType:
    def test_all_message_types(self):
        assert MessageType.REQUEST == "REQUEST"
        assert MessageType.RESPONSE == "RESPONSE"
        assert MessageType.BROADCAST == "BROADCAST"
        assert MessageType.SUBSCRIBE == "SUBSCRIBE"
        assert MessageType.CONSENSUS == "CONSENSUS"

    def test_message_type_count(self):
        assert len(MessageType) == 5


class TestMessageEnvelope:
    def test_creation_with_defaults(self):
        env = MessageEnvelope(
            from_agent="agent-a",
            to_agent="agent-b",
            msg_type=MessageType.REQUEST,
            intent="get_price",
        )
        assert env.from_agent == "agent-a"
        assert env.to_agent == "agent-b"
        assert env.msg_type == MessageType.REQUEST
        assert env.intent == "get_price"
        assert isinstance(env.id, str)
        assert env.data == {}

    def test_to_dict_roundtrip(self):
        env = MessageEnvelope(
            from_agent="a",
            to_agent="b",
            msg_type=MessageType.BROADCAST,
            intent="market_update",
            data={"price": 100.0},
        )
        d = env.to_dict()
        restored = MessageEnvelope.from_dict(d)
        assert restored.from_agent == env.from_agent
        assert restored.intent == env.intent
        assert restored.data == env.data
        assert restored.msg_type == MessageType.BROADCAST

    def test_from_dict_with_minimal_fields(self):
        d = {
            "from_agent": "x",
            "msg_type": "REQUEST",
            "intent": "ping",
        }
        env = MessageEnvelope.from_dict(d)
        assert env.from_agent == "x"
        assert env.to_agent is None


class TestProtocolHandler:
    @pytest.mark.asyncio
    async def test_broadcast_sends_envelope(self):
        sent = []
        handler = ProtocolHandler("agent-1", send_fn=AsyncMock(side_effect=lambda e: sent.append(e)))
        await handler.broadcast("alert", {"level": "high"})
        assert len(sent) == 1
        assert sent[0].msg_type == MessageType.BROADCAST
        assert sent[0].to_agent is None

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self):
        received = []
        handler = ProtocolHandler("agent-1", send_fn=AsyncMock())
        handler.subscribe("price_update", AsyncMock(side_effect=lambda e: received.append(e)))
        await handler.publish("price_update", {"ticker": "AAPL"})
        assert len(received) == 1
        assert received[0].intent == "price_update"

    @pytest.mark.asyncio
    async def test_handle_incoming_response_resolves_future(self):
        import asyncio
        send_fn = AsyncMock()
        handler = ProtocolHandler("agent-1", send_fn=send_fn)
        future = asyncio.get_event_loop().create_future()
        handler._pending_responses["corr-123"] = future

        response_env = MessageEnvelope(
            from_agent="agent-2",
            to_agent="agent-1",
            msg_type=MessageType.RESPONSE,
            intent="get_price",
            correlation_id="corr-123",
        )
        await handler.handle_incoming(response_env)
        assert future.done()
        assert future.result().from_agent == "agent-2"
