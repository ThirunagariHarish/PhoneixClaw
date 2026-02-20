

from shared.models.trade import (
    AccountSourceMapping,
    Base,
    Channel,
    Configuration,
    DailyMetrics,
    DataSource,
    NotificationLog,
    Position,
    Trade,
    TradeEvent,
    TradingAccount,
    User,
)


class TestUserModel:
    def test_user_has_required_columns(self):
        assert hasattr(User, "id")
        assert hasattr(User, "email")
        assert hasattr(User, "password_hash")
        assert hasattr(User, "is_active")

    def test_user_tablename(self):
        assert User.__tablename__ == "users"


class TestTradingAccountModel:
    def test_has_user_id(self):
        assert hasattr(TradingAccount, "user_id")
        assert hasattr(TradingAccount, "broker_type")
        assert hasattr(TradingAccount, "credentials_encrypted")
        assert hasattr(TradingAccount, "paper_mode")

    def test_tablename(self):
        assert TradingAccount.__tablename__ == "trading_accounts"


class TestDataSourceModel:
    def test_has_required_fields(self):
        assert hasattr(DataSource, "user_id")
        assert hasattr(DataSource, "source_type")
        assert hasattr(DataSource, "credentials_encrypted")
        assert hasattr(DataSource, "connection_status")

    def test_tablename(self):
        assert DataSource.__tablename__ == "data_sources"


class TestChannelModel:
    def test_has_required_fields(self):
        assert hasattr(Channel, "data_source_id")
        assert hasattr(Channel, "channel_identifier")
        assert hasattr(Channel, "enabled")

    def test_tablename(self):
        assert Channel.__tablename__ == "channels"


class TestAccountSourceMappingModel:
    def test_has_required_fields(self):
        assert hasattr(AccountSourceMapping, "trading_account_id")
        assert hasattr(AccountSourceMapping, "channel_id")
        assert hasattr(AccountSourceMapping, "config_overrides")
        assert hasattr(AccountSourceMapping, "enabled")


class TestTradeModel:
    def test_has_multi_tenant_fields(self):
        assert hasattr(Trade, "user_id")
        assert hasattr(Trade, "trading_account_id")
        assert hasattr(Trade, "channel_id")

    def test_has_execution_fields(self):
        assert hasattr(Trade, "buffered_price")
        assert hasattr(Trade, "fill_price")
        assert hasattr(Trade, "broker_order_id")
        assert hasattr(Trade, "execution_latency_ms")

    def test_tablename(self):
        assert Trade.__tablename__ == "trades"


class TestPositionModel:
    def test_has_multi_tenant_fields(self):
        assert hasattr(Position, "user_id")
        assert hasattr(Position, "trading_account_id")
        assert hasattr(Position, "high_water_mark")

    def test_has_exit_fields(self):
        assert hasattr(Position, "profit_target")
        assert hasattr(Position, "stop_loss")
        assert hasattr(Position, "close_reason")
        assert hasattr(Position, "realized_pnl")


class TestTradeEventModel:
    def test_has_audit_fields(self):
        assert hasattr(TradeEvent, "user_id")
        assert hasattr(TradeEvent, "trade_id")
        assert hasattr(TradeEvent, "event_type")
        assert hasattr(TradeEvent, "source_service")


class TestDailyMetricsModel:
    def test_has_metric_fields(self):
        assert hasattr(DailyMetrics, "total_pnl")
        assert hasattr(DailyMetrics, "winning_trades")
        assert hasattr(DailyMetrics, "max_drawdown")


class TestAllModelsHaveBase:
    def test_all_inherit_from_base(self):
        models = [
            User, TradingAccount, DataSource, Channel,
            AccountSourceMapping, Trade, Position, TradeEvent,
            DailyMetrics, Configuration, NotificationLog,
        ]
        for model in models:
            assert issubclass(model, Base), f"{model.__name__} does not inherit from Base"
