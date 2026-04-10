# Spec: Token Optimization

## Purpose

Minimize Claude Code token usage in production by routing tasks to the cheapest capable model and offloading compute to Python scripts.

## Strategy

### 1. Compute in Code, Not Tokens

The backtesting agent's heavy work runs as Python scripts, not LLM reasoning:

| Task | Runs as | Token Cost |
|------|---------|------------|
| Discord message ingestion | Python (`discord_adapter.py`) | Zero |
| Feature extraction / NLP | Python (`signal_parser.py`) | Zero |
| Market data download | Python (`yfinance`, API calls) | Zero |
| Technical indicator calculation | Python (`ta`, `pandas`) | Zero |
| Model training | Python (`scikit-learn`, `xgboost`) | Zero |
| Model inference on new trade | Python (`.predict()`) | Zero |
| Robinhood order execution | Python (`robin_stocks`) | Zero |
| **Orchestration decisions** | **Claude Code LLM** | **Tokens** |
| **Error handling / debugging** | **Claude Code LLM** | **Tokens** |
| **User chat with agent** | **Claude Code LLM** | **Tokens** |

### 2. Model Routing

Configure Claude Code to use the cheapest model that can handle each task:

```json
// In CLAUDE.md or claude settings
{
  "model_preferences": {
    "default": "claude-haiku",
    "complex_analysis": "claude-sonnet",
    "code_generation": "claude-sonnet"
  }
}
```

| Task | Model | Reasoning |
|------|-------|-----------|
| Parse progress output | Haiku | Simple JSON parsing |
| Decide which tool to run next | Haiku | Follows CLAUDE.md script |
| Handle an error / debug | Sonnet | Needs reasoning |
| Generate training code | Sonnet | Complex code generation |
| User chat / explanation | Sonnet | Needs understanding |

### 3. Caching

- **Market data cache**: yfinance data cached locally on VPS for 24h
- **Enrichment cache**: computed indicators cached per ticker+date
- **Model predictions cache**: same ticker+features = same prediction (Redis TTL 1h)
- **Sentiment cache**: hourly sentiment scores cached per ticker

### 4. Batch Processing

Instead of waking the agent per Discord message:
- Discord listener (Python script, zero tokens) batches messages for 5 minutes
- Only invokes Claude Code when a potential trade signal is detected
- Signal detection is regex/NLP-based (Python), not LLM-based

### 5. Token Budget Monitoring

Dashboard widget queries Claude API usage:

```python
# Estimated daily token budget per agent type
BUDGETS = {
    "backtesting": 500_000,    # One-time, heavy orchestration
    "live_trading": 10_000,     # Per day, mostly Python
    "user_chat": 5_000,         # Per conversation
}
```

### API for Token Tracking

```
GET /api/v2/token-usage
Response: {
    "daily": { "input_tokens": 15000, "output_tokens": 8000, "cost_usd": 0.12 },
    "weekly": { ... },
    "monthly": { ... },
    "by_agent": [
        { "agent_id": "...", "agent_name": "SPX Alerts", "tokens_today": 3000 }
    ],
    "budget_remaining_pct": 78.5
}
```

## Files to Create/Modify

| File | Action |
|------|--------|
| `apps/api/src/routes/token_usage.py` | New — token monitoring endpoint |
| `apps/api/src/services/token_tracker.py` | New — aggregate usage data |
| `apps/dashboard/src/components/TokenMonitor.tsx` | New — sidebar widget |
