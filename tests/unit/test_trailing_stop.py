import pytest

from services.position_monitor.src.exit_engine import ExitEngine


@pytest.fixture
def engine():
    return ExitEngine()


class TestTrailingStop:
    def test_trailing_stop_triggered(self, engine):
        assert engine.check_trailing_stop(15.0, 13.0, 0.10) is True

    def test_trailing_stop_not_triggered(self, engine):
        assert engine.check_trailing_stop(15.0, 14.0, 0.10) is False

    def test_hwm_updated(self, engine):
        assert engine.update_high_water_mark(10.0, 12.0) == 12.0

    def test_hwm_not_lowered(self, engine):
        assert engine.update_high_water_mark(12.0, 10.0) == 12.0

    def test_hwm_from_none(self, engine):
        assert engine.update_high_water_mark(None, 5.0) == 5.0

    def test_zero_hwm(self, engine):
        assert engine.check_trailing_stop(0.0, 5.0, 0.10) is False
