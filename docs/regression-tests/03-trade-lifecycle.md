# E2E Regression: Trade Lifecycle

## Prerequisites
- Running pipeline with auto-approve enabled
- Trading account configured (paper mode recommended)

---

## TC-TRADE-001: Trade Signal Processing
**Steps:**
1. Send a trade message via chat widget: "BTO SPY 500C 3/21 @ 2.50"
2. Wait for processing (5-10 seconds)

**Expected:**
- Trade appears in Dashboard's recent trades table
- Status: EXECUTED (auto-approve) or PENDING (manual)
- Ticker, strike, option type, price correctly parsed

---

## TC-TRADE-002: Manual Trade Approval
**Steps:**
1. Ensure pipeline has auto_approve=false
2. Send a trade signal
3. Navigate to Trades page
4. Find the PENDING trade
5. Click "Approve"

**Expected:**
- Trade status changes to APPROVED → EXECUTED
- Position created in Positions page
- Notification sent

---

## TC-TRADE-003: Trade Rejection
**Steps:**
1. Find a PENDING trade
2. Click "Reject"

**Expected:**
- Trade status changes to REJECTED
- No position created
- Rejection reason recorded

---

## TC-TRADE-004: Position Monitoring
**Steps:**
1. Navigate to Positions page
2. Select the trading account
3. View open positions

**Expected:**
- Open position shows ticker, strike, entry price, quantity
- Unrealized P&L displayed (if broker connected)
- Auto-refreshes every 5 seconds

---

## TC-TRADE-005: Position Close
**Steps:**
1. In Positions page, find an open position
2. Click "Close" button
3. Confirm

**Expected:**
- Position moves to Closed tab
- Realized P&L calculated
- Close reason: "MANUAL"

---

## TC-TRADE-006: Trades CSV Export
**Steps:**
1. Navigate to Dashboard or Positions page
2. Click CSV export button

**Expected:**
- CSV file downloads with all trade/position data
- Columns match table headers

---

## TC-TRADE-007: Trade Statistics
**Steps:**
1. Navigate to Dashboard

**Expected:**
- KPI cards show: Total Trades, Executed, In Progress, Rejected, Errors
- Daily P&L chart renders with actual data
- Recent trades table shows latest 50 trades
