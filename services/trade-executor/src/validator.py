import logging
from typing import Any

from shared.config.base_config import config

logger = logging.getLogger(__name__)


class TradeValidator:
    """Validates trades before execution."""

    def validate(self, trade: dict[str, Any], risk_config: dict | None = None) -> tuple[bool, str | None]:
        """
        Validate a trade before execution.
        Returns (is_valid, error_message).
        """
        rc = risk_config or {}
        enable_trading = rc.get("enable_trading", config.risk.enable_trading)
        if not enable_trading:
            return False, "Trading is disabled"

        ticker = trade.get("ticker", "").upper()
        blacklist = rc.get("ticker_blacklist", config.risk.ticker_blacklist)
        if ticker in [t.upper() for t in blacklist]:
            return False, f"Ticker {ticker} is blacklisted"

        required = ["ticker", "strike", "option_type", "action", "price"]
        for field in required:
            if not trade.get(field):
                return False, f"Missing required field: {field}"

        if not trade.get("expiration"):
            return False, "Expiration date is required for options"

        raw_qty = trade.get("quantity")
        quantity_str = str(raw_qty) if raw_qty is not None else "1"
        is_percentage = "%" in quantity_str

        if not is_percentage:
            try:
                quantity = int(quantity_str)
                if quantity <= 0:
                    return False, f"Invalid quantity: {quantity}"
                max_pos = rc.get("max_position_size", config.risk.max_position_size)
                if quantity > max_pos:
                    return False, f"Quantity {quantity} exceeds max position size {max_pos}"
            except ValueError:
                return False, f"Invalid quantity format: {quantity_str}"

        price = float(trade.get("price", 0))
        if price <= 0:
            return False, f"Invalid price: {price}"

        return True, None


trade_validator = TradeValidator()
