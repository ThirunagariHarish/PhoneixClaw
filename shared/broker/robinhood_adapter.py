"""Robinhood broker adapter wrapping MCP server as async HTTP client.

Implements BrokerAdapter protocol by wrapping the shared Robinhood MCP server
deployed at robinhood-mcp-server:8080. All methods POST to the MCP HTTP endpoints.

Symbols are converted:
- Input (from pipeline): OCC format (e.g., "SPY260616C00600000")
- Output (to Robinhood): Human-readable (e.g., "SPY 6/16/26 600C")
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class BrokerAPIError(Exception):
    """Raised when Robinhood MCP server returns an error."""


class RobinhoodBrokerAdapter:
    """BrokerAdapter for Robinhood via shared MCP HTTP server."""

    def __init__(
        self,
        mcp_url: str = "http://robinhood-mcp-server:8080",
        timeout: float = 30.0,
    ) -> None:
        self.mcp_url = mcp_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        logger.info("Robinhood broker adapter initialized (mcp_url=%s)", self.mcp_url)

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init async HTTP client with connection pooling."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _post(self, endpoint: str, payload: dict) -> dict:
        """POST to MCP server and handle errors."""
        client = await self._get_client()
        url = f"{self.mcp_url}{endpoint}"
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text[:500]
            logger.error("Robinhood MCP error %d: %s", exc.response.status_code, error_detail)
            raise BrokerAPIError(f"MCP server error {exc.response.status_code}: {error_detail}") from exc
        except httpx.RequestError as exc:
            logger.error("Robinhood MCP request failed: %s", exc)
            raise BrokerAPIError(f"MCP server unreachable: {exc}") from exc

    async def place_limit_order(self, symbol: str, qty: int, side: str, price: float) -> str:
        """Place a limit order. Returns broker order ID."""
        rh_symbol = self._occ_to_robinhood(symbol)
        payload = {
            "symbol": rh_symbol,
            "quantity": qty,
            "side": side.lower(),
            "order_type": "limit",
            "price": price,
        }
        resp = await self._post("/place_order", payload)
        return resp.get("order_id", "")

    async def place_bracket_order(
        self, symbol: str, qty: int, side: str, price: float, take_profit: float, stop_loss: float
    ) -> str:
        """Place a bracket order with take-profit and stop-loss legs."""
        rh_symbol = self._occ_to_robinhood(symbol)
        payload = {
            "symbol": rh_symbol,
            "quantity": qty,
            "side": side.lower(),
            "order_type": "limit",
            "price": price,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
        }
        resp = await self._post("/place_bracket_order", payload)
        return resp.get("order_id", "")

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""
        resp = await self._post("/cancel_order", {"order_id": order_id})
        return resp.get("success", False)

    async def get_order_status(self, order_id: str) -> dict:
        """Get order status. Returns {status, filled_qty, fill_price}."""
        resp = await self._post("/get_order_status", {"order_id": order_id})
        return {
            "status": resp.get("status", "unknown"),
            "filled_qty": resp.get("filled_quantity", 0),
            "fill_price": resp.get("fill_price"),
        }

    async def get_positions(self) -> list[dict]:
        """Get all open positions from the broker."""
        resp = await self._post("/get_positions", {})
        positions = resp.get("positions", [])
        # Convert to standard format
        return [
            {
                "symbol": self._robinhood_to_occ(p.get("symbol", "")),
                "quantity": p.get("quantity", 0),
                "avg_cost": p.get("avg_cost"),
                "current_price": p.get("current_price"),
                "pnl": p.get("pnl"),
            }
            for p in positions
        ]

    async def get_orders(self, status: str = "open") -> list[dict]:
        """Get orders from the broker. status: open, closed, all."""
        resp = await self._post("/get_orders", {"status": status})
        orders = resp.get("orders", [])
        return [
            {
                "order_id": o.get("order_id"),
                "symbol": self._robinhood_to_occ(o.get("symbol", "")),
                "side": o.get("side"),
                "quantity": o.get("quantity"),
                "price": o.get("price"),
                "status": o.get("status"),
            }
            for o in orders
        ]

    async def close_position(self, symbol: str) -> bool:
        """Close (liquidate) an open position by symbol. Returns True if closed."""
        rh_symbol = self._occ_to_robinhood(symbol)
        resp = await self._post("/close_position", {"symbol": rh_symbol})
        return resp.get("success", False)

    async def get_quote(self, symbol: str) -> dict:
        """Get current quote. Returns {bid, ask, last, timestamp}."""
        rh_symbol = self._occ_to_robinhood(symbol)
        resp = await self._post("/get_quote", {"symbol": rh_symbol})
        return {
            "bid": resp.get("bid"),
            "ask": resp.get("ask"),
            "last": resp.get("last") or resp.get("price"),
            "timestamp": resp.get("timestamp"),
        }

    async def get_account(self) -> dict:
        """Get account summary. Returns {buying_power, cash, equity, portfolio_value}."""
        resp = await self._post("/get_account", {})
        return {
            "buying_power": resp.get("buying_power", 0.0),
            "cash": resp.get("cash", 0.0),
            "equity": resp.get("equity", 0.0),
            "portfolio_value": resp.get("portfolio_value", 0.0),
        }

    def format_option_symbol(self, ticker: str, expiration: str, option_type: str, strike: float) -> str:
        """Format option symbol in Robinhood-friendly format.

        Returns human-readable format: "SPY 6/16/26 600C"
        """
        # Parse expiration (assume YYYY-MM-DD)
        try:
            exp_date = datetime.strptime(expiration, "%Y-%m-%d")
            exp_str = exp_date.strftime("%-m/%-d/%y")  # "6/16/26"
        except ValueError:
            exp_str = expiration

        opt_char = "C" if option_type.upper() in ("C", "CALL") else "P"
        strike_int = int(strike) if strike == int(strike) else strike
        return f"{ticker} {exp_str} {strike_int}{opt_char}"

    def _occ_to_robinhood(self, symbol: str) -> str:
        """Convert OCC symbol to Robinhood human-readable format.

        Examples:
            SPY260616C00600000 -> SPY 6/16/26 600C
            AAPL -> AAPL (stock, unchanged)
        """
        # OCC pattern: TICKER(1-6 chars) + YYMMDD + C/P + STRIKE(8 digits)
        m = re.match(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$", symbol.upper())
        if not m:
            # Not an option OCC symbol, return as-is (stock)
            return symbol

        root, yymmdd, cp, strike_str = m.groups()
        yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
        year = 2000 + yy if yy < 50 else 1900 + yy

        strike = int(strike_str) / 1000.0
        strike_int = int(strike) if strike == int(strike) else strike

        # Format: "SPY 6/16/26 600C"
        exp_str = f"{mm}/{dd}/{yy}"
        return f"{root} {exp_str} {strike_int}{cp}"

    def _robinhood_to_occ(self, symbol: str) -> str:
        """Convert Robinhood human-readable format back to OCC.

        Examples:
            SPY 6/16/26 600C -> SPY260616C00600000
            AAPL -> AAPL (stock, unchanged)
        """
        # Pattern: TICKER M/D/YY STRIKE{C|P}
        m = re.match(r"^([A-Z]+)\s+(\d{1,2})/(\d{1,2})/(\d{2})\s+([\d.]+)([CP])$", symbol.strip())
        if not m:
            return symbol  # Stock or already OCC

        root, mm, dd, yy, strike_str, cp = m.groups()
        strike = float(strike_str)
        strike_padded = f"{int(strike * 1000):08d}"

        return f"{root}{yy}{mm:02d}{dd:02d}{cp}{strike_padded}"
