import pytest

from services.position_monitor.src.exit_engine import ExitEngine


@pytest.fixture
def engine():
    return ExitEngine()


class TestProfitTarget:
    def test_profit_target_triggered(self, engine):
        assert engine.check_profit_target(10.0, 13.0, 0.30) is True

    def test_profit_target_not_triggered(self, engine):
        assert engine.check_profit_target(10.0, 12.0, 0.30) is False

    def test_exact_target(self, engine):
        assert engine.check_profit_target(10.0, 13.0, 0.30) is True

    def test_zero_entry_price(self, engine):
        assert engine.check_profit_target(0.0, 5.0, 0.30) is False
