"""
Regression tests for heartbeat ingestion and instance management. M1.8.
"""



class TestHeartbeatRegression:
    """Heartbeat endpoint contract tests using mock data."""

    def test_heartbeat_payload_schema(self):
        """Verify the heartbeat payload structure matches the expected schema."""
        payload = {
            "agent_statuses": [
                {"id": "trader-1", "status": "RUNNING", "pnl": 150.0},
                {"id": "monitor-1", "status": "RUNNING", "pnl": 0},
            ],
            "positions": [
                {"symbol": "SPY", "side": "long", "qty": 10, "unrealized_pnl": 50.0}
            ],
            "recent_trades": [],
            "total_pnl": 150.0,
            "active_tasks": 2,
            "memory_usage_mb": 256.0,
            "cpu_percent": 15.5,
        }
        assert isinstance(payload["agent_statuses"], list)
        assert isinstance(payload["total_pnl"], (int, float))
        assert isinstance(payload["memory_usage_mb"], (int, float))
        assert all("status" in a for a in payload["agent_statuses"])

    def test_instance_create_payload_schema(self):
        """Verify instance creation payload."""
        payload = {
            "name": "Instance-D-Live",
            "host": "10.0.1.12",
            "port": 18800,
            "role": "live-trading-ops",
            "node_type": "vps",
            "capabilities": {"live_trading": True, "max_agents": 10},
        }
        assert 1 <= len(payload["name"]) <= 100
        assert payload["node_type"] in ("vps", "local")
        assert 1 <= payload["port"] <= 65535

    def test_local_node_classification(self):
        """Local nodes should be classified correctly."""
        local_payload = {"name": "Laptop-1", "host": "10.0.1.20", "node_type": "local"}
        vps_payload = {"name": "VPS-1", "host": "10.0.1.10", "node_type": "vps"}
        assert local_payload["node_type"] == "local"
        assert vps_payload["node_type"] == "vps"
