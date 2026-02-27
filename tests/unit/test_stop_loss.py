import pytest
from services.position_monitor.src.exit_engine import ExitEngine


@pytest.fixture
def engine():
    return ExitEngine()


class TestStopLoss:
    def test_stop_loss_triggered(self, engine):
        assert engine.check_stop_loss(10.0, 8.0, 0.20) is True

    def test_stop_loss_not_triggered(self, engine):
        assert engine.check_stop_loss(10.0, 9.0, 0.20) is False

    def test_zero_entry(self, engine):
        assert engine.check_stop_loss(0.0, 5.0, 0.20) is False
