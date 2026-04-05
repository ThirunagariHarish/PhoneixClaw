# Spec: API Contract Changes

## Purpose

Document all new and modified API endpoints for the Claude Code transformation.

## New Endpoints

### Token Usage

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v2/token-usage` | Aggregate token usage (daily/weekly/monthly, by agent, by model) |
| `GET` | `/api/v2/token-usage/history` | Daily token usage over time for charts |

### Agent Trades (Live)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v2/agents/{id}/live-trades` | Live trade history from running agent |
| `POST` | `/api/v2/agents/{id}/live-trades` | Agent reports a new trade (callback) |
| `GET` | `/api/v2/agents/{id}/positions` | Current open positions |

### Agent Metrics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v2/agents/{id}/metrics` | Latest metrics snapshot |
| `POST` | `/api/v2/agents/{id}/metrics` | Agent reports metrics (callback) |
| `GET` | `/api/v2/agents/{id}/metrics/history` | Metrics over time for charts |

### Agent Chat

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v2/agents/{id}/chat` | Chat history |
| `POST` | `/api/v2/agents/{id}/chat` | Send message to agent (via SSH) |

### Agent Commands

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v2/agents/{id}/command` | Send operational command (pause/resume/update-config) |

### Instance Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v2/instances/{id}/install-claude` | Install Claude Code on VPS |
| `POST` | `/api/v2/instances/{id}/ship-agent` | Ship backtesting agent to VPS |
| `GET` | `/api/v2/instances/{id}/agents` | List agents running on instance |
| `GET` | `/api/v2/instances/{id}/logs` | Get instance-level logs |

## Modified Endpoints

### `POST /api/v2/agents` — Create Agent

New payload fields:
```json
{
  "name": "SPX Alerts Agent",
  "type": "trading",
  "channel_name": "spx-alerts",
  "channel_id": "987654321",
  "server_id": "123456789",
  "analyst_name": "Vinod",
  "vps_instance_id": "uuid-of-vps",
  "risk_params": {
    "max_position_size_pct": 5.0,
    "max_daily_loss_pct": 3.0,
    "confidence_threshold": 0.65
  }
}
```

Behavior change: After DB insert, calls Agent Gateway to:
1. Ship backtesting agent to VPS
2. Start backtesting with channel config
3. Stream progress back

### `POST /api/v2/instances` — Add Instance

New payload:
```json
{
  "name": "vps-main",
  "host": "192.168.1.100",
  "ssh_port": 22,
  "ssh_username": "ubuntu",
  "ssh_private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n...",
  "role": "backtesting",
  "node_type": "vps"
}
```

### `POST /api/v2/instances/verify` — Verify Instance

Changed from HTTP health check to SSH-based verification:
```json
{
  "host": "192.168.1.100",
  "ssh_port": 22,
  "ssh_username": "ubuntu",
  "ssh_private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n..."
}
```

Response:
```json
{
  "reachable": true,
  "claude_installed": true,
  "claude_version": "1.2.3",
  "python_installed": true,
  "memory_free_mb": 2048,
  "disk_free": "45G"
}
```

## Removed/Deprecated

| Endpoint | Reason |
|----------|--------|
| `POST /api/v2/instances/{id}/sync-skills` | Replaced by ship-agent flow |
| `POST /api/v2/agents/{id}/backtest-complete` | Replaced by backtesting agent callback |

## Authentication

All agent callback endpoints (`POST .../live-trades`, `POST .../metrics`, `POST .../heartbeat`) use a per-agent API key:

```
Authorization: Bearer {agent_api_key}
```

The API key is generated during agent creation and stored in the agent's `config.json` on VPS.

---

## Standardized Endpoint Naming

All agent-specific endpoints follow the pattern `/api/v2/agents/{id}/{resource}`:

| Resource | Endpoint | Notes |
|----------|----------|-------|
| Live trades | `/api/v2/agents/{id}/live-trades` | NOT `/trades` (avoids collision with backtest trades) |
| Positions | `/api/v2/agents/{id}/positions` | Current open positions |
| Metrics snapshot | `/api/v2/agents/{id}/metrics` | Latest snapshot |
| Metrics history | `/api/v2/agents/{id}/metrics/history` | Time series |
| Chat | `/api/v2/agents/{id}/chat` | GET history, POST message |
| Heartbeat | `/api/v2/agents/{id}/heartbeat` | POST from agent |
| Commands | `/api/v2/agents/{id}/command` | POST operational commands |

---

## Request/Response Schemas (Pydantic Models)

### Pagination

All list endpoints accept pagination parameters and return paginated responses:

```python
class PaginationParams(BaseModel):
    offset: int = 0
    limit: int = Field(default=50, le=200)
    sort_by: str = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"

class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int
    has_more: bool
```

Example: `GET /api/v2/agents/{id}/live-trades?offset=0&limit=20&sort_by=executed_at&sort_order=desc`

### Trade Schema

```python
class LiveTradeResponse(BaseModel):
    id: str
    agent_id: str
    ticker: str
    side: Literal["buy", "sell"]
    quantity: float
    entry_price: float
    exit_price: float | None
    pnl: float | None
    pnl_pct: float | None
    status: Literal["open", "closed", "cancelled"]
    confidence: float
    model_prediction: str
    matched_patterns: list[str]
    executed_at: datetime
    closed_at: datetime | None
```

### Metrics Schema

```python
class AgentMetricsResponse(BaseModel):
    agent_id: str
    daily_pnl: float
    total_pnl: float
    total_trades: int
    win_rate: float
    avg_confidence: float
    model_accuracy: float
    sharpe_ratio: float | None
    max_drawdown: float | None
    open_positions: int
    signals_today: int
    last_signal_at: datetime | None
    last_trade_at: datetime | None
    uptime_seconds: int
    status: str
```

### Chat Schema

```python
class ChatMessageRequest(BaseModel):
    message: str

class ChatMessageResponse(BaseModel):
    id: str
    role: Literal["user", "agent"]
    content: str
    timestamp: datetime
```

### Command Schema

```python
class AgentCommandRequest(BaseModel):
    command: Literal["pause", "resume", "update_config", "restart", "stop"]
    params: dict | None = None

class AgentCommandResponse(BaseModel):
    success: bool
    message: str
    command_id: str
```

---

## Error Response Schema

All error responses follow a standard format:

```python
class ErrorResponse(BaseModel):
    error: str          # Machine-readable error code
    detail: str         # Human-readable description
    status_code: int    # HTTP status code
    request_id: str     # For debugging/support

# Example:
{
    "error": "agent_not_found",
    "detail": "Agent with id 'abc-123' does not exist",
    "status_code": 404,
    "request_id": "req_7f2a3b"
}
```

Standard error codes:

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `validation_error` | 422 | Invalid request body |
| `not_found` | 404 | Resource doesn't exist |
| `unauthorized` | 401 | Missing or invalid auth |
| `forbidden` | 403 | Valid auth but insufficient permissions |
| `rate_limited` | 429 | Too many requests |
| `internal_error` | 500 | Server error |
| `agent_unreachable` | 502 | Cannot reach agent on VPS |
| `agent_busy` | 503 | Agent is processing another request |

---

## WebSocket/SSE for Streaming

### Backtest Progress Streaming

```
WS /ws/backtests/{backtest_id}/progress
```

Events:

```json
{"event": "step_started", "step": "transformation", "progress": 0}
{"event": "step_progress", "step": "transformation", "progress": 45, "detail": "Processing message 450/1000"}
{"event": "step_completed", "step": "transformation", "progress": 100}
{"event": "step_started", "step": "enrichment", "progress": 0}
{"event": "training_started", "model": "xgboost", "progress": 0}
{"event": "training_completed", "model": "xgboost", "accuracy": 0.72}
{"event": "backtest_completed", "best_model": "hybrid_ensemble", "accuracy": 0.78}
```

### Agent Activity Stream

```
WS /ws/agents/{agent_id}/activity
```

Events:

```json
{"event": "signal_detected", "ticker": "SPY", "timestamp": "..."}
{"event": "trade_executed", "ticker": "SPY", "side": "buy", "price": 450.00}
{"event": "position_update", "ticker": "SPY", "pnl": 2.50, "pnl_pct": 0.55}
{"event": "heartbeat", "status": "listening", "uptime": 3600}
```

---

## Idempotency Keys

Agent callback endpoints (trade reports, metrics, heartbeats) must be idempotent:

```
POST /api/v2/agents/{id}/live-trades
X-Idempotency-Key: trade_abc123_1234567890

POST /api/v2/agents/{id}/metrics
X-Idempotency-Key: metrics_abc123_20260403T120000
```

The API stores idempotency keys in Redis with a 24-hour TTL. Duplicate requests return the original response.

---

## Authentication Model

| Endpoint Category | Auth Method | Notes |
|-------------------|------------|-------|
| Dashboard endpoints (`GET /api/v2/agents`, etc.) | JWT (user session) | From login flow |
| Agent callbacks (`POST .../heartbeat`, etc.) | Agent API Key | `Authorization: Bearer {agent_api_key}` |
| Instance management (`POST .../install-claude`) | JWT + admin role | Only admin users |
| WebSocket connections | JWT in query param | `?token={jwt}` on connect |

Agent API keys are generated during agent creation, stored encrypted in DB, and injected into the agent's `config.json` on VPS.
