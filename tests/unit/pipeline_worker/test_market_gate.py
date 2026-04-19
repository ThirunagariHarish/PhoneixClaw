"""Tests for market gate."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from services.pipeline_worker.src.pipeline.market_gate import MarketStatus, check_market_hours

ET = ZoneInfo("America/New_York")


class TestCheckMarketHours:
    @patch("services.pipeline_worker.src.pipeline.market_gate.get_market_status")
    @patch("services.pipeline_worker.src.pipeline.market_gate.is_market_open")
    @patch("services.pipeline_worker.src.pipeline.market_gate.next_market_open")
    @patch("services.pipeline_worker.src.pipeline.market_gate.next_market_close")
    def test_regular_hours(self, mock_close, mock_open, mock_is_open, mock_status):
        mock_status.return_value = {"session": "regular"}
        mock_is_open.return_value = True
        mock_open.return_value = datetime(2026, 4, 13, 9, 30, tzinfo=ET)
        mock_close.return_value = datetime(2026, 4, 13, 16, 0, tzinfo=ET)

        result = check_market_hours()
        assert result.is_open is True
        assert result.session_type == "regular"
        assert result.closes_at is not None

    @patch("services.pipeline_worker.src.pipeline.market_gate.get_market_status")
    @patch("services.pipeline_worker.src.pipeline.market_gate.is_market_open")
    @patch("services.pipeline_worker.src.pipeline.market_gate.next_market_open")
    @patch("services.pipeline_worker.src.pipeline.market_gate.next_market_close")
    def test_closed_hours(self, mock_close, mock_open, mock_is_open, mock_status):
        mock_status.return_value = {"session": "closed"}
        mock_is_open.return_value = False
        mock_open.return_value = datetime(2026, 4, 14, 9, 30, tzinfo=ET)
        mock_close.return_value = None

        result = check_market_hours()
        assert result.is_open is False
        assert result.session_type == "closed"
        assert result.closes_at is None

    def test_market_status_dataclass(self):
        status = MarketStatus(is_open=True, session_type="regular")
        assert status.opens_at is None
        assert status.closes_at is None
