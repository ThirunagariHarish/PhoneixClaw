# Spec: Agents Tab Redesign

## Purpose

Redesign the Agents dashboard to show real metrics from live Claude Code agents: trade history, P&L, portfolio state, and the ability to chat with agents.

## Layout

```
┌──────────────────────────────────────────────────┐
│ Agents                              [+ New Agent] │
├──────────────────────────────────────────────────┤
│ Stats Bar: Total | Running | Paused | P&L Today  │
├──────────────────────────────────────────────────┤
│ Agent Cards Grid                                  │
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ │
│ │ SPX Alerts  │ │ AAPL Swings │ │ QQQ 0DTE    │ │
│ │ ● Running   │ │ ● Running   │ │ ○ Paused    │ │
│ │ P&L: +$450  │ │ P&L: -$120  │ │ P&L: +$800  │ │
│ │ Trades: 12  │ │ Trades: 5   │ │ Trades: 23  │ │
│ │ Win: 75%    │ │ Win: 60%    │ │ Win: 70%    │ │
│ │ Conf: 0.78  │ │ Conf: 0.65  │ │ Conf: 0.82  │ │
│ └─────────────┘ └─────────────┘ └─────────────┘ │
└──────────────────────────────────────────────────┘
```

## Agent Card

Each card shows:
- **Name** and channel
- **Status badge**: Running (green), Paused (yellow), Backtesting (blue), Error (red)
- **P&L today**: Dollar amount, color-coded
- **Trades today**: Count
- **Win rate**: Percentage (from backtest or live)
- **Model confidence**: Average confidence of recent predictions
- **Last signal**: Time since last processed signal
- **Actions**: Pause/Resume, View Details, Chat

## Agent Detail Page (`/agents/:id`)

### Tabs

1. **Overview**: Key metrics, P&L chart, risk status
2. **Trades**: Full trade history with signal, prediction, execution, result
3. **Intelligence**: Model info, patterns, explainability
4. **Chat**: Talk to the Claude Code agent directly
5. **Logs**: Agent activity log

### Overview Tab

- **Equity curve** (real, from reported trades)
- **Daily P&L bar chart**
- **Open positions table**
- **Risk metrics**: max drawdown, Sharpe, current exposure
- **Agent health**: uptime, last heartbeat, signals processed

### Trades Tab

| Time | Ticker | Side | Entry | Exit | P&L | Confidence | Patterns | Reasoning |
|------|--------|------|-------|------|-----|------------|----------|-----------|
| 9:35 | SPX 5950C | Long | $12.50 | $15.00 | +$250 | 0.78 | RSI_oversold, morning_session | Model high conf, 3 patterns matched |

Each trade expandable to show:
- Full signal text from Discord
- All 200 enriched features (collapsible)
- Model prediction details
- Risk check results
- Execution details (Robinhood order ID, fill price)

### Chat Tab

Direct communication with the Claude Code agent:

```
┌──────────────────────────────────────┐
│ Chat with SPX Alerts Agent           │
├──────────────────────────────────────┤
│ You: Why did you skip the last SPX   │
│      signal at 2:30 PM?             │
│                                      │
│ Agent: The model predicted SKIP with │
│ confidence 0.42 (below threshold    │
│ 0.65). Key factors: RSI was 72      │
│ (overbought), VIX was dropping, and │
│ no pattern matches were found.      │
│                                      │
│ You: Lower the confidence threshold  │
│      to 0.55 for the rest of today  │
│                                      │
│ Agent: Updated confidence_threshold  │
│ to 0.55 in config.json. This will   │
│ apply to all new signals. I'll      │
│ revert to 0.65 at market close.     │
├──────────────────────────────────────┤
│ [Type a message...]        [Send]    │
└──────────────────────────────────────┘
```

Implementation: Messages sent via Agent Gateway → SSH → `claude --print "message"` in agent directory.

## New Agent Wizard

Updated wizard steps:

1. **Channel**: Select Discord server → channel → analyst name
2. **Instance**: Select which VPS (Claude Code instance) to run on
3. **Risk Config**: Max position size, daily loss limit, confidence threshold
4. **Review & Create**: Shows summary, then ships backtesting agent to VPS

After creation:
- Agent status = `BACKTESTING`
- Progress streamed from VPS via SSH
- On completion → status = `RUNNING`, live agent active

## API Endpoints (New/Modified)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v2/agents/{id}/metrics` | GET | Real-time metrics from live agent |
| `GET /api/v2/agents/{id}/trades` | GET | Trade history |
| `POST /api/v2/agents/{id}/chat` | POST | Send message to agent |
| `GET /api/v2/agents/{id}/chat` | GET | Get chat history |
| `POST /api/v2/agents/{id}/heartbeat` | POST | Agent reports health |
| `GET /api/v2/agents/{id}/positions` | GET | Open positions |
| `POST /api/v2/agents/{id}/command` | POST | Send command to agent |

## Files to Modify

| File | Action |
|------|--------|
| `apps/dashboard/src/pages/Agents.tsx` | Rewrite — new card layout, wizard |
| `apps/dashboard/src/pages/AgentDashboard.tsx` | Rewrite — real metrics, trades, chat |
| `apps/api/src/routes/agents.py` | Modify — new endpoints |
| `shared/db/models/agent.py` | Modify — add metrics fields |
