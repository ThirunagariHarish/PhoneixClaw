"""Integration test: Backtest pipeline DB-only enforcement (egress-blocked).

Verifies that the backtest transform step can run with network egress completely blocked,
reading ONLY from the database and producing valid output.

This test:
1. Seeds a Postgres container with synthetic channel_messages and backtest_trades
2. Runs agents/backtesting/tools/transform.py via subprocess with network blocked
3. Asserts exit 0 and valid Parquet output

Network blocking approach: monkey-patch socket.socket to refuse non-localhost connections.
"""

import os
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from shared.db.models.agent import Agent
from shared.db.models.agent_backtest import AgentBacktest
from shared.db.models.backtest_trade import BacktestTrade
from shared.db.models.base import Base
from shared.db.models.channel_message import ChannelMessage
from shared.db.models.connector import Connector

# Use a real Postgres DB for this integration test (SQLite doesn't fully support JSONB)
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://phoenixtrader:localdev@localhost:5432/phoenixtrader_test",
)


@pytest.fixture(scope="module")
def db_engine():
    """Create a test database engine with schema."""
    engine = create_engine(TEST_DB_URL, echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def seeded_db(db_engine) -> Generator[tuple[str, str], None, None]:
    """Seed database with 100 synthetic messages and 10 backtest trades.

    Returns (connector_id, channel_id_snowflake) for verification.
    """
    with Session(db_engine) as session:
        # Create connector
        connector = Connector(
            id=uuid.uuid4(),
            name="Test Discord Connector",
            type="discord",
            status="active",
            config={"channel_ids": ["1234567890123456789"]},
            is_active=True,
        )
        session.add(connector)
        session.flush()

        # Create agent
        agent = Agent(
            id=uuid.uuid4(),
            name="Test Agent",
            type="backtesting",
            status="pending",
            config={},
        )
        session.add(agent)
        session.flush()

        # Create backtest
        backtest = AgentBacktest(
            id=uuid.uuid4(),
            agent_id=agent.id,
            status="running",
            config={},
        )
        session.add(backtest)
        session.flush()

        # Seed 100 messages over 24 months
        channel_id_snowflake = "1234567890123456789"
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=730)  # 24 months
        messages = []

        for i in range(100):
            posted_at = start_date + timedelta(days=i * 7)  # ~weekly
            msg = ChannelMessage(
                id=uuid.uuid4(),
                connector_id=connector.id,
                channel=channel_id_snowflake,
                channel_id_snowflake=channel_id_snowflake,
                author=f"user{i % 5}",
                content=f"Test message {i}",
                message_type="info",
                tickers_mentioned=["SPY", "QQQ"],
                raw_data={"test": True},
                platform_message_id=str(1000000000000000000 + i),
                posted_at=posted_at,
            )
            messages.append(msg)
            session.add(msg)

        session.flush()

        # Seed 10 backtest trades referencing some messages
        for i in range(10):
            trade = BacktestTrade(
                id=uuid.uuid4(),
                backtest_id=backtest.id,
                agent_id=agent.id,
                ticker="SPY",
                side="long",
                entry_price=400.0 + i,
                exit_price=405.0 + i,
                entry_time=messages[i * 10].posted_at,
                exit_time=messages[i * 10].posted_at + timedelta(hours=2),
                pnl=5.0,
                pnl_pct=1.25,
                holding_period_hours=2.0,
                signal_message_id=messages[i * 10].id,
                channel_id=channel_id_snowflake,
                is_profitable=True,
            )
            session.add(trade)

        session.commit()

        yield str(connector.id), channel_id_snowflake

        # Cleanup
        session.execute(text("DELETE FROM backtest_trades"))
        session.execute(text("DELETE FROM agent_backtests"))
        session.execute(text("DELETE FROM agents"))
        session.execute(text("DELETE FROM channel_messages"))
        session.execute(text("DELETE FROM connectors"))
        session.commit()


class BlockedSocket:
    """Socket replacement that blocks all non-localhost connections."""

    def __init__(self, *args, **kwargs):
        self._original_socket = socket.socket(*args, **kwargs)

    def connect(self, address):
        """Block connections to non-localhost addresses."""
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("localhost", "127.0.0.1", "::1"):
            raise OSError(f"Network egress blocked: cannot connect to {host}")
        return self._original_socket.connect(address)

    def __getattr__(self, name):
        return getattr(self._original_socket, name)


def block_network_egress():
    """Monkey-patch socket to block non-localhost connections."""
    socket.socket = BlockedSocket


def test_backtest_db_only_egress_blocked(seeded_db):
    """Verify backtest transform runs successfully with network egress blocked."""
    connector_id, channel_id = seeded_db

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.parquet"

        # Build command to run transform.py
        # We need to run in a subprocess with the monkey-patch applied
        transform_script = Path(__file__).parent.parent.parent / "agents" / "backtesting" / "tools" / "transform.py"
        assert transform_script.exists(), f"transform.py not found at {transform_script}"

        # Create a wrapper script that applies the network block
        wrapper_script = Path(tmpdir) / "run_blocked.py"
        wrapper_script.write_text(f"""
import socket
import subprocess
import sys

class BlockedSocket:
    def __init__(self, *args, **kwargs):
        self._original_socket = socket.socket(*args, **kwargs)

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("localhost", "127.0.0.1", "::1"):
            raise OSError(f"Network egress blocked: cannot connect to {{host}}")
        return self._original_socket.connect(address)

    def __getattr__(self, name):
        return getattr(self._original_socket, name)

# Apply network block
socket.socket = BlockedSocket

# Run transform.py as a module
import sys
sys.path.insert(0, "{transform_script.parent.parent.parent.parent}")
sys.argv = [
    "transform.py",
    "--source", "postgres",
    "--db-url", "{TEST_DB_URL}",
    "--output", "{output_path}",
]

exec(open("{transform_script}").read())
""")

        # Run the wrapper
        result = subprocess.run(
            [sys.executable, str(wrapper_script)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Debug output on failure
        if result.returncode != 0:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)

        # Assertions
        assert result.returncode == 0, f"Transform exited with code {result.returncode}"
        assert output_path.exists(), f"Output file not created at {output_path}"

        # Verify Parquet content
        df = pd.read_parquet(output_path)
        assert len(df) == 10, f"Expected 10 trades, got {len(df)}"
        assert "ticker" in df.columns
        assert "entry_price" in df.columns
        assert all(df["ticker"] == "SPY")


def test_transform_postgres_source_only():
    """Verify transform.py --source discord is deprecated and raises error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.parquet"
        transform_script = Path(__file__).parent.parent.parent / "agents" / "backtesting" / "tools" / "transform.py"

        result = subprocess.run(
            [
                sys.executable,
                str(transform_script),
                "--source", "discord",
                "--output", str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Should fail with clear error message
        assert result.returncode != 0
        assert "deprecated" in result.stderr.lower() or "postgres" in result.stderr.lower()
