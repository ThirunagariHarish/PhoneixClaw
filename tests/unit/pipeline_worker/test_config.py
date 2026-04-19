"""Tests for config module."""

from services.pipeline_worker.src.config import Settings


class TestSettings:
    def test_default_values(self):
        s = Settings()
        assert s.REDIS_URL == "redis://localhost:6379"
        assert s.PIPELINE_WORKER_PORT == 8055
        assert s.MAX_WORKERS == 50
        assert s.HEARTBEAT_INTERVAL_SEC == 30
        assert s.INFERENCE_SERVICE_URL == "http://localhost:8045"
        assert s.BROKER_GATEWAY_URL == "http://localhost:8030"
        assert s.FEATURE_PIPELINE_URL == "http://localhost:8050"
        assert s.API_BASE_URL == "http://localhost:8011"
