# Spec: Transformation Pipeline (Backtesting Step 1)

## Purpose

Read 2 years of Discord messages from a specified channel, parse each raw message into a clean trade row with features, reconstruct partial exits, compute profit/loss labels, and attach hourly sentiment scores.

## Input

```json
{
  "discord_server_id": "123456789",
  "channel_id": "987654321",
  "channel_name": "spx-alerts",
  "lookback_days": 730,
  "analyst_name": "Vinod"
}
```

## Output

A pandas DataFrame (saved as Parquet) with one row per completed trade:

| Column | Type | Description |
|--------|------|-------------|
| `trade_id` | str | UUID for this trade |
| `ticker` | str | e.g., "SPX", "AAPL" |
| `side` | str | "long" or "short" |
| `entry_price` | float | Price at entry |
| `entry_time` | datetime | When the buy signal was posted |
| `target_price` | float | Analyst's stated target (if any) |
| `stop_loss` | float | Analyst's stated stop (if any) |
| `exit_pct_25` | float | Price at 25% partial exit (NaN if no partial) |
| `exit_pct_50` | float | Price at 50% partial exit |
| `exit_pct_75` | float | Price at 75% partial exit |
| `exit_pct_100` | float | Price at full exit |
| `exit_time_first` | datetime | Time of first partial exit |
| `exit_time_final` | datetime | Time of final exit |
| `weighted_exit_price` | float | Volume-weighted average exit price |
| `pnl_pct` | float | Percentage return on the trade |
| `pnl_dollar` | float | Dollar return (if size known) |
| `is_profitable` | bool | True if >50% of position exited with gain |
| `hold_duration_hours` | float | Time between entry and final exit |
| `entry_sentiment_score` | float | Hourly sentiment at entry time (-1 to 1) |
| `entry_message_raw` | str | Original Discord message |
| `exit_messages_raw` | list[str] | All exit-related messages |
| `analyst` | str | Discord username of the analyst |
| `channel` | str | Channel name |
| `option_type` | str | "call", "put", or "stock" |
| `strike` | float | Option strike price (NaN for stocks) |
| `expiry` | str | Option expiry date (NaN for stocks) |

## Processing Steps

### 1. Ingest Messages

Use existing `services/message-ingestion/src/discord_adapter.py` to pull 2 years of history:

```python
async def ingest_messages(connector_config, channel_id, lookback_days=730):
    adapter = DiscordAdapter(connector_config)
    since = datetime.utcnow() - timedelta(days=lookback_days)
    messages = []
    async for batch in adapter.pull_history(since=since):
        messages.extend(batch)
    return messages
```

### 2. Parse and Fix Messages

Enhance `shared/nlp/signal_parser.py` to handle:

- **Missing dates**: Infer from message timestamp
- **Typos in tickers**: Fuzzy match against known ticker list (rapidfuzz)
- **Incomplete prices**: Extract from context ("took SPX at 50" → entry_price=5050 based on SPX level)
- **Option parsing**: "$SPX 5950C 0DTE" → ticker=SPX, strike=5950, type=call, expiry=today

```python
def fix_and_parse(raw_message: str, posted_at: datetime) -> ParsedSignal:
    signal = parse_signal(raw_message)
    
    # Fix missing date
    if not signal.date:
        signal.date = posted_at.date()
    
    # Fuzzy ticker correction
    if signal.ticker and signal.ticker not in KNOWN_TICKERS:
        match = rapidfuzz.process.extractOne(signal.ticker, KNOWN_TICKERS, score_cutoff=80)
        if match:
            signal.ticker = match[0]
    
    return signal
```

### 3. Reconstruct Partial Exits

Group messages by ticker + time window (same trade session = within 24h of entry):

```python
def reconstruct_exits(entry_signal, subsequent_messages):
    exits = []
    cumulative_pct = 0.0
    
    for msg in subsequent_messages:
        if msg.type in ('sell_signal', 'close_signal') and msg.ticker == entry_signal.ticker:
            pct = extract_exit_percentage(msg.content)  # "sold 50%" → 0.5
            price = msg.price
            cumulative_pct += pct
            exits.append(ExitEvent(pct=pct, cumulative=cumulative_pct, price=price, time=msg.time))
            
            if cumulative_pct >= 0.95:  # Fully closed
                break
    
    return exits
```

### 4. Compute Profit Labels

```python
def compute_profit_label(entry_price, exits, side='long'):
    profitable_exits = 0
    total_weight = 0
    
    for exit in exits:
        pnl = (exit.price - entry_price) / entry_price if side == 'long' \
              else (entry_price - exit.price) / entry_price
        total_weight += exit.pct
        if pnl > 0:
            profitable_exits += exit.pct
    
    # Profitable if >50% of position exited with gain
    return profitable_exits > 0.5 * total_weight if total_weight > 0 else False
```

### 5. Attach Sentiment Scores

Use **Finnhub** (free tier: 60 calls/min) or **News API** for hourly headline sentiment:

```python
async def get_hourly_sentiment(ticker: str, timestamp: datetime) -> float:
    """Returns sentiment score -1.0 to 1.0 for the hour of the trade."""
    hour_start = timestamp.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + timedelta(hours=1)
    
    # Check cache first
    cached = await redis.get(f"sentiment:{ticker}:{hour_start.isoformat()}")
    if cached:
        return float(cached)
    
    # Fetch headlines for this hour
    headlines = await finnhub_client.company_news(
        ticker, _from=hour_start.strftime('%Y-%m-%d'), to=hour_end.strftime('%Y-%m-%d')
    )
    
    if not headlines:
        return 0.0  # Neutral if no news
    
    # Simple sentiment: use FinBERT or keyword scoring
    scores = [classify_sentiment(h['headline']) for h in headlines]
    avg_score = sum(scores) / len(scores)
    
    await redis.setex(f"sentiment:{ticker}:{hour_start.isoformat()}", 86400, str(avg_score))
    return avg_score
```

## Tool Script (for Claude Code agent)

```
agents/backtesting/tools/transform.py
```

CLI interface:
```bash
python tools/transform.py \
    --config config.json \
    --output output/transformed.parquet
```

## Files to Create/Modify

| File | Action |
|------|--------|
| `agents/backtesting/tools/transform.py` | New — standalone transformation script |
| `agents/backtesting/tools/sentiment.py` | New — sentiment API wrapper |
| `shared/nlp/signal_parser.py` | Modify — add fix_and_parse, extract_exit_percentage |
| `shared/nlp/ticker_extractor.py` | Modify — add fuzzy matching |
