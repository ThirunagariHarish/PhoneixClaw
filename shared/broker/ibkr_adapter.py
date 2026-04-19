"""Interactive Brokers broker adapter using ib_insync.

Implements BrokerAdapter protocol via TWS API / IB Gateway connection.
Uses circuit breaker for connection failures with exponential backoff reconnect.

Deployment:
- Local dev: TWS or IB Gateway on 127.0.0.1:7497 (paper) / 7496 (live)
- Production: Docker ghcr.io/gnzsnz/ib-gateway on ib-gateway:4001
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

from ib_insync import IB, Contract, LimitOrder, Option, Stock

from shared.broker.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)


class BrokerAPIError(Exception):
    """Raised when IBKR API returns an error."""


class IBKRBrokerAdapter:
    """BrokerAdapter for Interactive Brokers via ib_insync."""

    def __init__(
        self,
        host: str = "ib-gateway",
        port: int = 4001,
        client_id: int = 1,
        account_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account_id = account_id
        self.timeout = timeout

        self._ib: Optional[IB] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_delay = 30.0

        # Circuit breaker: 3 failures -> OPEN for 30s -> HALF_OPEN probe
        self._circuit = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30.0,
            half_open_max_calls=1,
        )

        logger.info(
            "IBKR broker adapter initialized (host=%s, port=%d, account=%s)",
            self.host,
            self.port,
            self.account_id or "default",
        )

    async def _ensure_connected(self) -> IB:
        """Ensure connection to IB Gateway, reconnect with exponential backoff if needed."""
        if self._ib and self._ib.isConnected():
            self._connected = True
            return self._ib

        if self._ib is None:
            self._ib = IB()
            # Subscribe to disconnectedEvent for reconnect handling
            self._ib.disconnectedEvent += self._on_disconnected

        delay = min(2 ** self._reconnect_attempts, self._max_reconnect_delay)
        if self._reconnect_attempts > 0:
            logger.info("Reconnecting to IBKR after %ds delay (attempt %d)", delay, self._reconnect_attempts)
            await asyncio.sleep(delay)

        try:
            await self._ib.connectAsync(self.host, self.port, clientId=self.client_id, timeout=self.timeout)
            self._connected = True
            self._reconnect_attempts = 0
            logger.info("Connected to IBKR successfully")
            return self._ib
        except Exception as exc:
            self._reconnect_attempts += 1
            logger.error("IBKR connection failed (attempt %d): %s", self._reconnect_attempts, exc)
            raise BrokerAPIError(f"Failed to connect to IBKR: {exc}") from exc

    def _on_disconnected(self):
        """Handle disconnection event from ib_insync."""
        self._connected = False
        logger.warning("IBKR disconnected, will attempt reconnect on next call")

    async def disconnect(self) -> None:
        """Disconnect from IB Gateway."""
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
            self._connected = False
            logger.info("Disconnected from IBKR")

    async def _call_with_circuit(self, func, *args, **kwargs):
        """Execute a broker call with circuit breaker protection."""
        try:
            return await self._circuit.call(func, *args, **kwargs)
        except CircuitOpenError:
            logger.error("Circuit breaker OPEN, rejecting IBKR call")
            raise BrokerAPIError("IBKR circuit breaker is OPEN") from None

    async def place_limit_order(self, symbol: str, qty: int, side: str, price: float) -> str:
        """Place a limit order. Returns broker order ID."""

        async def _place():
            ib = await self._ensure_connected()
            contract = self._parse_symbol(symbol)
            action = "BUY" if side.upper() == "BUY" else "SELL"
            order = LimitOrder(action, qty, price)
            trade = ib.placeOrder(contract, order)
            await asyncio.sleep(0.5)  # Wait for order ID assignment
            return str(trade.order.orderId) if trade.order.orderId else ""

        return await self._call_with_circuit(_place)

    async def place_bracket_order(
        self, symbol: str, qty: int, side: str, price: float, take_profit: float, stop_loss: float
    ) -> str:
        """Place a bracket order with take-profit and stop-loss legs."""

        async def _place():
            ib = await self._ensure_connected()
            contract = self._parse_symbol(symbol)
            action = "BUY" if side.upper() == "BUY" else "SELL"

            # IBKR bracket: parent limit + TP limit + SL stop
            parent = LimitOrder(action, qty, price)
            parent.transmit = False

            take_profit_action = "SELL" if action == "BUY" else "BUY"
            tp_order = LimitOrder(take_profit_action, qty, take_profit)
            tp_order.parentId = parent.orderId
            tp_order.transmit = False

            sl_order = LimitOrder(take_profit_action, qty, stop_loss)
            sl_order.parentId = parent.orderId
            sl_order.transmit = True  # Transmit last order submits all

            parent_trade = ib.placeOrder(contract, parent)
            ib.placeOrder(contract, tp_order)
            ib.placeOrder(contract, sl_order)

            await asyncio.sleep(0.5)
            return str(parent_trade.order.orderId) if parent_trade.order.orderId else ""

        return await self._call_with_circuit(_place)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""

        async def _cancel():
            ib = await self._ensure_connected()
            try:
                ib.cancelOrder(int(order_id))
                await asyncio.sleep(0.5)
                return True
            except Exception as exc:
                logger.error("Failed to cancel order %s: %s", order_id, exc)
                return False

        return await self._call_with_circuit(_cancel)

    async def get_order_status(self, order_id: str) -> dict:
        """Get order status. Returns {status, filled_qty, fill_price}."""

        async def _status():
            ib = await self._ensure_connected()
            trades = ib.trades()
            for trade in trades:
                if str(trade.order.orderId) == order_id:
                    return {
                        "status": trade.orderStatus.status,
                        "filled_qty": trade.orderStatus.filled,
                        "fill_price": trade.orderStatus.avgFillPrice if trade.orderStatus.avgFillPrice > 0 else None,
                    }
            return {"status": "unknown", "filled_qty": 0, "fill_price": None}

        return await self._call_with_circuit(_status)

    async def get_positions(self) -> list[dict]:
        """Get all open positions from the broker."""

        async def _positions():
            ib = await self._ensure_connected()
            positions = ib.positions(account=self.account_id) if self.account_id else ib.positions()
            return [
                {
                    "symbol": self._contract_to_occ(p.contract),
                    "quantity": int(p.position),
                    "avg_cost": p.avgCost,
                    "current_price": None,  # Requires separate market data subscription
                    "pnl": None,
                }
                for p in positions
            ]

        return await self._call_with_circuit(_positions)

    async def get_orders(self, status: str = "open") -> list[dict]:
        """Get orders from the broker. status: open, closed, all."""

        async def _orders():
            ib = await self._ensure_connected()
            all_trades = ib.openTrades() if status == "open" else ib.trades()
            return [
                {
                    "order_id": str(t.order.orderId),
                    "symbol": self._contract_to_occ(t.contract),
                    "side": t.order.action,
                    "quantity": int(t.order.totalQuantity),
                    "price": t.order.lmtPrice if hasattr(t.order, "lmtPrice") else None,
                    "status": t.orderStatus.status,
                }
                for t in all_trades
            ]

        return await self._call_with_circuit(_orders)

    async def close_position(self, symbol: str) -> bool:
        """Close (liquidate) an open position by symbol. Returns True if closed."""

        async def _close():
            ib = await self._ensure_connected()
            positions = ib.positions(account=self.account_id) if self.account_id else ib.positions()
            for pos in positions:
                if self._contract_to_occ(pos.contract) == symbol:
                    contract = pos.contract
                    qty = abs(int(pos.position))
                    action = "SELL" if pos.position > 0 else "BUY"
                    order = LimitOrder(action, qty, 0)  # Market-on-close approximation
                    ib.placeOrder(contract, order)
                    await asyncio.sleep(0.5)
                    return True
            return False

        return await self._call_with_circuit(_close)

    async def get_quote(self, symbol: str) -> dict:
        """Get current quote. Returns {bid, ask, last, timestamp}."""

        async def _quote():
            ib = await self._ensure_connected()
            contract = self._parse_symbol(symbol)
            ticker = ib.reqTickers(contract)[0] if ib.reqTickers(contract) else None
            if not ticker:
                raise BrokerAPIError(f"No quote data for {symbol}")

            return {
                "bid": ticker.bid if ticker.bid > 0 else None,
                "ask": ticker.ask if ticker.ask > 0 else None,
                "last": ticker.last if ticker.last > 0 else None,
                "timestamp": datetime.now().isoformat(),
            }

        return await self._call_with_circuit(_quote)

    async def get_account(self) -> dict:
        """Get account summary. Returns {buying_power, cash, equity, portfolio_value}."""

        async def _account():
            ib = await self._ensure_connected()
            account_values = ib.accountSummary(account=self.account_id) if self.account_id else ib.accountSummary()

            data = {}
            for item in account_values:
                if item.tag == "BuyingPower":
                    data["buying_power"] = float(item.value)
                elif item.tag == "TotalCashValue":
                    data["cash"] = float(item.value)
                elif item.tag == "NetLiquidation":
                    data["equity"] = float(item.value)
                    data["portfolio_value"] = float(item.value)

            return {
                "buying_power": data.get("buying_power", 0.0),
                "cash": data.get("cash", 0.0),
                "equity": data.get("equity", 0.0),
                "portfolio_value": data.get("portfolio_value", 0.0),
            }

        return await self._call_with_circuit(_account)

    def format_option_symbol(self, ticker: str, expiration: str, option_type: str, strike: float) -> str:
        """Format option symbol in IBKR OCC format.

        Returns: SPY   260616C00600000 (6-char padded ticker + YYMMDD + C/P + 8-digit strike)
        """
        # Pad ticker to 6 characters
        ticker_padded = ticker.ljust(6)

        # Parse expiration YYYY-MM-DD -> YYMMDD
        try:
            exp_date = datetime.strptime(expiration, "%Y-%m-%d")
            yymmdd = exp_date.strftime("%y%m%d")
        except ValueError:
            yymmdd = expiration[-6:]  # Fallback

        opt_char = "C" if option_type.upper() in ("C", "CALL") else "P"
        strike_padded = f"{int(strike * 1000):08d}"

        return f"{ticker_padded}{yymmdd}{opt_char}{strike_padded}"

    def _parse_symbol(self, symbol: str) -> Contract:
        """Parse OCC symbol to ib_insync Contract (Stock or Option)."""
        # OCC pattern: TICKER(1-6) + YYMMDD + C/P + STRIKE(8)
        m = re.match(r"^([A-Z\s]{1,6})(\d{6})([CP])(\d{8})$", symbol.upper())
        if not m:
            # Stock symbol
            return Stock(symbol.strip(), "SMART", "USD")

        root, yymmdd, cp, strike_str = m.groups()
        root = root.strip()

        yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
        year = 2000 + yy if yy < 50 else 1900 + yy
        exp_str = f"{year}{mm:02d}{dd:02d}"

        strike = int(strike_str) / 1000.0
        right = "C" if cp == "C" else "P"

        return Option(root, exp_str, strike, right, "SMART")

    def _contract_to_occ(self, contract: Contract) -> str:
        """Convert ib_insync Contract back to OCC symbol."""
        if isinstance(contract, Stock):
            return contract.symbol

        if isinstance(contract, Option):
            ticker_padded = contract.symbol.ljust(6)
            # contract.lastTradeDateOrContractMonth is YYYYMMDD
            exp_str = contract.lastTradeDateOrContractMonth
            yy = exp_str[2:4] if len(exp_str) >= 8 else "26"
            mm = exp_str[4:6] if len(exp_str) >= 8 else "01"
            dd = exp_str[6:8] if len(exp_str) >= 8 else "01"
            yymmdd = f"{yy}{mm}{dd}"

            cp = "C" if contract.right == "C" else "P"
            strike_padded = f"{int(contract.strike * 1000):08d}"
            return f"{ticker_padded}{yymmdd}{cp}{strike_padded}"

        return str(contract.symbol)
