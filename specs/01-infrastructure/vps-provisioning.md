# Spec: VPS Provisioning

## Purpose

Define how VPS instances are registered, provisioned with Claude Code, and maintained.

## Registration Flow

1. User navigates to Network tab → "Add Instance"
2. Fills in: name, host, SSH port (default 22), username, SSH private key (paste or upload)
3. UI calls `POST /api/v2/instances` with credentials
4. API encrypts SSH key with Fernet, stores in `claude_code_instances` table
5. API immediately runs health check via Agent Gateway

## Health Check Protocol

```python
async def check_health(instance_id) -> HealthStatus:
    conn = await pool.get_connection(instance_id)
    
    checks = {}
    
    # 1. Claude Code installed?
    result = await conn.run("claude --version 2>/dev/null || echo 'NOT_INSTALLED'")
    checks["claude_installed"] = "NOT_INSTALLED" not in result.stdout
    checks["claude_version"] = result.stdout.strip() if checks["claude_installed"] else None
    
    # 2. System resources
    result = await conn.run("free -m | awk '/Mem:/{print $2,$3,$4}'")
    total, used, free = result.stdout.strip().split()
    checks["memory_total_mb"] = int(total)
    checks["memory_used_mb"] = int(used)
    checks["memory_free_mb"] = int(free)
    
    result = await conn.run("df -h ~ | awk 'NR==2{print $4}'")
    checks["disk_free"] = result.stdout.strip()
    
    result = await conn.run("nproc")
    checks["cpu_cores"] = int(result.stdout.strip())
    
    # 3. Python available?
    result = await conn.run("python3 --version 2>/dev/null || echo 'NOT_INSTALLED'")
    checks["python_installed"] = "NOT_INSTALLED" not in result.stdout
    
    # 4. List running agents
    result = await conn.run("ls ~/agents/live/ 2>/dev/null || echo 'NONE'")
    checks["active_agents"] = [] if "NONE" in result.stdout else result.stdout.strip().split()
    
    return HealthStatus(**checks)
```

## Claude Code Installation

If Claude Code is not detected during health check:

```bash
# Install script shipped to VPS
curl -fsSL https://claude.ai/install.sh | sh

# Verify
claude --version

# Install Python dependencies for agent tools
pip3 install --user pandas numpy scikit-learn xgboost lightgbm \
    yfinance robin_stocks ta finnhub-python fredapi torch transformers
```

## Instance States

| State | Meaning |
|-------|---------|
| `ONLINE` | SSH reachable, Claude Code installed, healthy |
| `OFFLINE` | SSH unreachable |
| `PROVISIONING` | Claude Code being installed |
| `DEGRADED` | Reachable but low resources or errors |
| `ERROR` | Reachable but Claude Code broken |

## Database Schema

```sql
CREATE TABLE claude_code_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    host VARCHAR(255) NOT NULL,
    ssh_port INTEGER DEFAULT 22,
    ssh_username VARCHAR(100) NOT NULL,
    ssh_key_encrypted TEXT NOT NULL,          -- Fernet-encrypted private key
    role VARCHAR(50) DEFAULT 'general',       -- 'backtesting' | 'trading' | 'general'
    status VARCHAR(20) DEFAULT 'ONLINE',
    node_type VARCHAR(20) DEFAULT 'vps',      -- 'vps' | 'local'
    capabilities JSONB DEFAULT '{}',          -- health check results
    claude_version VARCHAR(50),
    agent_count INTEGER DEFAULT 0,
    last_heartbeat_at TIMESTAMPTZ,
    last_offline_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

## Files to Create/Modify

| File | Action |
|------|--------|
| `shared/db/models/claude_code_instance.py` | New |
| `apps/api/src/services/vps_provisioner.py` | New — install + configure Claude Code |
| `agents/install_vps.sh` | New — shell script for VPS setup |
