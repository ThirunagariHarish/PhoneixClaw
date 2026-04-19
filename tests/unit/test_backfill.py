"""Unit tests for tools.backfill module.

Tests:
- Rate limiter leaky bucket behavior
- 429 handling with Retry-After parsing
- Conservative mode after 3 consecutive 429s
- Checkpoint writes after batch commit
- Idempotency (duplicate message skipping)
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from shared.discord_utils.rate_limiter import DiscordRateLimiter
from tools.backfill import BackfillCheckpoint, DiscordBackfiller


class TestDiscordRateLimiter:
    """Test rate limiter behavior."""

    @pytest.mark.asyncio
    async def test_leaky_bucket_enforces_min_interval(self):
        """Rate limiter should enforce minimum 20ms interval between requests."""
        limiter = DiscordRateLimiter()
        channel_id = "123456789"

        start = asyncio.get_event_loop().time()
        await limiter.wait_if_needed(channel_id)
        await limiter.wait_if_needed(channel_id)
        elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000

        # Second call should wait ~20ms
        assert elapsed_ms >= limiter.MIN_INTERVAL_MS
        assert limiter._channels[channel_id].total_requests == 2

    @pytest.mark.asyncio
    async def test_handle_429_with_retry_after(self):
        """429 handler should respect Retry-After header + jitter."""
        limiter = DiscordRateLimiter()
        channel_id = "123456789"

        start = asyncio.get_event_loop().time()
        await limiter.handle_429(channel_id, retry_after=0.05)  # 50ms
        elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000

        # Should wait retry_after (50ms) + jitter (1000ms) = ~1050ms
        expected_min = (0.05 * 1000) + limiter.JITTER_MS
        assert elapsed_ms >= expected_min * 0.9  # Allow 10% margin
        assert limiter._channels[channel_id].consecutive_429_count == 1
        assert limiter._channels[channel_id].total_429s == 1

    @pytest.mark.asyncio
    async def test_consecutive_429_triggers_conservative_mode(self):
        """After 3 consecutive 429s, limiter should enter conservative mode."""
        limiter = DiscordRateLimiter()
        channel_id = "123456789"

        # First two 429s
        await limiter.handle_429(channel_id, retry_after=0.01)
        await limiter.handle_429(channel_id, retry_after=0.01)
        assert not limiter._channels[channel_id].conservative_mode

        # Third 429 triggers conservative mode
        await limiter.handle_429(channel_id, retry_after=0.01)
        assert limiter._channels[channel_id].conservative_mode
        assert limiter._channels[channel_id].consecutive_429_count == 3

    @pytest.mark.asyncio
    async def test_mark_success_resets_consecutive_counter(self):
        """Successful request should reset consecutive 429 counter."""
        limiter = DiscordRateLimiter()
        channel_id = "123456789"

        await limiter.handle_429(channel_id)
        await limiter.handle_429(channel_id)
        assert limiter._channels[channel_id].consecutive_429_count == 2

        limiter.mark_success(channel_id)
        assert limiter._channels[channel_id].consecutive_429_count == 0
        assert not limiter._channels[channel_id].conservative_mode

    def test_get_stats(self):
        """Stats should return accurate counters."""
        limiter = DiscordRateLimiter()
        channel_id = "123456789"

        stats = limiter.get_stats(channel_id)
        assert stats["total_requests"] == 0
        assert stats["total_429s"] == 0


class TestBackfillCheckpoint:
    """Test checkpoint save/load logic."""

    def test_save_and_load(self, tmp_path: Path):
        """Checkpoint should persist and restore state."""
        checkpoint_path = tmp_path / "checkpoint.json"
        cp = BackfillCheckpoint(checkpoint_path)

        data = {
            "run_id": str(uuid.uuid4()),
            "messages_imported": 500,
            "status": "in_progress",
        }
        cp.save(data)

        # Load in new instance
        cp2 = BackfillCheckpoint(checkpoint_path)
        loaded = cp2.load()
        assert loaded["run_id"] == data["run_id"]
        assert loaded["messages_imported"] == 500
        assert loaded["status"] == "in_progress"

    def test_update_adds_timestamp(self, tmp_path: Path):
        """Update should add last_checkpoint_at timestamp."""
        checkpoint_path = tmp_path / "checkpoint.json"
        cp = BackfillCheckpoint(checkpoint_path)

        cp.save({"run_id": str(uuid.uuid4())})
        cp.update(messages_imported=100)

        loaded = cp.load()
        assert "last_checkpoint_at" in loaded
        assert loaded["messages_imported"] == 100


class TestDiscordBackfiller:
    """Test backfill orchestration logic."""

    @pytest.fixture
    def mock_connector(self):
        """Mock connector with encrypted credentials."""
        connector = Mock()
        connector.id = uuid.uuid4()
        connector.type = "discord"
        connector.credentials_encrypted = json.dumps({"bot_token": "mock-token"})
        return connector

    @pytest.mark.asyncio
    async def test_idempotency_skips_duplicate_messages(self, tmp_path: Path, mock_connector):
        """Backfiller should skip messages that already exist in DB."""
        # This is a minimal smoke test; integration test covers full flow
        checkpoint_path = tmp_path / "checkpoint.json"

        with patch("tools.backfill.create_engine") as mock_engine, \
             patch("tools.backfill.Session") as mock_session_cls:

            # Mock session that says message exists
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = uuid.uuid4()  # EXISTS

            # Mock connector load
            with patch.object(DiscordBackfiller, "_load_connector", return_value=mock_connector), \
                 patch.object(DiscordBackfiller, "_decrypt_token", return_value="mock-token"):

                backfiller = DiscordBackfiller(
                    connector_id=mock_connector.id,
                    channel_id="987654321",
                    db_url="postgresql://localhost/test",
                    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
                    batch_size=500,
                    checkpoint_path=checkpoint_path,
                    resume=False,
                )

                # Test duplicate check
                is_dup = backfiller._is_duplicate("msg-123", mock_session)
                assert is_dup is True

    @pytest.mark.asyncio
    async def test_checkpoint_written_after_batch(self, tmp_path: Path, mock_connector):
        """Checkpoint should be updated after each batch commit."""
        checkpoint_path = tmp_path / "checkpoint.json"

        with patch("tools.backfill.create_engine") as mock_engine, \
             patch("tools.backfill.Session") as mock_session_cls, \
             patch.object(DiscordBackfiller, "_load_connector", return_value=mock_connector), \
             patch.object(DiscordBackfiller, "_decrypt_token", return_value="mock-token"):

            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = None  # NOT duplicate

            backfiller = DiscordBackfiller(
                connector_id=mock_connector.id,
                channel_id="987654321",
                db_url="postgresql://localhost/test",
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
                batch_size=500,
                checkpoint_path=checkpoint_path,
                resume=False,
            )

            backfiller._init_checkpoint()

            # Add messages to batch
            for i in range(3):
                backfiller.current_batch.append({
                    "connector_id": mock_connector.id,
                    "channel": "987654321",
                    "author": "test",
                    "content": f"msg {i}",
                    "message_type": "unknown",
                    "tickers_mentioned": [],
                    "raw_data": {},
                    "platform_message_id": f"msg-{i}",
                    "posted_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                })
                backfiller.last_message_id = f"msg-{i}"

            backfiller._flush_batch(mock_session)

            # Verify checkpoint updated
            cp = BackfillCheckpoint(checkpoint_path)
            loaded = cp.load()
            assert loaded["messages_imported"] == 3
            assert loaded["batches_committed"] == 1
            assert loaded["last_message_id"] == "msg-2"

    @pytest.mark.asyncio
    async def test_429_handling_in_fetch_page(self, tmp_path: Path, mock_connector):
        """fetch_page should retry after 429 response."""
        checkpoint_path = tmp_path / "checkpoint.json"

        with patch("tools.backfill.create_engine"), \
             patch.object(DiscordBackfiller, "_load_connector", return_value=mock_connector), \
             patch.object(DiscordBackfiller, "_decrypt_token", return_value="mock-token"):

            backfiller = DiscordBackfiller(
                connector_id=mock_connector.id,
                channel_id="987654321",
                db_url="postgresql://localhost/test",
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
                batch_size=500,
                checkpoint_path=checkpoint_path,
                resume=False,
            )

            # Mock httpx client
            mock_client = AsyncMock()
            mock_response_429 = Mock()
            mock_response_429.status_code = 429
            mock_response_429.json.return_value = {"retry_after": 0.01}

            mock_response_200 = Mock()
            mock_response_200.status_code = 200
            mock_response_200.json.return_value = []

            # First call returns 429, second returns 200
            mock_client.get.side_effect = [mock_response_429, mock_response_200]

            result = await backfiller._fetch_page(mock_client, {"Authorization": "Bot mock-token"})

            # Should have retried and returned empty list
            assert result == []
            assert mock_client.get.call_count == 2  # Initial + retry
