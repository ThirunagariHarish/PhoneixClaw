"""Unit tests for discord_redis_consumer.py — Redis Consumer Group based.

Tests:
- test_stream_key_uses_connector_id       -- stream_key uses config["connector_id"]
- test_ensure_consumer_group_called       -- _ensure_consumer_group called on startup
- test_xack_called_after_batch            -- xack called with batch IDs after processing
- test_no_deadline_exit                   -- loop does not exit on its own (_shutdown gate)
- test_pending_signals_trim               -- >500 entries are trimmed to 500
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _load_consumer(tmp_path: Path):
    """Import discord_redis_consumer from its filesystem path, isolated in tmp_path."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "discord_redis_consumer",
        Path(__file__).parent.parent.parent
        / "agents"
        / "templates"
        / "live-trader-v1"
        / "tools"
        / "discord_redis_consumer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_mocks(mod, xreadgroup_side_effect):
    """Build fake redis and aioredis mocks with xreadgroup side effect."""
    fake_redis = MagicMock()
    fake_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)
    fake_redis.xack = AsyncMock()
    fake_redis.xgroup_create = AsyncMock()
    fake_redis.aclose = AsyncMock()

    fake_aioredis = MagicMock()
    fake_aioredis.from_url = MagicMock(return_value=fake_redis)

    fake_redis_exceptions = MagicMock()
    fake_redis_exceptions.ConnectionError = ConnectionError

    sys_modules_patch = {
        "redis": MagicMock(asyncio=fake_aioredis, exceptions=fake_redis_exceptions),
        "redis.asyncio": fake_aioredis,
        "redis.exceptions": fake_redis_exceptions,
    }
    return fake_redis, fake_aioredis, sys_modules_patch


class TestStreamKeyUsesConnectorId:
    def test_stream_key_uses_connector_id(self, tmp_path):
        """Stream key must be built from config['connector_id'], not channel_id."""
        mod = _load_consumer(tmp_path)
        captured_keys: list[str] = []

        async def fake_xreadgroup(group, consumer, streams, count, block):
            captured_keys.extend(streams.keys())
            mod._shutdown = True
            return []

        fake_redis, _, sys_modules_patch = _make_mocks(mod, fake_xreadgroup)

        with patch.dict(sys.modules, sys_modules_patch):
            mod._shutdown = False
            asyncio.run(mod.consume("test-connector-uuid", str(tmp_path / "out.json")))

        assert len(captured_keys) >= 1
        assert captured_keys[0] == "stream:channel:test-connector-uuid"

    def test_main_prefers_connector_id_from_config(self, tmp_path, monkeypatch):
        """main() resolves connector_id from config['connector_id'] first."""
        mod = _load_consumer(tmp_path)

        config = {"connector_id": "cfg-uuid", "channel_id": "old-cid"}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        resolved: list[str] = []

        async def fake_consume(connector_id, output_path, redis_url=""):
            resolved.append(connector_id)
            return 0

        monkeypatch.setattr(mod, "consume", fake_consume)
        monkeypatch.setattr(mod, "_config", lambda path="config.json": config)

        with patch("sys.argv", ["prog", "--config", str(config_file), "--output", str(tmp_path / "out.json")]):
            mod.main()

        assert resolved and resolved[0] == "cfg-uuid"


class TestConsumerGroupSetup:
    def test_ensure_consumer_group_called(self, tmp_path):
        """_ensure_consumer_group must be called before reading messages."""
        mod = _load_consumer(tmp_path)
        group_created = []

        async def fake_xreadgroup(group, consumer, streams, count, block):
            mod._shutdown = True
            return []

        fake_redis, _, sys_modules_patch = _make_mocks(mod, fake_xreadgroup)

        original_xgroup_create = fake_redis.xgroup_create

        async def tracking_xgroup_create(*args, **kwargs):
            group_created.append((args, kwargs))
            return await original_xgroup_create(*args, **kwargs)

        fake_redis.xgroup_create = AsyncMock(side_effect=tracking_xgroup_create)

        with patch.dict(sys.modules, sys_modules_patch):
            mod._shutdown = False
            asyncio.run(mod.consume("test-id", str(tmp_path / "out.json")))

        assert len(group_created) >= 1
        call_args, call_kwargs = group_created[0]
        assert call_args[0] == "stream:channel:test-id"
        assert call_args[1] == "phoenix-agents"
        assert call_kwargs.get("id") == "$"
        assert call_kwargs.get("mkstream") is True

    def test_xack_called_after_batch(self, tmp_path):
        """After consuming a batch, xack must be called with the message IDs."""
        mod = _load_consumer(tmp_path)
        call_count = 0

        async def fake_xreadgroup(group, consumer, streams, count, block):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "stream:channel:test-id",
                        [
                            ("1700000001234-0", {"content": "buy $SPY", "author": "t1", "channel_id": "test-id"}),
                            ("1700000001235-0", {"content": "sell $AAPL", "author": "t2", "channel_id": "test-id"}),
                        ],
                    )
                ]
            mod._shutdown = True
            return []

        fake_redis, _, sys_modules_patch = _make_mocks(mod, fake_xreadgroup)

        with patch.dict(sys.modules, sys_modules_patch):
            mod._shutdown = False
            asyncio.run(mod.consume("test-id", str(tmp_path / "out.json")))

        fake_redis.xack.assert_called_once()
        ack_args = fake_redis.xack.call_args[0]
        assert ack_args[0] == "stream:channel:test-id"
        assert ack_args[1] == "phoenix-agents"
        assert "1700000001234-0" in ack_args[2:]
        assert "1700000001235-0" in ack_args[2:]

    def test_consumer_name_uses_connector_id(self, tmp_path):
        """Consumer name must be 'agent-{connector_id}'."""
        mod = _load_consumer(tmp_path)
        captured_consumers: list[str] = []

        async def fake_xreadgroup(group, consumer, streams, count, block):
            captured_consumers.append(consumer)
            mod._shutdown = True
            return []

        fake_redis, _, sys_modules_patch = _make_mocks(mod, fake_xreadgroup)

        with patch.dict(sys.modules, sys_modules_patch):
            mod._shutdown = False
            asyncio.run(mod.consume("my-connector", str(tmp_path / "out.json")))

        assert captured_consumers[0] == "agent-my-connector"


class TestNoDeadlineExit:
    def test_no_deadline_exit(self, tmp_path):
        """Consumer loop does not exit on its own; it exits only when _shutdown is True."""
        mod = _load_consumer(tmp_path)
        call_count = 0

        async def fake_xreadgroup(group, consumer, streams, count, block):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                mod._shutdown = True
            return []

        _, _, sys_modules_patch = _make_mocks(mod, fake_xreadgroup)

        with patch.dict(sys.modules, sys_modules_patch):
            mod._shutdown = False
            asyncio.run(mod.consume("test-id", str(tmp_path / "out.json")))

        assert call_count >= 3, f"Expected >=3 xreadgroup calls, got {call_count}"


class TestPendingSignalsTrim:
    def test_pending_signals_trim(self, tmp_path):
        """When pending_signals.json exceeds 500 entries, it is trimmed to the most recent 500."""
        mod = _load_consumer(tmp_path)

        out_file = tmp_path / "pending_signals.json"
        seed = [{"content": f"msg {i}", "stream_id": f"{i}-0"} for i in range(510)]
        out_file.write_text(json.dumps(seed))

        call_count = 0

        async def fake_xreadgroup(group, consumer, streams, count, block):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "stream:channel:trim-test",
                        [("9999999999999-0", {"content": "new signal", "author": "a", "channel_id": "trim-test"})],
                    )
                ]
            mod._shutdown = True
            return []

        _, _, sys_modules_patch = _make_mocks(mod, fake_xreadgroup)

        with patch.dict(sys.modules, sys_modules_patch):
            mod._shutdown = False
            asyncio.run(mod.consume("trim-test", str(out_file)))

        result = json.loads(out_file.read_text())
        assert len(result) == 500, f"Expected 500 entries after trim, got {len(result)}"
        assert result[-1]["stream_id"] == "9999999999999-0"
