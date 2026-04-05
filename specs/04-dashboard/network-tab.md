# Spec: Network Tab Redesign

## Purpose

Replace the OpenClaw instance management with Claude Code instance management. Users register VPS machines, configure the backtesting agent location, and monitor instance health.

## Layout

```
┌──────────────────────────────────────────────────────┐
│ Network                           [+ Add Instance]    │
├──────────────────────────────────────────────────────┤
│ Backtesting Agent: vps-main (192.168.1.100)  [Edit]  │
├──────────────────────────────────────────────────────┤
│ Instance Cards                                        │
│ ┌──────────────────┐ ┌──────────────────┐            │
│ │ vps-main         │ │ vps-trading-01   │            │
│ │ ● Online         │ │ ● Online         │            │
│ │ 192.168.1.100    │ │ 10.0.0.50        │            │
│ │ Claude: v1.2.3   │ │ Claude: v1.2.3   │            │
│ │ Agents: 3        │ │ Agents: 2        │            │
│ │ CPU: 45%         │ │ CPU: 30%         │            │
│ │ RAM: 2.1/4 GB    │ │ RAM: 1.5/8 GB    │            │
│ │ Role: backtesting │ │ Role: trading    │            │
│ │ [Check] [Detail] │ │ [Check] [Detail] │            │
│ └──────────────────┘ └──────────────────┘            │
└──────────────────────────────────────────────────────┘
```

## Add Instance Dialog

Fields:
- **Name**: Human-readable name
- **Host**: IP address or hostname
- **SSH Port**: Default 22
- **Username**: SSH username
- **SSH Private Key**: Paste or upload (stored encrypted)
- **Role**: `backtesting` | `trading` | `general`
- **[Verify]**: Test SSH connection + check Claude Code

## Instance Detail Panel

- **System Info**: OS, CPU, RAM, disk
- **Claude Code**: Version, status
- **Agents Running**: List of agent folders in `~/agents/live/`
- **Resource Usage**: CPU/RAM charts (from periodic heartbeat)
- **Actions**: 
  - Install Claude Code (if not present)
  - Ship Backtesting Agent
  - Restart Agent
  - View Logs

## Backtesting Agent Configuration

A prominent section at the top of Network tab:

```
┌─ Backtesting Agent Configuration ────────────────────┐
│ Instance: [vps-main ▼]                                │
│ Status: ● Ready                                       │
│ Last Run: 2026-04-03 (SPX Alerts channel)            │
│ [Ship/Update Agent] [View Logs]                       │
└──────────────────────────────────────────────────────┘
```

When user clicks "Ship/Update Agent":
1. Gateway copies `agents/backtesting/` to the selected VPS
2. Installs Python dependencies if needed
3. Reports success/failure

## Database Changes

Replace `openclaw_instances` with `claude_code_instances`:

```sql
ALTER TABLE openclaw_instances RENAME TO claude_code_instances;
ALTER TABLE claude_code_instances ADD COLUMN ssh_port INTEGER DEFAULT 22;
ALTER TABLE claude_code_instances ADD COLUMN ssh_username VARCHAR(100);
ALTER TABLE claude_code_instances ADD COLUMN ssh_key_encrypted TEXT;
ALTER TABLE claude_code_instances ADD COLUMN claude_version VARCHAR(50);
ALTER TABLE claude_code_instances ADD COLUMN agent_count INTEGER DEFAULT 0;
ALTER TABLE claude_code_instances DROP COLUMN auto_registered;
```

## API Changes

| Old Endpoint | New Endpoint | Change |
|-------------|-------------|--------|
| `POST /api/v2/instances` | Same | Add SSH credentials |
| `POST /api/v2/instances/verify` | Same | SSH-based verify instead of HTTP |
| `POST /api/v2/instances/{id}/check` | Same | SSH health check |
| `POST /api/v2/instances/{id}/heartbeat` | Same | Accept richer data |
| — | `POST /api/v2/instances/{id}/install-claude` | New — install Claude Code |
| — | `POST /api/v2/instances/{id}/ship-agent` | New — ship backtesting agent |

## Files to Modify

| File | Action |
|------|--------|
| `apps/dashboard/src/pages/Network.tsx` | Rewrite |
| `apps/api/src/routes/instances.py` | Modify |
| `shared/db/models/openclaw_instance.py` → `claude_code_instance.py` | Rename + modify |
