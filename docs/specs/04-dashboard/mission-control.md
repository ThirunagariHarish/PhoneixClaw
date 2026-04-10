# Spec: Agent Mission Control Dashboard

## Purpose

The Agent Mission Control page (`/agents/:id`) is the primary interface for managing a live trading agent. It provides a comprehensive view of the agent's portfolio, trades, intelligence, logs, and rules — with the ability to chat with the agent, send trade commands, approve proposals, and edit configuration in real time.

## Route

`/agents/:id` — replaces the previous 4-tab lightweight dashboard.

## Page Layout

```
+------------------------------------------------------------------------+
| [< Back]  SPX Alerts Agent                   [Aggressive] [Pause] [⚙]  |
+------------------------------------------------------------------------+
| $1,250 P&L  |  75% Win  |  12 Trades  |  3 Open  |  0.78 Conf  | ● Live |
+------------------------------------------------------------------------+
| TABS: Portfolio | Trades | Chat | Intelligence | Logs | Rules           |
+------------------------------------------------------------------------+
| [Tab Content Area]                                                      |
+------------------------------------------------------------------------+
```

### Header

- Agent name + channel badge
- Mode selector dropdown (Aggressive / Conservative)
- Pause / Resume toggle
- Settings gear icon → opens config panel
- Status indicator (Live / Paper / Paused / Error)

### Metrics Bar

Fetched from `GET /api/v2/agents/:id/metrics`:
- Total P&L (color-coded)
- Win rate
- Total trades
- Open positions count
- Average model confidence
- Heartbeat status (green dot if last heartbeat < 2 min)

---

## Tab: Portfolio

Robinhood-style positions view.

### Data Sources

- `GET /api/v2/agents/:id/positions` — open positions
- `GET /api/v2/agents/:id/metrics/history` — equity curve time series

### Components

1. **Account Summary Card**: total value, buying power, day gain/loss, unrealized P&L
2. **Equity Curve Chart**: line chart of cumulative P&L over time
3. **Open Positions Table**:

| Ticker | Side | Entry | Current | P&L | Size | Stop | Actions |
|--------|------|-------|---------|-----|------|------|---------|
| SPX 5950C | Long | $12.50 | $15.00 | +$250 | 10 | $10.00 | [Close] [50%] [Stop] |

4. **Position Actions**:
   - **Close**: `POST /agents/:id/command { "action": "close_position", "ticker": "...", "pct": 100 }`
   - **Partial Close**: same with `"pct": 50`
   - **Modify Stop**: `POST /agents/:id/command { "action": "modify_stop", "ticker": "...", "stop_price": ... }`

---

## Tab: Trades

Full trade history with expandable reasoning.

### Data Source

- `GET /api/v2/agents/:id/live-trades`

### Table Columns

| Time | Symbol | Side | Entry | Exit | P&L | Confidence | Status |
|------|--------|------|-------|------|-----|------------|--------|

### Expandable Row Detail

Each trade expands to show:
- **Signal**: raw Discord message text (`signal_raw` field)
- **Reasoning**: why the agent took or skipped the trade (`reasoning` field)
- **Model Confidence**: numeric value + visual bar
- **Pattern Matches**: list of matched rules (`pattern_matches` JSONB)
- **Execution**: broker order ID, fill price, slippage
- **Account**: which Robinhood account was used

---

## Tab: Chat

Command center for communicating with the Claude Code agent.

### Data Sources

- `GET /api/v2/agents/:id/chat` — message history (polls every 5s)
- `POST /api/v2/agents/:id/chat` — send message

### Message Types

| `message_type` | Rendering |
|-----------------|-----------|
| `text` | Standard chat bubble |
| `trade_proposal` | Structured card with ticker, price, direction, confidence + Approve/Reject buttons |
| `tool_trace` | Collapsible panel showing tool name, input params, output |
| `rule_change` | Before/after diff card |

### Chat Features

1. **Natural language trade requests**: User types "I want to buy a put on SPX because of war tensions" → agent researches, proposes trade as a `trade_proposal` message → user clicks Approve → agent executes
2. **Rule changes via chat**: "Lower confidence to 0.55" → agent confirms and applies, sends `rule_change` message
3. **Command shortcuts**: Quick action buttons above input:
   - Switch Mode (Aggressive/Conservative)
   - Pause/Resume
   - Close All Positions
   - Run Pre-Market Analysis
4. **Tool traces**: agent actions show collapsible traces of which tools were invoked and their results

### Trade Approval Flow

```
User: "Take a put on SPX 5900 for tomorrow"
Agent: [trade_proposal message]
  Ticker: SPXW 5900P 04/04
  Direction: Buy
  Price: ~$8.50
  Confidence: 0.72
  Risk Check: PASS
  [✅ Approve]  [❌ Reject]
User clicks Approve → POST /agents/:id/command { "action": "approve_trade", "trade": {...} }
Agent: "Order placed. Fill: $8.45. Stop-loss set at $6.00."
```

---

## Tab: Intelligence

Model and pattern intelligence from backtesting.

### Data Sources

- `GET /api/v2/agents/:id/manifest` — rules, knowledge, models
- `GET /api/v2/agents/:id/backtest` — backtest metrics

### Components

1. **Pattern Heatmap**: grid of all rules with name, condition, weight, win rate — weights are editable via click
2. **Model Comparison**: if manifest has `models.all_models`, show score comparison bar chart
3. **Feature Importance**: top 20 features from `knowledge.top_features` as horizontal bar chart
4. **Analyst Profile Card**: avg hold, win rate, best tickers, best hours, trades/day
5. **Channel Summary**: text overview from `knowledge.channel_summary`

---

## Tab: Logs

Real-time agent activity log.

### Data Source

- `GET /api/v2/agents/:id/logs` — paginated, filterable

### Components

1. **Filter bar**: level dropdown (ALL / INFO / WARN / ERROR), search input
2. **Log stream**: auto-scrolling list with pause-on-hover
3. **Log entry format**: `[timestamp] [LEVEL] message` with expandable context JSON
4. **Color coding**: trade decision = green, skip = yellow, error = red, heartbeat = gray, tool = blue

---

## Tab: Rules

Edit agent rules, risk parameters, and modes.

### Data Sources

- `GET /api/v2/agents/:id/manifest` — current rules + risk + modes
- `PUT /api/v2/agents/:id/manifest` — save changes

### Components

1. **Rules Table**:

| Enabled | Name | Condition | Weight | Source | Actions |
|---------|------|-----------|--------|--------|---------|
| ✅ | morning_session | hour_of_day between 9 and 11 | 2.1 | backtesting | [Edit] [Delete] |
| ✅ | user_caution_vix | market_vix > 25 | -3.0 | user | [Edit] [Delete] |

2. **Add Rule Button**: opens form with name, condition expression, weight, description
3. **Risk Config Form**: max position %, max daily loss %, max concurrent positions, confidence threshold, pattern match requirements
4. **Mode Editor**: two-column form for aggressive + conservative thresholds
5. **Save Button**: validates locally → `PUT /agents/:id/manifest` → SSH to VPS to update config.json → increments `rules_version`

---

## Agent Card Click-Through

On the Agents list page (`/agents`), clicking any agent card navigates to `/agents/:id` (the mission control page) instead of opening a side panel. The side panel is removed.

## API Dependencies

| Endpoint | Tab |
|----------|-----|
| `GET /agents/:id` | Header |
| `GET /agents/:id/metrics` | Metrics bar |
| `GET /agents/:id/positions` | Portfolio |
| `GET /agents/:id/metrics/history` | Portfolio chart |
| `GET /agents/:id/live-trades` | Trades |
| `GET /agents/:id/chat` | Chat |
| `POST /agents/:id/chat` | Chat |
| `POST /agents/:id/command` | Portfolio actions, Chat approvals |
| `GET /agents/:id/manifest` | Intelligence, Rules |
| `PUT /agents/:id/manifest` | Rules |
| `GET /agents/:id/logs` | Logs |
| `GET /agents/:id/backtest` | Intelligence |

## Files

| File | Action |
|------|--------|
| `apps/dashboard/src/pages/AgentDashboard.tsx` | REWRITE — mission control with 6 tabs |
| `apps/dashboard/src/pages/Agents.tsx` | MODIFY — card click navigates to `/agents/:id` |
| `apps/api/src/routes/agents.py` | MODIFY — manifest CRUD, enhanced command, chat message_type |
| `shared/db/models/agent.py` | MODIFIED — manifest, current_mode, rules_version fields |
| `shared/db/models/agent_chat.py` | MODIFIED — message_type, metadata fields |
