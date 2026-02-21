"""Shared Prometheus metrics and a FastAPI route factory for /metrics."""

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

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


async def metrics_endpoint(request: Request) -> Response:
    """Return Prometheus text format metrics."""
    return Response(
        content=generate_latest(registry),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def create_metrics_route(app):
    """Add /metrics endpoint to a FastAPI/Starlette app."""
    app.add_route("/metrics", metrics_endpoint, methods=["GET"])
