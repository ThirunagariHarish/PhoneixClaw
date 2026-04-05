# Spec: Paper Trading Mode

## Purpose

A paper trading simulator that mirrors the Robinhood MCP interface exactly, allowing agents to run in simulation mode without risking real money. Swappable via a single config flag.

## Design

- Implements identical MCP tool interface as `robinhood_mcp.py`
- Controlled by `config.json`: `"paper_mode": true`
- Agent code is completely unaware of paper vs live — same tool calls, same responses
- Virtual portfolio persisted in `paper_portfolio.json`

## Configuration

```json
{
    "paper_mode": true,
    "paper_config": {
        "initial_cash": 25000.00,
        "slippage_model": "realistic",
        "fill_delay_ms": 500,
        "market_data_source": "live"
    }
}
```

## Simulated Fills

### Market Orders

- Fill price = last_price + slippage
- Slippage model:
  - `none`: fill at exact last price
  - `fixed`: +0.01 per share
  - `realistic`: random(0.01%, 0.10%) of price, direction against order

### Limit Orders

- Buy limit: fills when ask <= limit_price
- Sell limit: fills when bid >= limit_price
- Check on every price update (every 5 seconds from yfinance)
- Partial fills: not simulated (full fill or nothing)

### Options Orders

- Same logic but with wider slippage (0.05% to 0.50%)
- Theta decay simulated: option positions lose value at contract's theta per day

## Virtual Portfolio State

```python
class PaperPortfolio:
    cash: float
    positions: dict[str, PaperPosition]
    pending_orders: list[PaperOrder]
    order_history: list[PaperOrder]

class PaperPosition:
    ticker: str
    quantity: float
    avg_cost: float
    current_price: float
    unrealized_pnl: float

class PaperOrder:
    id: str
    ticker: str
    side: str  # buy/sell
    quantity: float
    order_type: str  # market/limit/stop
    price: float | None
    status: str  # queued/filled/cancelled
    fill_price: float | None
    created_at: datetime
    filled_at: datetime | None
```

## Persistence

- State saved to `paper_portfolio.json` after every trade
- On restart, load existing state from file
- Daily reset option: `"reset_daily": true` starts fresh each market day

```json
{
    "cash": 24250.00,
    "positions": {
        "SPY": {"quantity": 10, "avg_cost": 450.00, "current_price": 452.50}
    },
    "order_history": [
        {"id": "paper_001", "ticker": "SPY", "side": "buy", "quantity": 10, "fill_price": 450.00, "status": "filled"}
    ],
    "daily_stats": {
        "2026-04-03": {"pnl": 25.00, "trades": 2, "win_rate": 1.0}
    }
}
```

## Price Feed

Even in paper mode, use LIVE market data (not simulated):

- `yfinance` for real-time quotes (delayed ~15 min for free tier)
- Price check interval: every 5 seconds during market hours
- Pre/post market: use last close price

```python
class LivePriceFeed:
    def __init__(self):
        self._cache: dict[str, tuple[float, float]] = {}
        self._last_fetch: float = 0

    async def get_price(self, ticker: str) -> float:
        if time.time() - self._last_fetch > 5:
            prices = yf.download(ticker, period="1d", interval="1m")
            self._cache[ticker] = (prices['Close'].iloc[-1], time.time())
            self._last_fetch = time.time()
        return self._cache.get(ticker, (0, 0))[0]
```

## Validation Against Live

Track paper vs live performance when both running:

- Compare fill prices: paper fill vs actual fill (measure slippage accuracy)
- Compare P&L trajectories
- Alert if paper diverges from live by >5% over 1 week

## Files to Create

| File | Action |
|------|--------|
| `agents/live-template/tools/robinhood_paper.py` | New — Paper MCP server |
