from shared.retention import DEFAULT_RETENTION_DAYS


class TestRetentionConfig:
    def test_default_retention_days(self):
        assert "trade_events" in DEFAULT_RETENTION_DAYS
        assert "notification_log" in DEFAULT_RETENTION_DAYS
        assert "raw_messages" in DEFAULT_RETENTION_DAYS

    def test_retention_values_positive(self):
        for table, days in DEFAULT_RETENTION_DAYS.items():
            assert days > 0, f"{table} retention must be > 0"

    def test_trade_events_retention(self):
        assert DEFAULT_RETENTION_DAYS["trade_events"] == 90

    def test_notification_retention(self):
        assert DEFAULT_RETENTION_DAYS["notification_log"] == 60

    def test_raw_messages_retention(self):
        assert DEFAULT_RETENTION_DAYS["raw_messages"] == 30
