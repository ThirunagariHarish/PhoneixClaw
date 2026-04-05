# Spec: Agent Creation (Backtesting Step 4)

## Purpose

After backtesting completes (transformation + enrichment + training), the backtesting agent creates a new **live trading agent** configured for the specific Discord channel and analyst. The live agent is a self-contained Claude Code project with all necessary models, tools, and skills.

## Trigger

The backtesting agent, upon completing Step 3, assembles the live agent:

```
# In backtesting CLAUDE.md orchestration:
1. Run transform.py → output/transformed.parquet
2. Run enrich.py → output/enriched.parquet
3. Run train_*.py (parallel) → models/*.pkl, models/*.pt
4. Run evaluate_models.py → models/best_model.json
5. Run build_explainability.py → models/explainability.json
6. Run discover_patterns.py → models/patterns.json
7. **Create live agent** → ~/agents/live/{channel_name}/
```

## Live Agent Structure

```
~/agents/live/spx-alerts/
  CLAUDE.md                     # Live agent instructions
  config.json                   # Channel, thresholds, risk params
  models/
    best_classifier.pkl         # The selected trade classifier
    imputer.pkl                 # Feature imputer
    scaler.pkl                  # Feature scaler
    explainability.json         # SHAP-based feature importance
    patterns.json               # Top 60 patterns
    model_metadata.json         # Which model, accuracy, etc.
  tools/
    inference.py                # Run classifier on new trade
    enrich_single.py            # Enrich a single trade row (real-time)
    technical_analysis.py       # TA on current market data
    discord_listener.py         # Listen to Discord channel
    robinhood_trade.py          # Execute trades via robin_stocks
    risk_check.py               # Pre-trade risk validation
    portfolio_tracker.py        # Track open positions, P&L
    report_to_phoenix.py        # Report trades/metrics back to API
  skills/
    discord_monitor.md          # Skill: monitor channel for signals
    trade_execution.md          # Skill: evaluate + execute trades
    risk_management.md          # Skill: position sizing, stop losses
    daily_report.md             # Skill: end-of-day summary
```

## config.json

```json
{
  "agent_name": "SPX Alerts Agent",
  "channel_name": "spx-alerts",
  "channel_id": "987654321",
  "server_id": "123456789",
  "discord_token": "encrypted:...",
  "analyst_name": "Vinod",
  "ticker_focus": ["SPX", "SPXW"],
  "phoenix_api_url": "https://your-phoenix-api.com",
  "phoenix_api_key": "encrypted:...",
  "robinhood_username": "encrypted:...",
  "robinhood_password": "encrypted:...",
  "robinhood_mfa_code": "encrypted:...",
  "risk_params": {
    "max_position_size_pct": 5.0,
    "max_daily_loss_pct": 3.0,
    "max_concurrent_positions": 3,
    "confidence_threshold": 0.65,
    "require_pattern_match": true,
    "min_pattern_matches": 2
  },
  "model_info": {
    "model_type": "xgboost",
    "accuracy": 0.72,
    "auc_roc": 0.78,
    "training_date": "2026-04-04",
    "training_trades": 1200
  }
}
```

## CLAUDE.md for Live Agent

```markdown
# Live Trading Agent: {channel_name}

You are a live trading agent monitoring the Discord channel "{channel_name}" 
for trade signals from analyst {analyst_name}.

## Your Tools
- `tools/discord_listener.py` — monitors the Discord channel for new messages
- `tools/inference.py` — runs the trained ML model on a new signal
- `tools/enrich_single.py` — adds real-time market data to a signal
- `tools/technical_analysis.py` — performs technical analysis
- `tools/robinhood_trade.py` — executes trades on Robinhood
- `tools/risk_check.py` — validates trade against risk limits
- `tools/portfolio_tracker.py` — tracks open positions and P&L
- `tools/report_to_phoenix.py` — reports activity to Phoenix dashboard

## Operation Loop
1. Run `discord_listener.py` to watch for new messages
2. When a buy/sell signal is detected:
   a. Parse the signal (ticker, price, direction)
   b. Run `enrich_single.py` to get current market attributes
   c. Run `inference.py` to get model prediction + confidence
   d. Run `risk_check.py` to validate against position limits
   e. If confidence > threshold AND risk approved AND patterns match:
      - Execute trade via `robinhood_trade.py`
      - Report trade to Phoenix via `report_to_phoenix.py`
   f. If rejected: log the reason
3. Every 5 minutes: check open positions, update trailing stops
4. End of day: generate daily report, report to Phoenix

## Important Rules
- NEVER trade without model confirmation (confidence >= {threshold})
- NEVER exceed max position size ({max_position_size_pct}% of portfolio)
- ALWAYS check risk limits before trading
- If daily loss exceeds {max_daily_loss_pct}%, stop trading for the day
- Log every decision with reasoning
```

## Registration with Phoenix

After creating the live agent, the backtesting agent registers it:

```python
# tools/report_to_phoenix.py
async def register_agent(config):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{config['phoenix_api_url']}/api/v2/agents",
            json={
                "name": config["agent_name"],
                "type": "trading",
                "status": "RUNNING",
                "source": "backtesting",
                "config": {
                    "channel_name": config["channel_name"],
                    "analyst": config["analyst_name"],
                    "model_type": config["model_info"]["model_type"],
                    "accuracy": config["model_info"]["accuracy"],
                    "created_by": "backtesting_agent",
                },
            },
            headers={"Authorization": f"Bearer {config['phoenix_api_key']}"},
        )
        return response.json()
```

## Files to Create

| File | Action |
|------|--------|
| `agents/backtesting/tools/create_live_agent.py` | New — assembles the live agent folder |
| `agents/live-template/CLAUDE.md` | New — template for live agent instructions |
| `agents/live-template/config.json` | New — template config |
| `agents/live-template/tools/*.py` | New — all live agent tools |
