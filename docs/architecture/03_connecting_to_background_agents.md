# Connecting to Background Claude Agents Through Terminal

A complete guide to **finding, inspecting, debugging, and interacting with** Claude Code agents that are running in the background.

---

## TL;DR

Every Claude Code agent is a **subprocess of the `phoenix-api` Docker container**. To interact with one:

```bash
# 1. Find the API container
docker ps | grep phoenix-api

# 2. Exec into it
docker exec -it <api-container-name> bash

# 3. Look at agent working directories
ls /app/data/live_agents/
ls /app/data/backtest_*/

# 4. Tail the agent's logs
tail -f /app/data/live_agents/<agent-id>/trades.log

# 5. See running Claude Code processes
ps aux | grep claude
```

---

## Understanding Where Agents Live

### Production (k3s VPS)

```
SSH layer:        root@69.62.86.166
↓
Docker layer:     phoenix-api container
↓
Process layer:    uvicorn (PID 1)
                  └── Python claude_agent_sdk subprocess (one per running agent)
                          └── Claude Code CLI process
                                  └── Bash subprocesses (running tools)
↓
Filesystem:       /app/data/live_agents/{agent_id}/
                  /app/data/backtest_{agent_id}/output/v{N}/
                  /app/data/supervisor/{date}/
```

### Local development

Same layout but on your laptop:

```
~/Projects/TradingBot/ProjectPhoneix/
├── data/
│   ├── live_agents/{id}/
│   ├── backtest_{id}/
│   └── supervisor/{date}/
```

---

## Step-by-Step: Connecting to Production

### 1. SSH to the VPS

```bash
ssh root@69.62.86.166
```

(Replace with your VPS IP. The k3s deploy script uses `root@69.62.86.166`.)

### 2. List running Phoenix containers

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep phoenix
```

Expected output:
```
phoenix-api-xxxxx          Up 2 hours    0.0.0.0:8011->8011/tcp
phoenix-dashboard-xxxxx    Up 2 hours    0.0.0.0:3000->3000/tcp
phoenix-postgres-xxxxx     Up 2 hours    5432/tcp
phoenix-redis-xxxxx        Up 2 hours    6379/tcp
```

### 3. Save the API container name as a shell variable

```bash
API=$(docker ps --format "{{.Names}}" | grep phoenix-api | head -1)
echo "API container: $API"
```

### 4. Exec into the API container

```bash
docker exec -it $API bash
```

You're now inside the container. Your prompt will look like `phoenix@xxxxxx:/app$` or `root@xxxxxx:/app#`.

---

## Inspecting Running Agents (Inside the Container)

### List all currently running agent processes

```bash
ps auxf | grep -E 'claude|python.*tools' | grep -v grep
```

This shows the process tree. You'll see:
- The main `uvicorn` process
- One Python subprocess per active Claude Code session
- The `claude` CLI process inside each
- Any tool scripts the agent is currently running

### List active agent working directories

```bash
ls -la /app/data/live_agents/
ls -la /app/data/backtest_*/ 2>/dev/null
ls -la /app/data/supervisor/ 2>/dev/null
```

Each subdirectory is one agent's workspace.

### See which agents are tracked in the database

From inside the container:

```bash
python3 -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    async with engine.begin() as conn:
        result = await conn.execute(text('''
            SELECT id, name, status, worker_status, type, current_mode
            FROM agents
            ORDER BY created_at DESC
            LIMIT 20
        '''))
        for row in result:
            print(f'{row.id} | {row.name:30} | {row.status:18} | {row.worker_status:10} | {row.type}')

asyncio.run(main())
"
```

### See active Claude Code sessions

```bash
python3 -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    async with engine.begin() as conn:
        result = await conn.execute(text('''
            SELECT id, agent_id, agent_type, session_role, status,
                   working_dir, started_at, position_ticker
            FROM agent_sessions
            WHERE status IN ('running', 'starting')
            ORDER BY started_at DESC
        '''))
        for row in result:
            print(f'{row.session_role or \"primary\":15} | {row.agent_type:18} | '
                  f'{row.status:10} | {row.position_ticker or \"-\":6} | {row.working_dir}')

asyncio.run(main())
"
```

---

## Watching an Agent Live

### Tail the agent's reports to Phoenix

Every agent calls `report_to_phoenix.py` which logs to stderr. To see what an agent is doing in real time:

```bash
docker logs -f $API 2>&1 | grep "<agent-id-prefix>"
```

Example: if your agent ID starts with `abc123`:

```bash
docker logs -f $API 2>&1 | grep "abc123"
```

### Watch the agent's working directory for file changes

```bash
docker exec -it $API bash -c "
  cd /app/data/live_agents/<agent-id> && \
  ls -la --time-style=full-iso | sort -k 6,7
"
```

To watch for new files appearing in real time:

```bash
docker exec -it $API bash -c "
  cd /app/data/live_agents/<agent-id> && \
  watch -n 2 'ls -lt | head -20'
"
```

### Read the latest log files

```bash
docker exec -it $API bash -c "
  cd /app/data/live_agents/<agent-id> && \
  tail -f trades.log 2>/dev/null || tail -f *.log 2>/dev/null
"
```

### Inspect the agent's pending tasks queue

When you call `gateway.send_task()` or chat with an agent, the instruction is queued in `pending_tasks.json`:

```bash
docker exec -it $API cat /app/data/live_agents/<agent-id>/pending_tasks.json | python3 -m json.tool
```

### Inspect the agent's positions

```bash
docker exec -it $API cat /app/data/live_agents/<agent-id>/positions.json | python3 -m json.tool
```

### Inspect the agent's paper trades (if in PAPER mode)

```bash
docker exec -it $API cat /app/data/live_agents/<agent-id>/paper_trades.json | python3 -m json.tool
```

### Inspect the agent's watchlist

```bash
docker exec -it $API cat /app/data/live_agents/<agent-id>/watchlist.json | python3 -m json.tool
```

---

## Inspecting Backtesting Agents

### Find the latest backtest run for an agent

```bash
docker exec -it $API cat /app/data/backtest_<agent-id>/latest.json
```

This tells you which version directory is the latest.

### List all backtest versions

```bash
docker exec -it $API ls -la /app/data/backtest_<agent-id>/output/
```

You'll see `v1/`, `v2/`, `v3/`, etc.

### Inspect a backtest's outputs

```bash
docker exec -it $API ls -la /app/data/backtest_<agent-id>/output/v3/
```

Key files:
- `transformed.parquet` — raw trade data from Discord
- `enriched.parquet` — with ~200 market features added
- `models/` — trained ML models
- `models/best_model.json` — which model won + scores
- `model_selection.json` — which models were chosen and why
- `patterns.json` — discovered trading patterns
- `explainability.json` — top features
- `live_agent/manifest.json` — the manifest that gets loaded into the live agent

### Read backtest progress logs

```bash
docker exec -it $API tail -100 /var/log/phoenix-api.log 2>/dev/null || \
docker logs $API 2>&1 | tail -200 | grep -i 'backtest\|enrich\|train'
```

---

## Inspecting Position Sub-Agents

Every open position gets its own Claude Code session. They live under the parent analyst's directory:

```bash
docker exec -it $API ls -la /app/data/live_agents/<analyst-agent-id>/positions/
```

Output looks like:
```
AAPL_20260406_143000/
TSLA_20260406_151230/
SPY_20260406_153000/
```

### Inspect a specific position monitor

```bash
docker exec -it $API ls -la /app/data/live_agents/<analyst-id>/positions/AAPL_20260406_143000/

# Read its assigned position
docker exec -it $API cat /app/data/live_agents/<analyst-id>/positions/AAPL_20260406_143000/position.json

# Read the latest exit decision
docker exec -it $API ls -t /app/data/live_agents/<analyst-id>/positions/AAPL_20260406_143000/exit_check_*.json | head -1 | xargs cat | python3 -m json.tool
```

---

## Sending Commands to a Running Agent

### Method 1: Via the dashboard chat tab

The chat tab calls `POST /api/v2/chat/send` with the agent ID, which calls `gateway.send_task()` which queues the instruction in `pending_tasks.json` for the agent to pick up.

### Method 2: Via curl from your laptop

```bash
curl -X POST https://cashflowus.com/api/v2/agents/<agent-id>/instruct \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Run pre-market analysis now and report findings"}'
```

### Method 3: Via WhatsApp

Reply to any Phoenix WhatsApp notification with:
```
@SPXDiscord Pause trading for 30 minutes, market looks volatile
```

The webhook (`/webhook/whatsapp`) parses the `@agent_name` mention and routes the instruction.

### Method 4: Direct file edit (advanced)

You can manually queue a task by editing the agent's `pending_tasks.json`:

```bash
docker exec -it $API bash -c "
  cd /app/data/live_agents/<agent-id> && \
  python3 -c \"
import json, uuid
from datetime import datetime, timezone
tasks_file = 'pending_tasks.json'
try:
    tasks = json.load(open(tasks_file))
except FileNotFoundError:
    tasks = []
tasks.append({
    'id': str(uuid.uuid4()),
    'prompt': 'Stop monitoring AAPL and close all open positions in tech sector',
    'status': 'pending',
    'created_at': datetime.now(timezone.utc).isoformat(),
})
json.dump(tasks, open(tasks_file, 'w'), indent=2)
print('queued')
\"
"
```

---

## Reading the Agent's "Mind"

Each agent has these files you can read to understand its state:

| File | Contents |
|---|---|
| `CLAUDE.md` | The agent's instructions (rendered from Jinja2 template) |
| `config.json` | Risk params, credentials, channel info |
| `manifest.json` | Rules, character, models, knowledge (if present) |
| `positions.json` | Open positions |
| `paper_trades.json` | Paper trading entries |
| `watchlist.json` | Low-confidence signals being monitored |
| `pending_tasks.json` | User instructions queued for the agent |
| `models/` | Trained ML model artifacts |

To dump everything for debugging:

```bash
docker exec -it $API bash -c "
  cd /app/data/live_agents/<agent-id> && \
  for f in CLAUDE.md config.json positions.json paper_trades.json watchlist.json pending_tasks.json; do
    echo '======================================='
    echo \"FILE: \$f\"
    echo '======================================='
    cat \$f 2>/dev/null || echo '(missing)'
    echo
  done
"
```

---

## Killing or Restarting an Agent

### Stop a single agent gracefully (preserves session for resume)

From your laptop:
```bash
curl -X POST https://cashflowus.com/api/v2/agents/<agent-id>/pause
```

### Stop and discard

```bash
curl -X POST https://cashflowus.com/api/v2/agents/<agent-id>/stop
```

### Resume a paused agent

```bash
curl -X POST https://cashflowus.com/api/v2/agents/<agent-id>/resume
```

### Force-kill a Claude Code subprocess (last resort)

Find the PID:
```bash
docker exec -it $API ps auxf | grep claude
```

Kill it:
```bash
docker exec -it $API kill -9 <pid>
```

The `agent_gateway.py` `_running_tasks` dict will detect the dead task on the next status check.

---

## Common Debugging Scenarios

### "Agent says it's RUNNING but I see no activity"

1. Check if the Claude Code process is actually alive:
   ```bash
   docker exec -it $API ps aux | grep claude
   ```
2. If no process exists, the gateway has stale state. Restart the agent:
   ```bash
   curl -X POST https://cashflowus.com/api/v2/agents/<id>/stop
   curl -X POST https://cashflowus.com/api/v2/agents/<id>/promote
   ```

### "Backtest is stuck"

1. Find the version directory:
   ```bash
   docker exec -it $API cat /app/data/backtest_<id>/latest.json
   ```
2. See which step it's on:
   ```bash
   docker exec -it $API ls -lt /app/data/backtest_<id>/output/v<N>/ | head -10
   ```
   The most recent file tells you the last step that completed.
3. Check the agent's stdout/stderr in API logs:
   ```bash
   docker logs $API --tail 500 2>&1 | grep -A2 "<id-prefix>"
   ```

### "Agent isn't reading my chat messages"

The agent polls `pending_tasks.json` periodically. If it's stuck in a loop and not checking, you can:
1. Restart it (`POST /pause` then `POST /resume`)
2. Or manually trigger a re-read by writing a sentinel file:
   ```bash
   docker exec -it $API touch /app/data/live_agents/<id>/CHECK_TASKS_NOW
   ```

### "I want to see what an agent has been thinking"

Claude Code sessions don't persist their full reasoning, but you can see all the tool invocations and their outputs:

```bash
docker logs $API --tail 1000 2>&1 | grep -E "tool_use|tool_result"
```

For full transcripts, you need to inspect the Claude Code session log files. These live in:

```bash
docker exec -it $API find / -name "*.session.json" 2>/dev/null
```

(The exact location depends on Claude Code SDK version.)

---

## Database Queries for Live State

Get a full snapshot of one agent's state:

```bash
docker exec -it $API python3 -c "
import asyncio, os, json
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

AGENT_ID = '<paste-agent-uuid>'

async def main():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    async with engine.begin() as conn:
        # Agent
        result = await conn.execute(text('SELECT * FROM agents WHERE id = :id'), {'id': AGENT_ID})
        agent = result.first()
        if agent:
            print('=== AGENT ===')
            print(f'  name: {agent.name}')
            print(f'  status: {agent.status}')
            print(f'  worker_status: {agent.worker_status}')
            print(f'  current_mode: {agent.current_mode}')
            print(f'  total_trades: {agent.total_trades}')
            print(f'  win_rate: {agent.win_rate}')

        # Latest backtest
        result = await conn.execute(text('''
            SELECT id, status, current_step, progress_pct, backtesting_version
            FROM agent_backtests WHERE agent_id = :id
            ORDER BY created_at DESC LIMIT 1
        '''), {'id': AGENT_ID})
        bt = result.first()
        if bt:
            print('\n=== LATEST BACKTEST ===')
            print(f'  status: {bt.status}')
            print(f'  step: {bt.current_step}')
            print(f'  progress: {bt.progress_pct}%')
            print(f'  version: {bt.backtesting_version}')

        # Active sessions
        result = await conn.execute(text('''
            SELECT id, agent_type, session_role, status, working_dir, position_ticker
            FROM agent_sessions WHERE agent_id = :id AND status IN ('running', 'starting')
        '''), {'id': AGENT_ID})
        print('\n=== ACTIVE SESSIONS ===')
        for s in result:
            tag = f'[{s.position_ticker}]' if s.position_ticker else ''
            print(f'  {s.session_role:15} {s.agent_type:18} {s.status:10} {tag}')
            print(f'      dir: {s.working_dir}')

        # Recent trades
        result = await conn.execute(text('''
            SELECT ticker, side, status, decision_status, pnl_dollar, created_at
            FROM agent_trades WHERE agent_id = :id
            ORDER BY created_at DESC LIMIT 10
        '''), {'id': AGENT_ID})
        print('\n=== RECENT TRADES ===')
        for t in result:
            print(f'  {t.created_at} | {t.ticker:6} {t.side:4} {t.status:10} '
                  f'{t.decision_status:10} pnl=\${t.pnl_dollar or 0:.2f}')

asyncio.run(main())
"
```

---

## Quick Reference: Useful One-Liners

```bash
# All running agent processes
docker exec $API ps auxf | grep -E 'claude|python.*tools' | grep -v grep

# Disk usage per agent
docker exec $API du -sh /app/data/live_agents/* 2>/dev/null

# Number of position sub-agents per parent
docker exec $API bash -c 'for d in /app/data/live_agents/*/positions/; do echo "$(ls $d 2>/dev/null | wc -l) $d"; done'

# Latest activity across all agents
docker exec $API bash -c 'find /app/data/live_agents -type f -mmin -5 2>/dev/null | head -20'

# Tail all agent logs at once
docker exec $API bash -c 'tail -f /app/data/live_agents/*/trades.log 2>/dev/null'

# Count active Claude Code sessions
docker exec $API ps aux | grep -c '[c]laude '

# Memory usage of API container
docker stats $API --no-stream

# Recent error logs
docker logs $API --tail 200 2>&1 | grep -i "error\|exception\|traceback"

# Restart the API (which kills all agent sessions — use carefully)
docker restart $API
```

---

## Local Development Equivalents

If you're running locally (`make run-api`), all the above commands work without Docker:

```bash
# List agents
ls ~/Projects/TradingBot/ProjectPhoneix/data/live_agents/

# Tail an agent's logs
tail -f ~/Projects/TradingBot/ProjectPhoneix/data/live_agents/<id>/trades.log

# Read pending tasks
cat ~/Projects/TradingBot/ProjectPhoneix/data/live_agents/<id>/pending_tasks.json | jq

# See running Claude processes
ps aux | grep claude

# Test endpoints against local API
curl http://localhost:8011/api/v2/agents
```

---

## Cheat Sheet: Quick Workflow

```bash
# === On your laptop ===
ssh root@69.62.86.166

# === On the VPS ===
API=$(docker ps --format '{{.Names}}' | grep phoenix-api | head -1)

# Pick an agent to inspect
docker exec $API ls /app/data/live_agents/

# Save its ID
AGENT_ID=<paste-here>

# Quick state snapshot
docker exec -it $API bash -c "
  echo '=== POSITIONS ==='
  cat /app/data/live_agents/$AGENT_ID/positions.json 2>/dev/null
  echo
  echo '=== PENDING TASKS ==='
  cat /app/data/live_agents/$AGENT_ID/pending_tasks.json 2>/dev/null
  echo
  echo '=== SUB-AGENTS ==='
  ls /app/data/live_agents/$AGENT_ID/positions/ 2>/dev/null
"

# Watch live activity
docker logs -f $API 2>&1 | grep --line-buffered $AGENT_ID
```

---

## Future: SSH Directly Into an Agent

Phase 5.2 of the architecture plan calls for a "Terminal" tab in the dashboard that opens a WebSocket-based shell into an agent's working directory. This is not yet implemented but the AgentSession model has `host_name` and `pid` fields ready for it.

Until then, use `docker exec` as shown above.
