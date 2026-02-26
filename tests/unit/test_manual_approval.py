import time

import pytest

from services.trade_gateway.src.manual_mode import ManualApprovalManager


@pytest.fixture
def manager():
    m = ManualApprovalManager()
    m.timeout_seconds = 1
    return m


class TestManualApproval:
    def test_add_pending(self, manager):
        manager.add_pending("t1", {"ticker": "SPX"})
        assert manager.pending_count == 1

    def test_approve(self, manager):
        manager.add_pending("t1", {"ticker": "SPX"})
        trade = manager.approve("t1", "admin")
        assert trade is not None
        assert trade["status"] == "IN_PROGRESS"
        assert trade["approved_by"] == "admin"
        assert manager.pending_count == 0

    def test_reject(self, manager):
        manager.add_pending("t1", {"ticker": "SPX"})
        trade = manager.reject("t1", "bad signal")
        assert trade["status"] == "REJECTED"
        assert "bad signal" in trade["rejection_reason"]

    def test_approve_all(self, manager):
        manager.add_pending("t1", {"ticker": "SPX"})
        manager.add_pending("t2", {"ticker": "AAPL"})
        approved = manager.approve_all("admin")
        assert len(approved) == 2
        assert manager.pending_count == 0

    def test_get_pending(self, manager):
        manager.add_pending("t1", {"ticker": "SPX"})
        pending = manager.get_pending()
        assert len(pending) == 1

    def test_approve_nonexistent(self, manager):
        result = manager.approve("nonexistent")
        assert result is None

    def test_timeout(self, manager):
        manager.timeout_seconds = 0  # immediate timeout
        manager.add_pending("t1", {"ticker": "SPX"})
        time.sleep(0.01)
        timed_out = manager.check_timeouts()
        assert len(timed_out) == 1
        assert timed_out[0]["status"] == "REJECTED"
