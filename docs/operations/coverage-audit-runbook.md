# Coverage Audit Runbook

## Purpose

The coverage audit CLI verifies that Discord channels configured for backtesting have sufficient historical message data. The target is 24 months of history per channel to ensure high-quality backtesting results.

## When to Run

- **Before first backtest** of a new Discord channel
- **Monthly** as part of data quality checks
- **After connector configuration changes** (adding/removing channels)
- **When backtest quality is unexpectedly low** (insufficient data may be the cause)

## Usage

### Basic Audit (All Connectors)

```bash
python -m tools.coverage_audit --output /tmp/coverage.json
```

### Audit Specific Connector

```bash
python -m tools.coverage_audit \
  --connector-id <uuid> \
  --output /tmp/coverage.json
```

### Custom Thresholds

```bash
python -m tools.coverage_audit \
  --min-months 12 \
  --min-messages 50 \
  --output /tmp/coverage.json
```

## Output Interpretation

### Exit Codes

- **0**: All channels pass requirements
- **1**: One or more channels fail requirements (needs backfill)
- **2**: Tool error (DB connection, invalid args, etc.)

### JSON Schema

```json
{
  "audit_timestamp": "2026-04-18T20:00:00Z",
  "threshold_months": 24,
  "threshold_messages": 100,
  "channels_total": 5,
  "channels_pass": 3,
  "channels_fail": 2,
  "failures": [
    {
      "connector_id": "uuid",
      "connector_name": "Trading Signals",
      "channel_id": "123456789012345678",
      "message_count": 45,
      "date_range_days": 180,
      "earliest_message": "2025-10-01T00:00:00Z",
      "latest_message": "2026-04-18T00:00:00Z",
      "reason": "Insufficient history (180 < 730 days)",
      "recommended_backfill": "python -m tools.backfill --connector-id uuid --channel-id 123456789012345678 --from 2024-04-01"
    }
  ],
  "passes": [...]
}
```

### Human Summary

The tool prints a human-readable summary to stderr:

```
Coverage Audit Summary
======================
Audit Timestamp: 2026-04-18T20:00:00Z
Threshold: 24 months, 100 messages
Total Channels: 5
Passed: 3
Failed: 2

Passing Channels:
  PASS Trading Signals / 111111111111111111: 5000 msgs, 850 days
  PASS Alpha Alerts / 222222222222222222: 3200 msgs, 900 days

Failing Channels:
  FAIL New Channel / 333333333333333333: 45 msgs, 180 days
       Reason: Insufficient history (180 < 730 days)
       Backfill: python -m tools.backfill --connector-id ... --from 2024-04-01
```

## How to Fix Failures

### 1. Run Recommended Backfill

Each failure includes a `recommended_backfill` command. Copy and run it:

```bash
python -m tools.backfill \
  --connector-id <uuid> \
  --channel-id <snowflake> \
  --from 2024-04-01
```

**Note**: Backfill tool is implemented in Phase C.3 (separate from this CLI).

### 2. Verify Backfill Success

After backfill completes, re-run the audit:

```bash
python -m tools.coverage_audit --connector-id <uuid>
```

Channel should now pass.

### 3. Handle Discord API Limitations

Discord's API has a ~1-year history limit for some channels. If backfill cannot retrieve older messages:

1. Document the limitation in the backtest metadata
2. Adjust `--min-months` threshold for that specific channel
3. Consider using a longer data collection period before backtesting

## Integration with Backtesting Pipeline

The backtesting agent (`agents/backtesting/CLAUDE.md`) should run coverage audit as **Step 0** (before transform.py). If channels fail, the agent should:

1. Log the failure
2. Optionally trigger backfill (if auto-backfill is enabled)
3. Proceed with available data (if policy allows partial coverage)

## Automation

### CI/CD Integration

Add to pre-backtest checks:

```yaml
- name: Coverage Audit
  run: |
    python -m tools.coverage_audit --output coverage.json
    if [ $? -eq 1 ]; then
      echo "Coverage audit failed. See coverage.json for details."
      exit 1
    fi
```

### Cron Job (Monthly Audit)

```bash
0 2 1 * * cd /path/to/phoenix && python -m tools.coverage_audit --output /var/log/phoenix/coverage-$(date +\%Y\%m).json
```

## Troubleshooting

### No Connectors Found

**Symptom**: `channels_total: 0`

**Cause**: No active Discord connectors in database

**Fix**: Verify `connectors` table has rows with `type='discord'` and `is_active=true`

### Database Connection Error

**Symptom**: Exit code 2, "ERROR: Coverage audit failed"

**Cause**: `DATABASE_URL` not set or Postgres not running

**Fix**:
```bash
export DATABASE_URL="postgresql+asyncpg://..."
make infra-up  # Start Postgres if needed
```

### Channel Shows Zero Messages

**Symptom**: Failure with "No messages found in database"

**Cause**: Discord ingestion service not running, or channel not yet ingested

**Fix**:
1. Verify `services/discord-ingestion` is running
2. Check connector credentials are valid
3. Manually trigger message ingestion (if supported)

## References

- Architecture: `docs/architecture/phase-c-backtesting-db-robustness.md` §5
- Backfill Tool: `tools/backfill.py` (Phase C.3)
- Discord Ingestion: `services/discord-ingestion/src/main.py`
