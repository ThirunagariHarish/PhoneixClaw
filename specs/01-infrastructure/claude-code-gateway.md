# Spec: Claude Code Agent Gateway

## Purpose

The Agent Gateway is a Python module in `apps/api/src/services/` that manages communication between the Phoenix API and Claude Code instances running on remote VPS machines via SSH.

## API Surface

### Internal (used by API routes)

```python
class AgentGateway:
    async def check_health(instance_id: UUID) -> HealthStatus
    async def install_claude_code(instance_id: UUID) -> bool
    async def ship_agent(instance_id: UUID, agent_type: str, agent_config: dict) -> str
    async def run_command(instance_id: UUID, command: str, timeout: int = 3600) -> CommandResult
    async def stream_command(instance_id: UUID, command: str) -> AsyncIterator[str]
    async def list_agents(instance_id: UUID) -> list[AgentInfo]
    async def get_agent_logs(instance_id: UUID, agent_name: str, lines: int = 100) -> str
    async def send_message(instance_id: UUID, agent_name: str, message: str) -> str
```

### SSH Connection Management

```python
class SSHConnectionPool:
    """Maintains persistent SSH connections to VPS instances."""
    async def get_connection(instance_id: UUID) -> asyncssh.SSHClientConnection
    async def close_connection(instance_id: UUID)
    async def close_all()
```

## Implementation Details

### Dependencies

- `asyncssh` — async SSH client for Python
- SSH keys stored encrypted in Postgres (`claude_code_instances` table)

### Connection Flow

1. User registers VPS in Network tab with: host, port (SSH), username, SSH private key (or password)
2. Gateway stores credentials encrypted (Fernet, same as broker creds)
3. On first connect: verify host key, test `claude --version`
4. Connection pooled for reuse; reconnect on failure with exponential backoff

### Command Execution

```python
async def run_command(instance_id, command, timeout=3600):
    conn = await pool.get_connection(instance_id)
    result = await conn.run(command, timeout=timeout)
    return CommandResult(
        exit_code=result.exit_status,
        stdout=result.stdout,
        stderr=result.stderr,
    )
```

### Shipping an Agent

```python
async def ship_agent(instance_id, agent_type, agent_config):
    conn = await pool.get_connection(instance_id)
    local_path = f"agents/{agent_type}/"
    remote_path = f"~/agents/{agent_type}/"
    
    # Create remote directory
    await conn.run(f"mkdir -p {remote_path}")
    
    # Copy agent files via SFTP
    async with conn.start_sftp_client() as sftp:
        await sftp.put(local_path, remote_path, recurse=True)
    
    # Write instance-specific config
    config_json = json.dumps(agent_config)
    await conn.run(f"echo '{config_json}' > {remote_path}/config.json")
    
    return remote_path
```

### Running Backtesting

```python
async def start_backtesting(instance_id, agent_config):
    # Ship the backtesting agent
    remote_path = await ship_agent(instance_id, "backtesting", agent_config)
    
    # Run Claude Code in the agent directory
    command = (
        f"cd {remote_path} && "
        f"claude --print 'Run the backtesting pipeline with config.json. "
        f"Report progress to stdout as JSON lines.'"
    )
    
    # Stream output for progress tracking
    async for line in stream_command(instance_id, command):
        if line.startswith('{"progress":'):
            yield json.loads(line)  # Progress events
```

## Error Handling

- SSH connection timeout: 30s connect, configurable command timeout
- Retry with backoff on transient SSH errors (connection reset, timeout)
- If Claude Code not installed: `install_claude_code()` runs the install script
- If agent folder missing: re-ship before running
- All errors logged to `AgentLog` table with `level='ERROR'`

## Security

- SSH private keys encrypted at rest with Fernet (same as `CREDENTIAL_ENCRYPTION_KEY`)
- No password auth in production; key-based only
- Gateway never exposes raw SSH access to the dashboard
- VPS firewall should only allow SSH from Phoenix API server IP

## Files to Create/Modify

| File | Action |
|------|--------|
| `apps/api/src/services/agent_gateway.py` | New — main gateway class |
| `apps/api/src/services/ssh_pool.py` | New — SSH connection pool |
| `shared/db/models/claude_code_instance.py` | New — replaces `openclaw_instance.py` |
| `apps/api/src/routes/instances.py` | Modify — update for Claude Code |
| `pyproject.toml` | Add `asyncssh` dependency |
