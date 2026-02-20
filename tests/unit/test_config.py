


class TestAppConfig:
    def test_config_loads_defaults(self):
        from shared.config.base_config import AppConfig

        cfg = AppConfig()
        assert cfg.kafka.bootstrap_servers
        assert cfg.database.url
        assert cfg.redis.url
        assert cfg.log_level == "INFO"

    def test_kafka_config_defaults(self):
        from shared.config.base_config import KafkaConfig

        kafka = KafkaConfig()
        assert kafka.auto_offset_reset == "earliest"
        assert kafka.consumer_group == "default-group"

    def test_risk_config_defaults(self):
        from shared.config.base_config import RiskConfig

        risk = RiskConfig()
        assert risk.max_position_size == 10
        assert risk.max_total_contracts == 100
        assert risk.enable_trading is True
        assert risk.dry_run_mode is False

    def test_execution_config_defaults(self):
        from shared.config.base_config import ExecutionConfig

        exe = ExecutionConfig()
        assert exe.buffer_percentage == 0.15
        assert exe.default_profit_target == 0.30
        assert exe.default_stop_loss == 0.20

    def test_gateway_config_defaults(self):
        from shared.config.base_config import GatewayConfig

        gw = GatewayConfig()
        assert gw.approval_mode == "auto"
        assert gw.approval_timeout_seconds == 300

    def test_auth_config_defaults(self):
        from shared.config.base_config import AuthConfig

        auth = AuthConfig()
        assert auth.algorithm == "HS256"
        assert auth.access_token_expire_minutes == 30

    def test_config_singleton(self):
        from shared.config.base_config import config

        assert config is not None
        assert config.kafka is not None
        assert config.database is not None
