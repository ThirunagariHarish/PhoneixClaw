from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class ExitSignal:
    def __init__(self, position_id: int, reason: str, trigger_price: float):
        self.position_id = position_id
        self.reason = reason
        self.trigger_price = trigger_price


class ExitEngine:
    """Evaluates exit conditions for positions."""

    def check_profit_target(self, entry_price: float, current_price: float, target_pct: float) -> bool:
        if entry_price <= 0:
            return False
        pnl_pct = (current_price - entry_price) / entry_price
        return pnl_pct >= target_pct

    def check_stop_loss(self, entry_price: float, current_price: float, stop_pct: float) -> bool:
        if entry_price <= 0:
            return False
        loss_pct = (entry_price - current_price) / entry_price
        return loss_pct >= stop_pct

    def check_trailing_stop(self, high_water_mark: float, current_price: float, offset_pct: float) -> bool:
        if high_water_mark <= 0:
            return False
        drop_pct = (high_water_mark - current_price) / high_water_mark
        return drop_pct >= offset_pct

    def update_high_water_mark(self, current_hwm: float | None, current_price: float) -> float:
        if current_hwm is None or current_price > current_hwm:
            return current_price
        return current_hwm

    def evaluate_position(self, position: dict, current_price: float) -> ExitSignal | None:
        entry = float(position.get("avg_entry_price", 0))
        profit_target = float(position.get("profit_target", 0.30))
        stop_loss = float(position.get("stop_loss", 0.20))
        hwm = float(position.get("high_water_mark") or entry)
        trailing_enabled = position.get("trailing_stop_enabled", False)
        trailing_offset = float(position.get("trailing_stop_offset", 0.10))
        pos_id = position.get("id", 0)

        if self.check_profit_target(entry, current_price, profit_target):
            return ExitSignal(pos_id, "TAKE_PROFIT", current_price)

        if self.check_stop_loss(entry, current_price, stop_loss):
            return ExitSignal(pos_id, "STOP_LOSS", current_price)

        if trailing_enabled and self.check_trailing_stop(hwm, current_price, trailing_offset):
            return ExitSignal(pos_id, "TRAILING_STOP", current_price)

        return None
