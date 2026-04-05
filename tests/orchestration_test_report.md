# Phoenix Claw — Orchestration Test Report

## Started: 2026-04-05 ~02:05 AM CST
## Target: Run for 2 hours max or 70% token usage

---

## Test Plan

### Phase 1: API Smoke Tests
Test every API endpoint returns valid responses (no 500s).

### Phase 2: Claude Code Installation on Backtesting VPS
- SSH to 187.124.77.249
- Install Claude Code CLI
- Authenticate with API key
- Verify claude --version

### Phase 3: Ship Backtesting Agent
- Use POST /api/v2/instances/{id}/ship-agent to deploy backtesting code
- Verify files landed on VPS at ~/agents/backtesting/

### Phase 4: Trigger Backtesting
- Run the backtesting pipeline on VPS
- Monitor logs for errors
- Wait for completion or timeout

### Phase 5: Validate Backtesting Output
- Check for model outputs, metrics files
- Verify trade data, patterns extracted
- Cross-check backtesting numbers

### Phase 6: Dashboard UI Tests
- Test all page routes return 200
- Test critical user flows (login, navigate, CRUD)

### Phase 7: Bug Fixes
- Fix all bugs found during testing
- Push and redeploy

---

## Results Log

