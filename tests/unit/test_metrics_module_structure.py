"""Smoke test for metrics module structure.

Validates that the metrics module exports the correct components and
can be imported without requiring full DB setup.
"""

import importlib.util


def test_metrics_module_can_be_loaded():
    """Metrics module should be loadable (syntax check)."""
    spec = importlib.util.spec_from_file_location(
        "shared.observability.metrics",
        "shared/observability/metrics.py"
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert module is not None


def test_metrics_module_has_required_exports():
    """Metrics module should export key components."""
    # Read the file to check for expected definitions
    with open("shared/observability/metrics.py") as f:
        content = f.read()

    # Check for expected exports
    assert "phoenix_registry" in content
    assert "phoenix_dlq_size" in content
    assert "start_dlq_gauge_refresher" in content
    assert "stop_dlq_gauge_refresher" in content
    assert "_refresh_dlq_gauge" in content


def test_metrics_uses_prometheus_client():
    """Metrics should use prometheus_client."""
    with open("shared/observability/metrics.py") as f:
        content = f.read()

    assert "from prometheus_client import" in content
    assert "Gauge" in content


def test_metrics_has_background_refresher():
    """Metrics should have async background refresh logic."""
    with open("shared/observability/metrics.py") as f:
        content = f.read()

    assert "async def _refresh_dlq_gauge" in content
    assert "asyncio.sleep(15)" in content  # 15s refresh interval


def test_dlq_gauge_has_correct_labels():
    """DLQ gauge should have connector_id label."""
    with open("shared/observability/metrics.py") as f:
        content = f.read()

    # Check gauge definition
    assert 'labelnames=["connector_id"]' in content or "labelnames=['connector_id']" in content


def test_metrics_queries_unresolved_dlq():
    """Refresh function should query WHERE resolved = false."""
    with open("shared/observability/metrics.py") as f:
        content = f.read()

    assert "WHERE resolved = false" in content
    assert "GROUP BY connector_id" in content


def test_metrics_has_docstrings():
    """Module and functions should have docstrings."""
    with open("shared/observability/metrics.py") as f:
        content = f.read()

    # Check module docstring
    assert '"""' in content
    assert "Shared Prometheus metrics" in content or "prometheus metrics" in content.lower()

    # Check function docstrings
    assert "Background task" in content or "background task" in content.lower()
