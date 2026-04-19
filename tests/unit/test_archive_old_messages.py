"""Unit tests for archive_old_messages tool."""

import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from shared.db.models.base import Base
from shared.db.models.channel_message import ChannelMessage
from tools.archive_old_messages import archive_messages


@pytest.fixture
def in_memory_db():
    """Create a test database for testing.

    Uses PostgreSQL test DB if available (for JSONB support),
    falls back to SQLite with JSON columns.
    """
    db_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://phoenixtrader:localdev@localhost:5432/phoenixtrader_test"
    )

    try:
        engine = create_engine(db_url, echo=False)
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        Base.metadata.create_all(engine)
        yield engine
        Base.metadata.drop_all(engine)
        engine.dispose()
    except Exception:
        # Fallback to SQLite with JSON instead of JSONB
        pytest.skip("PostgreSQL test database not available — archive tests require JSONB support")


@pytest.fixture
def seeded_messages(in_memory_db):
    """Seed database with test messages across different dates."""
    with Session(in_memory_db) as session:
        connector_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # 10 old messages (30 days ago)
        old_date = now - timedelta(days=30)
        old_messages = []
        for i in range(10):
            msg = ChannelMessage(
                id=uuid.uuid4(),
                connector_id=connector_id,
                channel="test-channel",
                channel_id_snowflake="1234567890",
                author=f"user{i}",
                content=f"Old message {i}",
                message_type="info",
                tickers_mentioned=["SPY"],
                raw_data={"test": True},
                platform_message_id=f"old_{i}",
                posted_at=old_date - timedelta(hours=i),
            )
            old_messages.append(msg)
            session.add(msg)

        # 5 recent messages (5 days ago)
        recent_date = now - timedelta(days=5)
        recent_messages = []
        for i in range(5):
            msg = ChannelMessage(
                id=uuid.uuid4(),
                connector_id=connector_id,
                channel="test-channel",
                channel_id_snowflake="1234567890",
                author=f"user{i}",
                content=f"Recent message {i}",
                message_type="info",
                tickers_mentioned=["QQQ"],
                raw_data={"test": True},
                platform_message_id=f"recent_{i}",
                posted_at=recent_date - timedelta(hours=i),
            )
            recent_messages.append(msg)
            session.add(msg)

        session.commit()

        yield {
            "connector_id": connector_id,
            "old_messages": old_messages,
            "recent_messages": recent_messages,
        }


def test_archive_old_messages_no_deletion(in_memory_db, seeded_messages):
    """Test archiving old messages without deletion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "archive.jsonl"
        before_date = datetime.now(timezone.utc) - timedelta(days=7)

        count = archive_messages(
            db_url=str(in_memory_db.url),
            before_date=before_date,
            channel_id=None,
            output_path=output_path,
            delete_after_archive=False,
        )

        # Should archive 10 old messages
        assert count == 10
        assert output_path.exists()

        # Verify JSONL content
        with open(output_path) as f:
            lines = f.readlines()
        assert len(lines) == 10

        # Parse first line
        msg = json.loads(lines[0])
        assert "id" in msg
        assert "content" in msg
        assert "Old message" in msg["content"]

        # Verify DB still has all messages (no deletion)
        with Session(in_memory_db) as session:
            remaining = session.query(ChannelMessage).count()
        assert remaining == 15


def test_archive_old_messages_with_deletion(in_memory_db, seeded_messages):
    """Test archiving old messages with deletion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "archive.jsonl"
        before_date = datetime.now(timezone.utc) - timedelta(days=7)

        count = archive_messages(
            db_url=str(in_memory_db.url),
            before_date=before_date,
            channel_id=None,
            output_path=output_path,
            delete_after_archive=True,
        )

        assert count == 10
        assert output_path.exists()

        # Verify DB now has only 5 recent messages
        with Session(in_memory_db) as session:
            remaining = session.query(ChannelMessage).count()
        assert remaining == 5

        # Verify remaining messages are recent
        with Session(in_memory_db) as session:
            messages = session.query(ChannelMessage).all()
        assert all("Recent message" in m.content for m in messages)


def test_archive_filter_by_channel(in_memory_db, seeded_messages):
    """Test archiving with channel_id filter."""
    # Add messages from another channel
    with Session(in_memory_db) as session:
        other_channel_msg = ChannelMessage(
            id=uuid.uuid4(),
            connector_id=seeded_messages["connector_id"],
            channel="other-channel",
            channel_id_snowflake="9999999999",
            author="user99",
            content="Other channel message",
            message_type="info",
            tickers_mentioned=[],
            raw_data={},
            platform_message_id="other_1",
            posted_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        session.add(other_channel_msg)
        session.commit()

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "archive.jsonl"
        before_date = datetime.now(timezone.utc) - timedelta(days=7)

        # Archive only from channel "1234567890"
        count = archive_messages(
            db_url=str(in_memory_db.url),
            before_date=before_date,
            channel_id="1234567890",
            output_path=output_path,
            delete_after_archive=True,
        )

        # Should only archive 10 messages from that channel
        assert count == 10

        # Verify other channel's message is still in DB
        with Session(in_memory_db) as session:
            remaining = session.query(ChannelMessage).filter_by(
                channel_id_snowflake="9999999999"
            ).count()
        assert remaining == 1


def test_archive_no_messages(in_memory_db, seeded_messages):
    """Test archiving when no messages match criteria."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "archive.jsonl"
        # Use a date in the past where no messages exist
        before_date = datetime.now(timezone.utc) - timedelta(days=365)

        count = archive_messages(
            db_url=str(in_memory_db.url),
            before_date=before_date,
            channel_id=None,
            output_path=output_path,
            delete_after_archive=False,
        )

        assert count == 0
        assert not output_path.exists()


def test_archive_idempotent(in_memory_db, seeded_messages):
    """Test that running archive twice produces identical output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path1 = Path(tmpdir) / "archive1.jsonl"
        output_path2 = Path(tmpdir) / "archive2.jsonl"
        before_date = datetime.now(timezone.utc) - timedelta(days=7)

        # Run archive twice
        count1 = archive_messages(
            db_url=str(in_memory_db.url),
            before_date=before_date,
            channel_id=None,
            output_path=output_path1,
            delete_after_archive=False,
        )

        count2 = archive_messages(
            db_url=str(in_memory_db.url),
            before_date=before_date,
            channel_id=None,
            output_path=output_path2,
            delete_after_archive=False,
        )

        assert count1 == count2 == 10

        # Verify files are identical
        with open(output_path1) as f1, open(output_path2) as f2:
            content1 = f1.read()
            content2 = f2.read()
        assert content1 == content2
