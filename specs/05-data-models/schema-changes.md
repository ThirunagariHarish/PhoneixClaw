# Spec: Database Schema Changes

## Purpose

Document all database model changes needed for the Claude Code transformation.

## New Tables

### `claude_code_instances` (replaces `openclaw_instances`)

```sql
CREATE TABLE claude_code_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    host VARCHAR(255) NOT NULL,
    ssh_port INTEGER NOT NULL DEFAULT 22,
    ssh_username VARCHAR(100) NOT NULL DEFAULT 'root',
    ssh_key_encrypted TEXT NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'general',
    status VARCHAR(20) NOT NULL DEFAULT 'ONLINE',
    node_type VARCHAR(20) NOT NULL DEFAULT 'vps',
    capabilities JSONB NOT NULL DEFAULT '{}',
    claude_version VARCHAR(50),
    agent_count INTEGER NOT NULL DEFAULT 0,
    last_heartbeat_at TIMESTAMPTZ,
    last_offline_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `agent_trades` (live trade records from agents)

```sql
CREATE TABLE agent_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    ticker VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    option_type VARCHAR(10),
    strike FLOAT,
    expiry DATE,
    entry_price FLOAT NOT NULL,
    exit_price FLOAT,
    quantity INTEGER NOT NULL DEFAULT 1,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    pnl_dollar FLOAT,
    pnl_pct FLOAT,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    model_confidence FLOAT,
    pattern_matches INTEGER,
    reasoning TEXT,
    signal_raw TEXT,
    broker_order_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_trades_agent ON agent_trades(agent_id);
CREATE INDEX idx_agent_trades_status ON agent_trades(status);
```

### `agent_metrics` (periodic metrics snapshots)

```sql
CREATE TABLE agent_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    portfolio_value FLOAT,
    daily_pnl FLOAT,
    open_positions INTEGER,
    trades_today INTEGER,
    win_rate FLOAT,
    avg_confidence FLOAT,
    signals_processed INTEGER,
    tokens_used INTEGER,
    status VARCHAR(20)
);

CREATE INDEX idx_agent_metrics_agent_time ON agent_metrics(agent_id, timestamp DESC);
```

### `agent_chat_messages` (chat history with agents)

```sql
CREATE TABLE agent_chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    role VARCHAR(10) NOT NULL,  -- 'user' or 'agent'
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_chat_agent ON agent_chat_messages(agent_id, created_at);
```

### `token_usage` (daily token usage tracking)

```sql
CREATE TABLE token_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id UUID REFERENCES claude_code_instances(id),
    agent_id UUID REFERENCES agents(id),
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    model VARCHAR(50) NOT NULL DEFAULT 'claude-sonnet',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd FLOAT NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_token_usage_date ON token_usage(date);
CREATE INDEX idx_token_usage_agent ON token_usage(agent_id, date);
```

## Modified Tables

### `agents` — add fields

```sql
ALTER TABLE agents ADD COLUMN source VARCHAR(50) DEFAULT 'manual';       -- 'manual' | 'backtesting'
ALTER TABLE agents ADD COLUMN channel_name VARCHAR(100);
ALTER TABLE agents ADD COLUMN analyst_name VARCHAR(100);
ALTER TABLE agents ADD COLUMN model_type VARCHAR(50);
ALTER TABLE agents ADD COLUMN model_accuracy FLOAT;
ALTER TABLE agents ADD COLUMN daily_pnl FLOAT DEFAULT 0;
ALTER TABLE agents ADD COLUMN total_pnl FLOAT DEFAULT 0;
ALTER TABLE agents ADD COLUMN total_trades INTEGER DEFAULT 0;
ALTER TABLE agents ADD COLUMN win_rate FLOAT DEFAULT 0;
ALTER TABLE agents ADD COLUMN last_signal_at TIMESTAMPTZ;
ALTER TABLE agents ADD COLUMN last_trade_at TIMESTAMPTZ;
ALTER TABLE agents ADD COLUMN vps_instance_id UUID REFERENCES claude_code_instances(id);
```

### `agents.instance_id` — re-target FK

Currently references `openclaw_instances`. Needs migration to `claude_code_instances` or rename in place.

## Migration Strategy

1. Rename `openclaw_instances` → `claude_code_instances`
2. Add new columns to `claude_code_instances`
3. Add new tables (`agent_trades`, `agent_metrics`, `agent_chat_messages`, `token_usage`)
4. Add new columns to `agents`
5. Update FK on `agents.instance_id`

## ORM Models to Create/Modify

| File | Action |
|------|--------|
| `shared/db/models/claude_code_instance.py` | New (or rename from openclaw) |
| `shared/db/models/agent_trade.py` | New |
| `shared/db/models/agent_metric.py` | New |
| `shared/db/models/agent_chat.py` | New |
| `shared/db/models/token_usage.py` | New |
| `shared/db/models/agent.py` | Modify — add fields |
| `shared/db/models/__init__.py` | Modify — register new models |
