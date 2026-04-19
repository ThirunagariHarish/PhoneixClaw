"""Unit tests for percentage-sell quantity calculation and position tracking."""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_percentage_sell_qty_calculation():
    """Test percentage-sell quantity calculation from open positions."""
    from services.pipeline_worker.src.agent_worker import AgentWorker

    agent_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # Create worker
    mock_redis = AsyncMock()

    async def mock_session_factory():
        yield AsyncMock()

    worker = AgentWorker(
        agent_id=agent_id,
        connector_ids=[],
        config={},
        redis_client=mock_redis,
        session_factory=mock_session_factory,
        user_id=user_id,
    )

    # Mock session with position query result
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 10  # 10 contracts open

    mock_session.execute.return_value = mock_result

    # Mock parsed signal
    parsed = MagicMock()
    parsed.ticker = "SPY"
    parsed.strike = 600.0
    parsed.expiry = date(2026, 6, 16)

    # Test 50% sell
    qty = await worker._calculate_percentage_sell_qty(mock_session, "SPY", parsed, "50%")
    assert qty == 5

    # Test 100% sell
    qty = await worker._calculate_percentage_sell_qty(mock_session, "SPY", parsed, "100%")
    assert qty == 10

    # Test 25% sell
    qty = await worker._calculate_percentage_sell_qty(mock_session, "SPY", parsed, "25%")
    assert qty == 2


@pytest.mark.asyncio
async def test_percentage_sell_no_open_positions():
    """Test percentage-sell returns 0 when no open positions exist."""
    from services.pipeline_worker.src.agent_worker import AgentWorker

    agent_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    mock_redis = AsyncMock()

    async def mock_session_factory():
        yield AsyncMock()

    worker = AgentWorker(
        agent_id=agent_id,
        connector_ids=[],
        config={},
        redis_client=mock_redis,
        session_factory=mock_session_factory,
        user_id=user_id,
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0  # No open positions

    mock_session.execute.return_value = mock_result

    parsed = MagicMock()
    parsed.ticker = "SPY"
    parsed.strike = 600.0
    parsed.expiry = date(2026, 6, 16)

    qty = await worker._calculate_percentage_sell_qty(mock_session, "SPY", parsed, "50%")
    assert qty == 0


@pytest.mark.asyncio
async def test_record_trade_buy_creates_position():
    """Test that a BUY trade creates a new AgentTrade record."""
    from services.pipeline_worker.src.agent_worker import AgentWorker

    agent_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    mock_redis = AsyncMock()

    async def mock_session_factory():
        yield AsyncMock()

    worker = AgentWorker(
        agent_id=agent_id,
        connector_ids=[],
        config={},
        redis_client=mock_redis,
        session_factory=mock_session_factory,
        user_id=user_id,
    )

    mock_session = MagicMock()
    mock_session.add = MagicMock()

    parsed = MagicMock()
    parsed.ticker = "SPY"
    parsed.option_type = "C"
    parsed.strike = 600.0
    parsed.expiry = date(2026, 6, 16)

    await worker._record_trade(
        mock_session,
        parsed=parsed,
        qty=5,
        price=3.50,
        side="buy",
        order_id="RH123",
        signal_dict={"raw_content": "BUY SPY 600C", "confidence": 0.8},
    )

    # Verify trade was added
    mock_session.add.assert_called_once()
    trade = mock_session.add.call_args[0][0]
    assert trade.ticker == "SPY"
    assert trade.quantity == 5
    assert trade.current_quantity == 5
    assert trade.position_status == "open"
    assert trade.entry_price == 3.50
    assert trade.broker_order_id == "RH123"


@pytest.mark.asyncio
async def test_record_trade_sell_closes_position():
    """Test that a SELL trade updates position_status and current_quantity."""
    from services.pipeline_worker.src.agent_worker import AgentWorker
    from shared.db.models.agent_trade import AgentTrade

    agent_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    mock_redis = AsyncMock()

    async def mock_session_factory():
        yield AsyncMock()

    worker = AgentWorker(
        agent_id=agent_id,
        connector_ids=[],
        config={},
        redis_client=mock_redis,
        session_factory=mock_session_factory,
        user_id=user_id,
    )

    # Mock existing position
    existing_position = AgentTrade(
        id=uuid.uuid4(),
        agent_id=agent_id,
        ticker="SPY",
        side="BUY",
        option_type="C",
        strike=600.0,
        expiry=date(2026, 6, 16),
        entry_price=3.50,
        quantity=10,
        current_quantity=10,
        position_status="open",
        entry_time=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [existing_position]
    mock_session.execute.return_value = mock_result

    parsed = MagicMock()
    parsed.ticker = "SPY"
    parsed.strike = 600.0
    parsed.expiry = date(2026, 6, 16)

    # Sell 5 contracts
    await worker._record_trade(
        mock_session,
        parsed=parsed,
        qty=5,
        price=4.00,
        side="sell",
        order_id="RH456",
        signal_dict={},
    )

    # Verify position was partially closed
    assert existing_position.current_quantity == 5
    assert existing_position.position_status == "partially_closed"
    assert existing_position.exit_price is None  # Not fully closed yet

    # Sell remaining 5 contracts
    await worker._record_trade(
        mock_session,
        parsed=parsed,
        qty=5,
        price=4.00,
        side="sell",
        order_id="RH457",
        signal_dict={},
    )

    # Verify position was fully closed
    assert existing_position.current_quantity == 0
    assert existing_position.position_status == "closed"
    assert existing_position.exit_price == 4.00
    assert existing_position.exit_time is not None
    # PnL: (4.00 - 3.50) * 5 * 100 = $250
    assert existing_position.pnl_dollar == 250.0
    assert existing_position.pnl_pct == pytest.approx(14.29, abs=0.1)
