from typing import Protocol, runtime_checkable


@runtime_checkable
class BrokerAdapter(Protocol):
    async def place_limit_order(self, symbol: str, qty: int, side: str, price: float) -> str:
        """Place a limit order. Returns broker order ID."""
        ...

    async def place_bracket_order(
        self, symbol: str, qty: int, side: str, price: float, take_profit: float, stop_loss: float
    ) -> str:
        """Place a bracket order with take-profit and stop-loss legs."""
        ...

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""
        ...

    async def get_order_status(self, order_id: str) -> dict:
        """Get order status. Returns {status, filled_qty, fill_price}."""
        ...

    async def get_positions(self) -> list[dict]:
        """Get all open positions from the broker."""
        ...

    async def close_position(self, symbol: str) -> bool:
        """Close (liquidate) an open position by symbol. Returns True if closed."""
        ...

    async def get_quote(self, symbol: str) -> dict:
        """Get current quote. Returns {bid, ask, last, timestamp}."""
        ...

    async def get_account(self) -> dict:
        """Get account summary. Returns {buying_power, cash, equity, portfolio_value}."""
        ...

    def format_option_symbol(self, ticker: str, expiration: str, option_type: str, strike: float) -> str:
        """Format option symbol in broker-specific format (e.g., OCC)."""
        ...
