"""Unit tests for discord_redis_consumer.py (Phase 3 fixes).

Tests:
- test_stream_key_uses_connector_id       -- stream_key uses config["connector_id"]
- test_cursor_first_start_uses_zero_zero  -- no cursor file -> last_id = "0-0"
- test_cursor_loaded_on_restart           -- cursor file exists -> last_id from file
- test_cursor_saved_after_batch           -- after batch, stream_cursor.json written
- test_no_deadline_exit                   -- loop does not exit on its own (_shutdown gate)
- test_pending_signals_trim              -- >500 entries are trimmed to 500
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helper: reload the module fresh so module-level signal handlers and globals
# don't bleed between tests.
# ---------------------------------------------------------------------------
MODULE_PATH = "agents.templates.live-trader-v1.tools.discord_redis_consumer"


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
    # Point CURSOR_FILE at tmp_path so tests are isolated
    spec.loader.exec_module(mod)
    mod.CURSOR_FILE = tmp_path / "stream_cursor.json"
    return mod


# ---------------------------------------------------------------------------
# 3.1a — stream_key uses connector_id from config
# ---------------------------------------------------------------------------


class TestStreamKeyUsesConnectorId:
    def test_stream_key_uses_connector_id(self, tmp_path, monkeypatch):
        """Stream key must be built from config['connector_id'], not channel_id."""
        mod = _load_consumer(tmp_path)

        captured_keys: list[str] = []

        async def fake_xread(streams, count, block):
            captured_keys.extend(streams.keys())
            mod._shutdown = True  # stop after first iteration
            return []

        fake_redis = MagicMock()
        fake_redis.xread = AsyncMock(side_effect=fake_xread)
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

        with patch.dict(sys.modules, sys_modules_patch):
            mod._shutdown = False
            asyncio.run(mod.consume("test-connector-uuid", str(tmp_path / "out.json")))

        assert len(captured_keys) >= 1
        assert captured_keys[0] == "stream:channel:test-connector-uuid"
        assert "old-channel-id" not in captured_keys[0]

    def test_main_prefers_connector_id_from_config(self, tmp_path, monkeypatch):
        """main() resolves connector_id from config['connector_id'] first."""
        mod = _load_consumer(tmp_path)

        config = {"connector_id": "cfg-uuid", "channel_id": "old-cid"}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        resolved: list[str] = []

        async def fake_consume(connector_id, output_path):
            resolved.append(connector_id)
            return 0

        monkeypatch.setattr(mod, "consume", fake_consume)
        monkeypatch.setattr(mod, "_config", lambda path="config.json": config)

        with patch("sys.argv", ["prog", "--config", str(config_file), "--output", str(tmp_path / "out.json")]):
            mod.main()

        # connector_id from config should be used
        assert resolved and resolved[0] == "cfg-uuid"


# ---------------------------------------------------------------------------
# 3.1b — cursor persistence
# ---------------------------------------------------------------------------


class TestCursorPersistence:
    def test_cursor_first_start_uses_zero_zero(self, tmp_path):
        """When no cursor file exists, _load_cursor returns '0-0'."""
        mod = _load_consumer(tmp_path)
        stream_key = "stream:channel:abc"
        # Ensure cursor file doesn't exist
        assert not mod.CURSOR_FILE.exists()
        result = mod._load_cursor(stream_key)
        assert result == "0-0"

    def test_cursor_loaded_on_restart(self, tmp_path):
        """When stream_cursor.json exists with matching stream_key, last_id is read from it."""
        mod = _load_consumer(tmp_path)
        stream_key = "stream:channel:abc"
        mod.CURSOR_FILE.write_text(
            json.dumps({
                "stream_key": stream_key,
                "last_id": "1700000000000-5",
                "message_count": 42,
            })
        )
        result = mod._load_cursor(stream_key)
        assert result == "1700000000000-5"

    def test_cursor_wrong_stream_key_falls_back(self, tmp_path):
        """Cursor file with different stream_key falls back to '0-0'."""
        mod = _load_consumer(tmp_path)
        mod.CURSOR_FILE.write_text(
            json.dumps({
                "stream_key": "stream:channel:other",
                "last_id": "9999-0",
                "message_count": 1,
            })
        )
        result = mod._load_cursor("stream:channel:abc")
        assert result == "0-0"

    def test_cursor_saved_after_batch(self, tmp_path):
        """After consuming at least one message, stream_cursor.json is written with correct last_id."""
        mod = _load_consumer(tmp_path)

        call_count = 0

        async def fake_xread(streams, count, block):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Return one fake message
                return [
                    (
                        "stream:channel:test-id",
                        [("1700000001234-0", {"content": "buy $SPY", "author": "trader1", "channel_id": "test-id"})],
                    )
                ]
            # Stop the loop on second call
            mod._shutdown = True
            return []

        fake_redis = MagicMock()
        fake_redis.xread = AsyncMock(side_effect=fake_xread)
        fake_redis.aclose = AsyncMock()

        fake_aioredis = MagicMock()
        fake_aioredis.from_url = MagicMock(return_value=fake_redis)
        fake_redis_exceptions = MagicMock()
        fake_redis_exceptions.ConnectionError = ConnectionError

        with patch.dict(sys.modules, {
            "redis": MagicMock(asyncio=fake_aioredis, exceptions=fake_redis_exceptions),
            "redis.asyncio": fake_aioredis,
            "redis.exceptions": fake_redis_exceptions,
        }):
            mod._shutdown = False
            asyncio.run(mod.consume("test-id", str(tmp_path / "out.json")))

        assert mod.CURSOR_FILE.exists(), "stream_cursor.json should have been written"
        cursor_data = json.loads(mod.CURSOR_FILE.read_text())
        assert cursor_data["last_id"] == "1700000001234-0"
        assert cursor_data["stream_key"] == "stream:channel:test-id"


# ---------------------------------------------------------------------------
# 3.1c — no deadline exit
# ---------------------------------------------------------------------------


class TestNoDeadlineExit:
    def test_no_deadline_exit(self, tmp_path):
        """Consumer loop does not exit on its own; it exits only when _shutdown is True."""
        mod = _load_consumer(tmp_path)

        call_count = 0

        async def fake_xread(streams, count, block):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                # After 3 empty polls, set shutdown from outside -- simulating SIGTERM
                mod._shutdown = True
            return []

        fake_redis = MagicMock()
        fake_redis.xread = AsyncMock(side_effect=fake_xread)
        fake_redis.aclose = AsyncMock()

        fake_aioredis = MagicMock()
        fake_aioredis.from_url = MagicMock(return_value=fake_redis)
        fake_redis_exceptions = MagicMock()
        fake_redis_exceptions.ConnectionError = ConnectionError

        with patch.dict(sys.modules, {
            "redis": MagicMock(asyncio=fake_aioredis, exceptions=fake_redis_exceptions),
            "redis.asyncio": fake_aioredis,
            "redis.exceptions": fake_redis_exceptions,
        }):
            mod._shutdown = False
            asyncio.run(mod.consume("test-id", str(tmp_path / "out.json")))

        # Loop ran at least 3 times before shutdown -- not a deadline-based exit
        assert call_count >= 3, f"Expected >=3 xread calls, got {call_count}"


# ---------------------------------------------------------------------------
# 3.1e — pending_signals.json trim to 500
# ---------------------------------------------------------------------------


class TestPendingSignalsTrim:
    def test_pending_signals_trim(self, tmp_path):
        """When pending_signals.json exceeds 500 entries, it is trimmed to the most recent 500."""
        mod = _load_consumer(tmp_path)

        out_file = tmp_path / "pending_signals.json"
        # Pre-seed with 510 entries
        seed = [{"content": f"msg {i}", "stream_id": f"{i}-0"} for i in range(510)]
        out_file.write_text(json.dumps(seed))

        call_count = 0

        async def fake_xread(streams, count, block):
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

        fake_redis = MagicMock()
        fake_redis.xread = AsyncMock(side_effect=fake_xread)
        fake_redis.aclose = AsyncMock()

        fake_aioredis = MagicMock()
        fake_aioredis.from_url = MagicMock(return_value=fake_redis)
        fake_redis_exceptions = MagicMock()
        fake_redis_exceptions.ConnectionError = ConnectionError

        with patch.dict(sys.modules, {
            "redis": MagicMock(asyncio=fake_aioredis, exceptions=fake_redis_exceptions),
            "redis.asyncio": fake_aioredis,
            "redis.exceptions": fake_redis_exceptions,
        }):
            mod._shutdown = False
            asyncio.run(mod.consume("trim-test", str(out_file)))

        result = json.loads(out_file.read_text())
        assert len(result) == 500, f"Expected 500 entries after trim, got {len(result)}"
        # Most recent entry should be the newly appended one
        assert result[-1]["stream_id"] == "9999999999999-0"
