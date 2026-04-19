"""Test Phase B.6 metrics — assert each metric name and label set match spec."""

import pytest
from prometheus_client import REGISTRY, generate_latest

from shared.observability.metrics import (
    agent_session_counter,
    circuit_breaker_gauge,
    discord_messages_counter,
    dlq_size_gauge,
    stream_lag_gauge,
    subagent_spawn_counter,
    tool_latency_histogram,
    trade_success_counter,
)


def test_tool_latency_histogram():
    """Tool latency has tool label and correct name."""
    tool_latency_histogram.labels(tool="parse_signal").observe(0.1)
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "phoenix_tool_duration_seconds" in output
    assert 'tool="parse_signal"' in output


def test_trade_success_counter():
    """Trade counter has status label."""
    trade_success_counter.labels(status="success").inc()
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "phoenix_trades_total" in output
    assert 'status="success"' in output


def test_agent_session_counter():
    """Agent session counter exists."""
    agent_session_counter.inc()
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "phoenix_agent_sessions_created_total" in output


def test_subagent_spawn_counter():
    """Sub-agent spawn counter exists."""
    subagent_spawn_counter.inc()
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "phoenix_subagent_spawned_total" in output


def test_circuit_breaker_gauge():
    """Circuit breaker gauge has name label and 0-2 values."""
    circuit_breaker_gauge.labels(name="robinhood").set(0)
    circuit_breaker_gauge.labels(name="yfinance").set(2)
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "phoenix_circuit_breaker_state" in output
    assert 'name="robinhood"' in output
    assert 'name="yfinance"' in output


def test_dlq_size_gauge():
    """DLQ size gauge has connector_id label."""
    dlq_size_gauge.labels(connector_id="test-connector").set(42)
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "phoenix_dlq_unresolved_total" in output
    assert 'connector_id="test-connector"' in output


def test_stream_lag_gauge():
    """Stream lag gauge has stream_key label."""
    stream_lag_gauge.labels(stream_key="stream:channel:test").set(12.5)
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "phoenix_redis_stream_lag_seconds" in output
    assert 'stream_key="stream:channel:test"' in output


def test_discord_messages_counter():
    """Discord messages counter exists."""
    discord_messages_counter.inc()
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "phoenix_discord_messages_total" in output


def test_all_metrics_registered():
    """All Phase B.6 metrics are in the registry."""
    metric_names = {
        "phoenix_tool_duration_seconds",
        "phoenix_trades_total",
        "phoenix_agent_sessions_created_total",
        "phoenix_subagent_spawned_total",
        "phoenix_circuit_breaker_state",
        "phoenix_dlq_unresolved_total",
        "phoenix_redis_stream_lag_seconds",
        "phoenix_discord_messages_total",
    }
    output = generate_latest(REGISTRY).decode("utf-8")
    for name in metric_names:
        assert name in output, f"Metric {name} not found in registry"
