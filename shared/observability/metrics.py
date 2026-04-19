"""Phase B.6 observability metrics — shared Prometheus registry and metric helpers.

Provides:
- tool_latency_histogram — phoenix_tool_duration_seconds{tool}
- agent_session_counter — phoenix_agent_sessions_created_total
- subagent_spawn_counter — phoenix_subagent_spawned_total
- circuit_breaker_gauge_by_name — phoenix_circuit_breaker_state_by_name{name} (0=closed, 1=half_open, 2=open)
- dlq_size_gauge — phoenix_dlq_unresolved_total{connector_id}
- stream_lag_gauge — phoenix_redis_stream_lag_seconds{stream_key}
- discord_messages_counter — phoenix_discord_messages_total

Note: phoenix_trades_total already exists in shared.metrics.TRADE_COUNTER with {service, status} labels.
We reuse it for tool-side trade metrics.
"""

from prometheus_client import Counter, Gauge, Histogram

from shared.metrics import TRADE_COUNTER as trade_success_counter
from shared.metrics import registry

# Tool latency across parse_signal, enrich_single, inference, risk_check, technical_analysis, execute_trade
tool_latency_histogram = Histogram(
    "phoenix_tool_duration_seconds",
    "Duration of agent tool calls in seconds",
    ["tool"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    registry=registry,
)

# Agent session creation (primary, position_monitor, supervisor, etc.)
agent_session_counter = Counter(
    "phoenix_agent_sessions_created_total",
    "Agent sessions created",
    registry=registry,
)

# Sub-agent spawn count (position monitors)
subagent_spawn_counter = Counter(
    "phoenix_subagent_spawned_total",
    "Sub-agents spawned (position monitors)",
    registry=registry,
)

# Circuit breaker state gauge with "name" label (0=closed, 1=half_open, 2=open)
# Note: shared.metrics.CIRCUIT_BREAKER_STATE uses "service" label; we need "name" label for tool-side.
circuit_breaker_gauge = Gauge(
    "phoenix_circuit_breaker_state_by_name",
    "Circuit breaker state: 0=closed, 1=half_open, 2=open",
    ["name"],
    registry=registry,
)

# DLQ size (unresolved messages per connector)
dlq_size_gauge = Gauge(
    "phoenix_dlq_unresolved_total",
    "Unresolved dead letter messages by connector",
    ["connector_id"],
    registry=registry,
)

# Redis stream lag (seconds behind latest entry)
stream_lag_gauge = Gauge(
    "phoenix_redis_stream_lag_seconds",
    "Redis stream lag in seconds",
    ["stream_key"],
    registry=registry,
)

# Discord messages ingested
discord_messages_counter = Counter(
    "phoenix_discord_messages_total",
    "Discord messages persisted to DB and Redis",
    registry=registry,
)


__all__ = [
    "tool_latency_histogram",
    "trade_success_counter",
    "agent_session_counter",
    "subagent_spawn_counter",
    "circuit_breaker_gauge",
    "dlq_size_gauge",
    "stream_lag_gauge",
    "discord_messages_counter",
]
