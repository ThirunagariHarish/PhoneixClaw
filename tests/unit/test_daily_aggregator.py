from services.position_monitor.src.daily_aggregator import DailyAggregator


class TestDailyAggregator:
    def test_aggregator_instantiation(self):
        agg = DailyAggregator()
        assert agg is not None
