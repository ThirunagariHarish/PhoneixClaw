"""Shared metrics — Prometheus exporters + portfolio math helpers."""

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

from .portfolio_math import (
    current_drawdown,
    max_drawdown,
    profit_factor,
    rolling_sharpe,
    win_rate,
)

registry = CollectorRegistry()

TRADE_COUNTER = Counter(
    "phoenix_trades_total",
    "Total trades processed",
    ["service", "status"],
    registry=registry,
)

TRADE_LATENCY = Histogram(
    "phoenix_trade_latency_seconds",
    "Trade execution latency in seconds",
    ["service"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=registry,
)

KAFKA_MESSAGES = Counter(
    "phoenix_kafka_messages_total",
    "Kafka messages consumed",
    ["service", "topic"],
    registry=registry,
)

OPEN_POSITIONS = Gauge(
    "phoenix_open_positions",
    "Current open positions count",
    ["service"],
    registry=registry,
)

HTTP_REQUESTS = Counter(
    "phoenix_http_requests_total",
    "HTTP requests served",
    ["service", "method", "path", "status"],
    registry=registry,
)

HTTP_LATENCY = Histogram(
    "phoenix_http_latency_seconds",
    "HTTP request latency",
    ["service", "method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0],
    registry=registry,
)

WS_CONNECTIONS = Gauge(
    "phoenix_ws_connections",
    "Active WebSocket connections",
    ["channel"],
    registry=registry,
)

CIRCUIT_BREAKER_STATE = Gauge(
    "phoenix_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
    ["service"],
    registry=registry,
)

ERROR_COUNTER = Counter(
    "phoenix_errors_total",
    "Application errors",
    ["service", "error_type"],
    registry=registry,
)

AGENTS_SPAWNED = Counter(
    "phoenix_agents_spawned_total",
    "Agent sessions spawned",
    ["agent_type", "result"],
    registry=registry,
)

AGENT_TOOL_CALLS = Counter(
    "phoenix_agent_tool_calls_total",
    "Tool invocations from agents",
    ["agent_type", "tool"],
    registry=registry,
)

LLM_TOKENS = Counter(
    "phoenix_llm_tokens_total",
    "LLM tokens consumed",
    ["agent_type", "model", "direction"],
    registry=registry,
)

LLM_COST_USD = Counter(
    "phoenix_llm_cost_usd_total",
    "LLM cost in USD",
    ["agent_type", "model"],
    registry=registry,
)

TRADE_SIGNALS_LOGGED = Counter(
    "phoenix_trade_signals_logged_total",
    "Trade signals logged to trade_signals table",
    ["decision"],
    registry=registry,
)

ACTIVE_AGENTS = Gauge(
    "phoenix_active_agents",
    "Currently running agent sessions",
    ["agent_type"],
    registry=registry,
)

AGENT_QUEUE_DEPTH = Gauge(
    "phoenix_agent_queue_depth",
    "Pending spawn requests in queue (Phase H5 semaphores)",
    ["queue"],
    registry=registry,
)

DATA_DIR_BYTES = Gauge(
    "phoenix_data_dir_bytes",
    "Total bytes in /app/data directory",
    registry=registry,
)

DB_POOL_SIZE = Gauge(
    "phoenix_db_pool_size",
    "Current SQLAlchemy pool size",
    ["state"],
    registry=registry,
)

SCHEDULER_JOB_RUNS = Counter(
    "phoenix_scheduler_job_runs_total",
    "Scheduler job invocations",
    ["job_id", "result"],
    registry=registry,
)


async def metrics_endpoint(request: Request) -> Response:
    """Return Prometheus text format metrics."""
    return Response(
        content=generate_latest(registry),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def create_metrics_route(app):
    """Add /metrics endpoint to a FastAPI/Starlette app."""
    app.add_route("/metrics", metrics_endpoint, methods=["GET"])


__all__ = [
    "registry",
    "TRADE_COUNTER", "TRADE_LATENCY", "KAFKA_MESSAGES", "OPEN_POSITIONS",
    "HTTP_REQUESTS", "HTTP_LATENCY", "WS_CONNECTIONS", "CIRCUIT_BREAKER_STATE",
    "ERROR_COUNTER", "AGENTS_SPAWNED", "AGENT_TOOL_CALLS", "LLM_TOKENS",
    "LLM_COST_USD", "TRADE_SIGNALS_LOGGED", "ACTIVE_AGENTS", "AGENT_QUEUE_DEPTH",
    "DATA_DIR_BYTES", "DB_POOL_SIZE", "SCHEDULER_JOB_RUNS",
    "metrics_endpoint", "create_metrics_route",
    "rolling_sharpe", "max_drawdown", "current_drawdown", "win_rate", "profit_factor",
]
