# E2E Regression: Data Sources & Trading Accounts

## Prerequisites
- Logged in user
- Discord bot token (for Discord source testing)
- Alpaca API keys (for trading account testing)

---

## TC-DS-001: Create Discord Data Source
**Steps:**
1. Navigate to Data Sources
2. Click "Add Source"
3. Select "Discord"
4. Enter Discord bot token
5. Click "Discover Servers"
6. Select a server
7. Select channels
8. Click "Create"

**Expected:**
- Source appears in list with connection status
- Channels synced and displayed
- Source card shows server name and channel count

---

## TC-DS-002: Test Data Source Connection
**Steps:**
1. Find a data source in the list
2. Click "Test Connection"

**Expected:**
- Connection test runs
- Success/failure status displayed
- Last connected timestamp updated

---

## TC-DS-003: Sync Channels
**Steps:**
1. Click "Sync" on a Discord data source

**Expected:**
- Channels refreshed from Discord
- New channels appear, removed channels disappear
- Channel count updated

---

## TC-DS-004: Toggle Data Source
**Steps:**
1. Toggle a source's enabled switch

**Expected:**
- Source enabled/disabled
- Active pipelines using this source are affected

---

## TC-DS-005: Delete Data Source
**Steps:**
1. Click delete on a data source
2. Confirm

**Expected:**
- Source removed
- Related channels and pipelines cleaned up

---

## TC-ACCT-001: Create Trading Account
**Steps:**
1. Navigate to Trading Accounts
2. Click "Add Account"
3. Select "Alpaca"
4. Enter API key and secret key
5. Enter display name
6. Toggle paper mode ON
7. Click "Create"

**Expected:**
- Account appears in list
- Paper mode badge shown
- Health check runs automatically

---

## TC-ACCT-002: Verify Trading Account
**Steps:**
1. Find trading account
2. Check health status

**Expected:**
- Health status shows: HEALTHY (green) or UNHEALTHY (red)
- Buying power and account info displayed (if healthy)

---

## TC-ACCT-003: Toggle Paper/Live Mode
**Steps:**
1. Click paper/live toggle on trading account

**Expected:**
- Mode changed
- Warning shown before switching to LIVE
- Base URL updated accordingly

---

## TC-ACCT-004: Delete Trading Account
**Steps:**
1. Click delete on trading account
2. Confirm

**Expected:**
- Account removed
- Related pipelines affected (mappings cleaned up)
