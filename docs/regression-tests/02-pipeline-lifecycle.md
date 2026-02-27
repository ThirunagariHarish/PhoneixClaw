# E2E Regression: Pipeline Creation & Lifecycle

## Prerequisites
- Logged in user with trading account and data source configured
- At least one Discord data source with synced channels

---

## TC-PIPE-001: Create Discord Pipeline
**Steps:**
1. Navigate to Trade Pipelines
2. Click "New Pipeline"
3. Select Source Type: Discord
4. Select a data source
5. Select a channel
6. Select a trading account
7. Enter pipeline name
8. Click "Create Pipeline"

**Expected:**
- Pipeline appears in the list
- Status shows "STOPPED"
- Pipeline card shows source and account info

---

## TC-PIPE-002: Start Pipeline
**Steps:**
1. Find the created pipeline
2. Click "Start" button

**Expected:**
- Status changes to "RUNNING"
- Source orchestrator begins monitoring the channel

---

## TC-PIPE-003: Pipeline Detail View
**Steps:**
1. Click on a running pipeline card

**Expected:**
- Pipeline detail page loads
- Stats grid shows: Total Trades, Executed, Win Rate, Messages, Avg Latency, Errors
- Portfolio chart (7d default) renders
- Trades, Messages, and Settings tabs are accessible

---

## TC-PIPE-004: Edit Pipeline Settings
**Steps:**
1. In pipeline detail, click "Settings" tab
2. Change auto-approve to manual
3. Save changes

**Expected:**
- Success notification
- Pipeline config updated
- Subsequent trades require manual approval

---

## TC-PIPE-005: Stop Pipeline
**Steps:**
1. Navigate to Trade Pipelines list
2. Click "Stop" on a running pipeline

**Expected:**
- Status changes to "STOPPED"
- No new messages processed

---

## TC-PIPE-006: Delete Pipeline
**Steps:**
1. Click delete icon on a stopped pipeline
2. Confirm deletion

**Expected:**
- Pipeline removed from list
- Related records cleaned up

---

## TC-PIPE-007: Chat Widget Pipeline
**Steps:**
1. Click the chat widget (floating button bottom-right)
2. Send a trade message: "BTO AAPL 190C 3/21 @ 2.50"
3. Wait for processing

**Expected:**
- Message appears in chat history
- If pipeline connected, trade signal is processed
- Trade appears in Trades list
