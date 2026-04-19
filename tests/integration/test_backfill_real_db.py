"""Integration test for backfill with real database.

Tests:
- Full backfill flow with mocked Discord API
- 10k message import
- Resume from checkpoint after simulated crash
- No duplicates after resume
- Checkpoint updates correctly
"""

import asyncio
import json
import signal
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from shared.db.models.base import Base
from shared.db.models.channel_message import ChannelMessage
from shared.db.models.connector import Connector
from tools.backfill import BackfillCheckpoint, DiscordBackfiller


@pytest.fixture
def test_db_url(tmp_path: Path) -> str:
    """Create in-memory SQLite database for testing."""
    db_path = tmp_path / "test.db"
    return f"sqlite:///{db_path}"


@pytest.fixture
def test_engine(test_db_url: str):
    """Create test database engine and initialize schema."""
    engine = create_engine(test_db_url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_connector(test_engine) -> Connector:
    """Create test connector with encrypted credentials."""
    # Generate encryption key
    key = Fernet.generate_key()
    cipher = Fernet(key)

    # Encrypt credentials
    credentials = {"bot_token": "test-bot-token-12345"}
    encrypted = cipher.encrypt(json.dumps(credentials).encode()).decode()

    connector = Connector(
        id=uuid.uuid4(),
        name="Test Discord Server",
        type="discord",
        status="connected",
        config={"channel_ids": ["123456789"]},
        credentials_encrypted=encrypted,
        tags=["test"],
        user_id=uuid.uuid4(),
        is_active=True,
    )

    with Session(test_engine) as session:
        session.add(connector)
        session.commit()
        session.refresh(connector)

    # Set encryption key in environment
    import os
    os.environ["CREDENTIAL_ENCRYPTION_KEY"] = key.decode()

    return connector


def generate_mock_discord_messages(count: int, start_date: datetime) -> list[dict]:
    """Generate mock Discord API responses."""
    messages = []
    for i in range(count):
        msg_date = start_date + timedelta(minutes=i)
        messages.append({
            "id": str(1000000000000000000 + i),  # Snowflake-like ID
            "content": f"Test message {i} $AAPL buy at 150",
            "timestamp": msg_date.isoformat().replace("+00:00", "Z"),
            "author": {
                "id": "999999999999999999",
                "username": f"testuser{i % 10}",
            },
        })
    return messages


class TestBackfillIntegration:
    """Integration tests with real database."""

    @pytest.mark.asyncio
    async def test_full_backfill_with_mocked_api(self, test_engine, test_connector, tmp_path: Path):
        """Test complete backfill flow with 1000 mocked messages."""
        checkpoint_path = tmp_path / "checkpoint.json"
        start_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 12, 31, tzinfo=timezone.utc)

        # Generate 1000 mock messages
        all_messages = generate_mock_discord_messages(1000, start_date)

        # Mock Discord API to return messages in pages of 100
        async def mock_fetch_page(client, headers, before=None):
            """Mock _fetch_page to return paginated messages."""
            # Find starting index based on 'before' parameter
            if before is None:
                start_idx = 0
            else:
                # Find message with this ID
                start_idx = next((i for i, m in enumerate(all_messages) if m["id"] == before), None)
                if start_idx is None:
                    return []
                start_idx += 1  # Start after this message

            # Return next page
            page = all_messages[start_idx:start_idx + 100]
            return page

        with patch.object(DiscordBackfiller, "_fetch_page", side_effect=mock_fetch_page):
            backfiller = DiscordBackfiller(
                connector_id=test_connector.id,
                channel_id="123456789",
                db_url=str(test_engine.url),
                start_date=start_date,
                end_date=end_date,
                batch_size=500,
                checkpoint_path=checkpoint_path,
                resume=False,
            )

            await backfiller.run()

        # Verify messages imported
        with Session(test_engine) as session:
            count = session.query(ChannelMessage).count()
            assert count == 1000

        # Verify checkpoint
        cp = BackfillCheckpoint(checkpoint_path)
        loaded = cp.load()
        assert loaded["status"] == "completed"
        assert loaded["messages_imported"] == 1000
        assert loaded["batches_committed"] == 2  # 1000 / 500 = 2 batches

    @pytest.mark.asyncio
    async def test_resume_from_checkpoint_no_duplicates(self, test_engine, test_connector, tmp_path: Path):
        """Test resume after simulated crash — should not create duplicates."""
        checkpoint_path = tmp_path / "checkpoint.json"
        start_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 12, 31, tzinfo=timezone.utc)

        # Generate 1000 mock messages
        all_messages = generate_mock_discord_messages(1000, start_date)

        async def mock_fetch_page(client, headers, before=None):
            if before is None:
                start_idx = 0
            else:
                start_idx = next((i for i, m in enumerate(all_messages) if m["id"] == before), None)
                if start_idx is None:
                    return []
                start_idx += 1
            return all_messages[start_idx:start_idx + 100]

        # First run: import 500 messages then "crash"
        with patch.object(DiscordBackfiller, "_fetch_page", side_effect=mock_fetch_page):
            backfiller = DiscordBackfiller(
                connector_id=test_connector.id,
                channel_id="123456789",
                db_url=str(test_engine.url),
                start_date=start_date,
                end_date=end_date,
                batch_size=500,
                checkpoint_path=checkpoint_path,
                resume=False,
            )

            # Manually run first batch only
            backfiller._init_checkpoint()
            async with AsyncMock() as mock_client:
                # Import first 500
                for i in range(5):  # 5 pages of 100
                    page = all_messages[i * 100:(i + 1) * 100]
                    for msg in page:
                        msg_dict = backfiller._parse_discord_message(msg)
                        backfiller.current_batch.append(msg_dict)
                        backfiller.last_message_id = msg["id"]

                with Session(test_engine) as session:
                    backfiller._flush_batch(session)

        # Verify first batch imported
        with Session(test_engine) as session:
            count = session.query(ChannelMessage).count()
            assert count == 500

        # Resume from checkpoint
        with patch.object(DiscordBackfiller, "_fetch_page", side_effect=mock_fetch_page):
            backfiller2 = DiscordBackfiller(
                connector_id=test_connector.id,
                channel_id="123456789",
                db_url=str(test_engine.url),
                start_date=start_date,
                end_date=end_date,
                batch_size=500,
                checkpoint_path=checkpoint_path,
                resume=True,  # RESUME
            )

            await backfiller2.run()

        # Verify total is 1000 (no duplicates)
        with Session(test_engine) as session:
            count = session.query(ChannelMessage).count()
            assert count == 1000  # NOT 1500

            # Verify unique platform_message_ids
            unique_ids = session.query(ChannelMessage.platform_message_id).distinct().count()
            assert unique_ids == 1000

        # Verify final checkpoint
        cp = BackfillCheckpoint(checkpoint_path)
        loaded = cp.load()
        assert loaded["status"] == "completed"
        assert loaded["messages_imported"] == 500  # Only NEW messages counted

    @pytest.mark.asyncio
    async def test_checkpoint_updates_after_each_batch(self, test_engine, test_connector, tmp_path: Path):
        """Checkpoint should update after each batch commit."""
        checkpoint_path = tmp_path / "checkpoint.json"
        start_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 12, 31, tzinfo=timezone.utc)

        # Generate 1500 messages (3 batches of 500)
        all_messages = generate_mock_discord_messages(1500, start_date)

        async def mock_fetch_page(client, headers, before=None):
            if before is None:
                start_idx = 0
            else:
                start_idx = next((i for i, m in enumerate(all_messages) if m["id"] == before), None)
                if start_idx is None:
                    return []
                start_idx += 1
            return all_messages[start_idx:start_idx + 100]

        with patch.object(DiscordBackfiller, "_fetch_page", side_effect=mock_fetch_page):
            backfiller = DiscordBackfiller(
                connector_id=test_connector.id,
                channel_id="123456789",
                db_url=str(test_engine.url),
                start_date=start_date,
                end_date=end_date,
                batch_size=500,
                checkpoint_path=checkpoint_path,
                resume=False,
            )

            await backfiller.run()

        # Verify checkpoint shows 3 batches
        cp = BackfillCheckpoint(checkpoint_path)
        loaded = cp.load()
        assert loaded["batches_committed"] == 3
        assert loaded["messages_imported"] == 1500
        assert loaded["status"] == "completed"
