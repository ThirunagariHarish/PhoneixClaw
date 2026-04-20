"""
Alpaca broker connector — paper and live trading via Alpaca API.

M1.9: Primary broker integration.
Reference: PRD Section 10, existing v1 shared/broker/alpaca_adapter.py.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class AccountMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class BrokerOrder(BaseModel):
    """Normalized order object for broker abstraction."""
    symbol: str
    side: OrderSide
    qty: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "day"


class BrokerPosition(BaseModel):
    """Normalized position from broker."""
    symbol: str
    qty: float
    side: str
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    market_value: float


class AlpacaBroker:
    """
    Alpaca broker adapter implementing the broker abstraction interface.
    Supports both paper and live trading modes.
    """

    def __init__(self, config: dict[str, Any]):
        self.api_key: str = config.get("api_key", "")
        self.api_secret: str = config.get("api_secret", "")
        self.mode: AccountMode = AccountMode(config.get("mode", "paper"))
        self.base_url = (
            "https://paper-api.alpaca.markets"
            if self.mode == AccountMode.PAPER
            else "https://api.alpaca.markets"
        )
        self._connected = False

    async def connect(self) -> None:
        """Validate credentials and establish connection."""
        if not self.api_key or not self.api_secret:
            raise ValueError("Alpaca API key and secret are required")
        # In production: validate with GET /v2/account
        self._connected = True

    async def disconnect(self) -> None:
        """Close broker connection."""
        self._connected = False

    async def get_account(self) -> dict[str, Any]:
        """Fetch account info (balance, buying power, etc.)."""
        # Placeholder: in production, calls GET /v2/account
        return {
            "status": "ACTIVE",
            "buying_power": "100000.00",
            "portfolio_value": "100000.00",
            "currency": "USD",
            "mode": self.mode.value,
        }

    async def submit_order(self, order: BrokerOrder) -> dict[str, Any]:
        """Submit an order to Alpaca."""
        if not self._connected:
            raise RuntimeError("Broker not connected")

        # Placeholder: in production, calls POST /v2/orders
        return {
            "id": f"order-{datetime.now().timestamp()}",
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": order.qty,
            "type": order.order_type.value,
            "status": "accepted",
            "submitted_at": datetime.now().isoformat(),
        }

    async def get_positions(self) -> list[BrokerPosition]:
        """Fetch all open positions."""
        # Placeholder: in production, calls GET /v2/positions
        return []

    async def close_position(self, symbol: str) -> dict[str, Any]:
        """Close a position by symbol."""
        # Placeholder: in production, calls DELETE /v2/positions/{symbol}
        return {"symbol": symbol, "status": "closed"}

    async def health_check(self) -> dict[str, Any]:
        """Check Alpaca API connectivity."""
        return {
            "reachable": self._connected,
            "mode": self.mode.value,
            "base_url": self.base_url,
        }
