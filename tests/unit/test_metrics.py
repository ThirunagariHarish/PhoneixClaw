from prometheus_client import generate_latest

from shared.metrics import (
    TRADE_COUNTER,
    TRADE_LATENCY,
    registry,
)


class TestMetrics:
    def test_registry_exists(self):
        assert registry is not None

    def test_trade_counter_labels(self):
        TRADE_COUNTER.labels(service="test", status="EXECUTED").inc()
        output = generate_latest(registry).decode("utf-8")
        assert "phoenix_trades_total" in output

    def test_trade_latency_labels(self):
        TRADE_LATENCY.labels(service="test").observe(0.1)
        output = generate_latest(registry).decode("utf-8")
        assert "phoenix_trade_latency_seconds" in output

    def test_generate_latest_produces_text(self):
        content = generate_latest(registry)
        assert isinstance(content, bytes)
        assert len(content) > 0
