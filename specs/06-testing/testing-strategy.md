# Spec: Testing Strategy

## Purpose

Define the testing approach for Phoenix Claw: unit tests, integration tests, E2E tests, fixtures, CI gates, and performance benchmarks.

## Test Structure

```
tests/
  unit/
    test_signal_parser.py       # NLP signal extraction
    test_enrichment.py          # Feature engineering
    test_risk_check.py          # Risk validation rules
    test_exit_engine.py         # Stop loss/take profit logic
    test_intelligence_filter.py # Pattern matching rules
    test_token_tracker.py       # Token usage calculation
  integration/
    test_api_agents.py          # Agent CRUD + lifecycle
    test_api_trades.py          # Trade reporting + queries
    test_api_instances.py       # Instance management
    test_db_models.py           # ORM model validation
    test_gateway_ssh.py         # SSH connection pool (mock SSH)
  e2e/
    test_backtest_pipeline.py   # Full backtest on sample data
    test_live_pipeline.py       # Signal → inference → decision
    test_trading_vision_e2e.py  # Existing E2E test
  fixtures/
    discord_messages.json       # 100 sample Discord messages (buy/sell/noise)
    enriched_trades.parquet     # Sample enriched data (50 rows, all 200 columns)
    sample_model.pkl            # Small trained XGBoost for inference tests
    market_data/
      SPY_daily.csv             # 1 year SPY daily candles
      SPY_5min.csv              # 1 week SPY 5-minute candles
```

## Unit Tests

### Signal Parser Tests

- Parse buy signals: `$SPY 450c 04/10` → ticker=SPY, strike=450, type=call, expiry=04/10
- Parse sell signals: `close SPY calls` → type=close, ticker=SPY
- Handle noise: `good morning everyone` → type=noise
- Handle partial signals: `$SPY looking good` → type=info (no trade action)
- Edge cases: multiple tickers, missing prices, emoji-heavy messages

### Enrichment Tests

- Verify all 200 features are populated (no unexpected NaNs)
- Verify temporal correctness (features use data BEFORE trade time, not after)
- Verify candle window shape is (30, 15) with correct feature ordering
- Verify rolling analyst features (win_rate, streak) computed from prior trades only

### Risk Check Tests

- Confidence below threshold → rejected
- Max positions exceeded → rejected
- Daily loss limit hit → rejected
- All checks pass → approved
- Edge: exactly at threshold → approved (inclusive)

### Exit Engine Tests

- Profit target hit → TAKE_PROFIT signal
- Stop loss hit → STOP_LOSS signal
- Trailing stop triggered → TRAILING_STOP signal
- High water mark updates correctly
- Partial exits at correct ladder levels

## Integration Tests

### API Route Tests

Use `httpx.AsyncClient` with `TestClient` from FastAPI:

```python
@pytest.fixture
async def client():
    from apps.api.src.main import app
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

async def test_create_agent(client, db_session):
    resp = await client.post("/api/v2/agents", json={...})
    assert resp.status_code == 201
    agent = resp.json()
    assert agent["name"] == "Test Agent"
    # Verify in DB
    db_agent = await db_session.get(Agent, agent["id"])
    assert db_agent is not None
```

### DB Model Tests

- Create, read, update, delete for every ORM model
- Foreign key constraints (agent_trade requires valid agent_id)
- Unique constraints (no duplicate agent names)
- Cascade deletes (delete agent → delete trades, metrics, chat)

### Gateway SSH Tests

Mock `asyncssh` to test:

- Connection pool creation and reuse
- Command execution and output capture
- Connection failure handling and retry
- Ship-agent SCP flow

## E2E Tests

### Backtest Pipeline E2E

1. Load 50 sample Discord messages from fixtures
2. Run transformation (signal parsing, trade reconstruction)
3. Run enrichment (with mocked yfinance returning fixture data)
4. Run preprocessing (4 modality output)
5. Train a small XGBoost (10 trees, max_depth 3 for speed)
6. Evaluate and verify metrics are in expected ranges
7. Assert pattern discovery returns at least 5 patterns

### Live Pipeline E2E

1. Create mock signal from fixtures
2. Run through LiveTradingPipeline with mock executor
3. Verify intelligence filter evaluates correctly
4. Verify risk chain passes/rejects correctly
5. Verify trade intent is created with correct fields

## Mock Data Fixtures

### Discord Messages (100 samples)

Categories:

- 30 buy signals (stocks + options, various formats)
- 20 sell/close signals
- 10 partial exit signals (`trimmed 50%`)
- 10 update signals (`adding to position`)
- 30 noise messages (greetings, commentary, reactions)

### Market Data

Pre-downloaded CSV files for SPY, QQQ, AAPL:

- Daily candles: 1 year
- 5-minute candles: 1 week

Used to mock yfinance calls in tests (no network dependency).

## CI Gate Requirements

| Check | Required for Merge | Allowed to Fail |
|-------|-------------------|-----------------|
| Lint (ruff + eslint) | Yes | No |
| Unit tests | Yes | No |
| Integration tests | Yes | No |
| E2E tests | No (nightly) | Yes |
| Docker build | Yes | No |
| Type check (mypy) | No (advisory) | Yes |

## Performance Benchmarks

| Operation | Target | Measurement |
|-----------|--------|-------------|
| Signal parsing (100 messages) | < 100ms | pytest-benchmark |
| Single trade enrichment | < 2s | Wall clock |
| XGBoost inference (1 sample) | < 5ms | pytest-benchmark |
| Hybrid ensemble inference | < 50ms | pytest-benchmark |
| API /health response | < 50ms | httpx timing |
| Full backtest (50 trades) | < 5min | Wall clock |

## Files to Create

| File | Action |
|------|--------|
| tests/unit/test_signal_parser.py | New |
| tests/unit/test_enrichment.py | New |
| tests/unit/test_risk_check.py | New |
| tests/unit/test_exit_engine.py | New |
| tests/integration/test_api_agents.py | New |
| tests/integration/test_db_models.py | New |
| tests/fixtures/discord_messages.json | New |
| tests/conftest.py | New — shared fixtures |
| pytest.ini | New — test configuration |
