# E2E Regression: Strategy Builder

## Prerequisites
- Logged in user
- Strategy Agent service running

---

## TC-STRAT-001: Open Strategy Builder
**Steps:**
1. Navigate to Strategy Builder

**Expected:**
- Chat interface loads
- Strategy sidebar shows existing strategies (or empty state)
- Chat input ready

---

## TC-STRAT-002: Create Strategy via Chat
**Steps:**
1. Type: "Create a momentum strategy for AAPL using SMA crossover 10/30"
2. Send message

**Expected:**
- Agent processes the request (streaming responses)
- Steps shown: THOUGHT → ACTION (create_strategy) → OBSERVATION → DONE
- Strategy appears in sidebar list

---

## TC-STRAT-003: Backtest Strategy
**Steps:**
1. Type: "Backtest the AAPL momentum strategy"
2. Send message

**Expected:**
- Agent runs backtest tool
- Results shown: Total Return, Sharpe Ratio, Max Drawdown, Win Rate
- Equity curve chart rendered

---

## TC-STRAT-004: View Strategy Dashboard
**Steps:**
1. Click on a strategy in the sidebar

**Expected:**
- Strategy dashboard opens with:
  - Strategy name and status
  - 6 metric cards (Return, Sharpe, Drawdown, Win Rate, Trades, P&L)
  - Equity curve chart
  - Strategy Logic panel
  - Data & Signals panel

---

## TC-STRAT-005: Deploy as Signal Source
**Steps:**
1. In strategy dashboard, click "Deploy as Signal Source"

**Expected:**
- Strategy status changes to "deployed"
- DataSource record created
- Strategy available as signal source in pipeline creation

---

## TC-STRAT-006: Delete Strategy
**Steps:**
1. Hover over strategy in sidebar
2. Click delete icon
3. Confirm deletion

**Expected:**
- Strategy removed from sidebar
- Related records cleaned up

---

## TC-STRAT-007: New Chat
**Steps:**
1. Click "New chat" in sidebar

**Expected:**
- Chat history cleared
- Ready for new conversation
- Previous strategies still visible in sidebar
