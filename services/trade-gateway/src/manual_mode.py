import logging
from datetime import datetime, timezone

from shared.config.base_config import config

logger = logging.getLogger(__name__)


class ManualApprovalManager:
    def __init__(self):
        self._pending: dict[str, dict] = {}
        self.timeout_seconds = config.gateway.approval_timeout_seconds

    def add_pending(self, trade_id: str, trade: dict) -> None:
        trade["status"] = "PENDING"
        trade["pending_since"] = datetime.now(timezone.utc).isoformat()
        self._pending[trade_id] = trade
        logger.info("Trade %s added to pending queue", trade_id)

    def approve(self, trade_id: str, approved_by: str = "manual") -> dict | None:
        trade = self._pending.pop(trade_id, None)
        if trade:
            trade["status"] = "IN_PROGRESS"
            trade["approved_by"] = approved_by
            trade["approved_at"] = datetime.now(timezone.utc).isoformat()
            logger.info("Trade %s approved by %s", trade_id, approved_by)
        return trade

    def reject(self, trade_id: str, reason: str = "") -> dict | None:
        trade = self._pending.pop(trade_id, None)
        if trade:
            trade["status"] = "REJECTED"
            trade["rejection_reason"] = reason or "Manually rejected"
            logger.info("Trade %s rejected: %s", trade_id, reason)
        return trade

    def approve_all(self, approved_by: str = "manual") -> list[dict]:
        approved = []
        for tid in list(self._pending.keys()):
            trade = self.approve(tid, approved_by)
            if trade:
                approved.append(trade)
        return approved

    def get_pending(self) -> list[dict]:
        return list(self._pending.values())

    def check_timeouts(self) -> list[dict]:
        timed_out = []
        now = datetime.now(timezone.utc)
        for tid in list(self._pending.keys()):
            trade = self._pending[tid]
            pending_since = datetime.fromisoformat(trade["pending_since"])
            elapsed = (now - pending_since).total_seconds()
            if elapsed > self.timeout_seconds:
                trade = self.reject(tid, f"Timed out after {self.timeout_seconds}s")
                if trade:
                    timed_out.append(trade)
        return timed_out

    @property
    def pending_count(self) -> int:
        return len(self._pending)
