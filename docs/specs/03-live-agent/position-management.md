# Spec: Position Management

## Purpose

Define how live agents manage positions after entry: partial exits, trailing stops, position sizing, multi-position coordination, end-of-day handling, swing trade support, and P&L tracking.

## Partial Exit Strategy

Positions are closed in a ladder, not all-at-once:

| Tranche | Trigger | Size | Action |
|---------|---------|------|--------|
| 1st exit | +20% unrealized | 30% of position | Market sell, move stop to breakeven |
| 2nd exit | +35% unrealized | 30% of position | Market sell, tighten trailing stop to 10% |
| 3rd exit | Trailing stop OR +50% | Remaining 40% | Trailing stop or target hit |

Configuration in `config.json`:

```json
{
    "exit_ladder": [
        {"target_pct": 0.20, "exit_pct": 0.30, "move_stop_to": "breakeven"},
        {"target_pct": 0.35, "exit_pct": 0.30, "trailing_stop_pct": 0.10},
        {"target_pct": 0.50, "exit_pct": 1.0, "type": "final"}
    ]
}
```

## Trailing Stop Implementation

Two modes:

### Percentage-Based (Default)

- Initial stop: 20% below entry
- After 1st exit: move to breakeven
- After 2nd exit: 10% below high water mark

### ATR-Based (Advanced)

- Stop = high_water_mark - (2.5 * ATR_14)
- ATR recalculated every 5 minutes from live candle data
- Wider in volatile markets, tighter in calm markets

```python
def calculate_atr_stop(high_water_mark: float, atr: float, multiplier: float = 2.5) -> float:
    return high_water_mark - (multiplier * atr)
```

## Position Sizing

### Fixed Fractional (Default)

Risk 2% of portfolio per trade:

```python
def calculate_position_size(portfolio_value: float, entry_price: float, stop_price: float, risk_pct: float = 0.02) -> int:
    risk_per_share = entry_price - stop_price
    if risk_per_share <= 0:
        return 0
    dollar_risk = portfolio_value * risk_pct
    shares = int(dollar_risk / risk_per_share)
    return max(1, shares)
```

### Kelly Criterion (Optional)

For agents with sufficient backtest data:

```python
def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 0
    b = avg_win / abs(avg_loss)
    f = (win_rate * b - (1 - win_rate)) / b
    return max(0, min(f, 0.25))  # Cap at 25% of portfolio
```

## Multi-Position Management

### Concurrent Limits

- Conservative mode: max 2 concurrent positions
- Aggressive mode: max 5 concurrent positions
- Same ticker: max 1 position (no doubling down)

### Portfolio Exposure

- Max single-position: 10% of portfolio
- Max sector exposure: 30% of portfolio
- Max total exposure: 80% of portfolio (keep 20% cash)

### Correlation Check

Before opening a new position, check correlation with existing positions:

- If new ticker has >0.8 correlation with existing position → reduce size by 50%
- Track using rolling 20-day correlation matrix

## End-of-Day Handling

### 0DTE Options

- Auto-close all 0DTE positions by 3:45 PM ET
- If profitable: sell at market
- If losing: sell at market (avoid expiry exercise risk)

### Intraday Positions (Default)

- Target: close all intraday positions by 3:50 PM ET
- Exceptions: positions in "swing" mode
- At 3:30 PM: evaluate all positions for close vs hold overnight

### Decision Logic at 3:30 PM

```python
def eod_decision(position, ta_snapshot, config):
    if position.is_0dte:
        return "close"
    if position.mode == "swing":
        if position.unrealized_pnl_pct < -0.05:
            return "close"  # Don't hold losing swings overnight
        return "hold"
    if position.unrealized_pnl_pct > 0.10:
        return "hold_overnight"  # Strong winners can swing
    return "close"
```

## Swing Trade Support

### Detection

During backtesting, compute average hold time per analyst:

- Hold time > 1 trading day → mark analyst as "swing trader"
- Swing positions skip EOD auto-close

### Overnight Risk Management

- Before close: if unrealized P&L < 5%, reduce position by 30%
- After open next day: check gap direction
  - Gap against position > 2% → close immediately
  - Gap with position → hold, reset trailing stop from new high

### Multi-Day Monitoring

- Swing positions checked at 9:35 AM ET (post-open volatility settles)
- Full TA scan every 30 minutes during market hours
- End-of-day evaluation at 3:30 PM ET daily

## P&L Tracking

### Real-Time

```python
class PortfolioTracker:
    def __init__(self, initial_cash: float):
        self.cash = initial_cash
        self.positions: dict[str, Position] = {}
        self.closed_trades: list[ClosedTrade] = []
        self.daily_pnl: float = 0.0

    def update_prices(self, price_map: dict[str, float]):
        for ticker, pos in self.positions.items():
            if ticker in price_map:
                pos.current_price = price_map[ticker]
                pos.unrealized_pnl = (pos.current_price - pos.avg_entry) * pos.quantity

    def get_summary(self) -> dict:
        return {
            "portfolio_value": self.cash + sum(p.market_value for p in self.positions.values()),
            "cash": self.cash,
            "open_positions": len(self.positions),
            "unrealized_pnl": sum(p.unrealized_pnl for p in self.positions.values()),
            "realized_pnl": sum(t.pnl for t in self.closed_trades),
            "daily_pnl": self.daily_pnl,
            "win_rate": self._calculate_win_rate(),
        }
```

### Reporting to Phoenix

- Every trade: POST to `/api/v2/agents/{id}/live-trades`
- Every 60s: POST metrics summary to `/api/v2/agents/{id}/metrics`
- End of day: POST daily summary with all trades

## Files to Create

| File | Action |
|------|--------|
| `agents/live-template/tools/portfolio_tracker.py` | New |
| `agents/live-template/tools/position_monitor.py` | New |
| `agents/live-template/tools/position_sizer.py` | New |
