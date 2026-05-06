from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

import httpx
from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest

from shared.config.base_config import config

logger = logging.getLogger(__name__)

ALPACA_TRADE_BASE = "https://paper-api.alpaca.markets"
ALPACA_LIVE_BASE = "https://api.alpaca.markets"
ALPACA_DATA_BASE = "https://data.alpaca.markets"

_INDEX_SYMBOL_MAP: dict[str, str] = {
    "SPX": "SPXW",
    "NDX": "NDXP",
}

_OCC_REVERSE_MAP: dict[str, str] = {v: k for k, v in _INDEX_SYMBOL_MAP.items()}


def parse_occ_symbol(symbol: str) -> dict | None:
    """Parse OCC option symbol (e.g. SPY260224C00580000) to ticker, strike, option_type, expiration.
    Returns None for stocks or invalid format."""
    m = re.match(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$", symbol.upper())
    if not m:
        return None
    root, yymmdd, cp, strike_str = m.groups()
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    year = 2000 + yy if yy < 50 else 1900 + yy
    try:
        exp_date = datetime(year, mm, dd)
    except ValueError:
        return None
    ticker = _OCC_REVERSE_MAP.get(root, root)
    strike = int(strike_str) / 1000.0
    option_type = "CALL" if cp == "C" else "PUT"
    return {
        "ticker": ticker,
        "strike": strike,
        "option_type": option_type,
        "expiration": exp_date.strftime("%Y-%m-%d"),
    }


class AlpacaOrderError(Exception):
    """Raised when Alpaca rejects an order, carrying the human-readable detail."""


class AlpacaAuthError(AlpacaOrderError):
    """Raised specifically for 401/403 auth failures so callers can skip retries."""


class AlpacaBrokerAdapter:
    """BrokerAdapter implementation for Alpaca using the official alpaca-py SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        paper: bool | None = None,
    ) -> None:
        self._api_key = api_key or config.broker.api_key
        self._secret_key = secret_key or config.broker.secret_key
        self._paper = paper if paper is not None else config.broker.paper
        self._base_url = (
            "https://paper-api.alpaca.markets" if self._paper
            else "https://api.alpaca.markets"
        )
        self._mode_label = "PAPER" if self._paper else "LIVE"

        if not self._api_key or not self._secret_key:
            raise AlpacaAuthError("Alpaca API credentials not configured")

        self._client = TradingClient(
            api_key=self._api_key,
            secret_key=self._secret_key,
            paper=self._paper,
        )
        logger.info(
            "Alpaca broker adapter initialized (mode=%s, sdk=alpaca-py)",
            self._mode_label,
        )

    def _raise_with_detail(self, resp: httpx.Response, *, symbol: str = "") -> None:
        """Raise with HTTP response detail (used by get_quote and tests)."""
        if resp.status_code < 400:
            return
        detail = ""
        try:
            body = resp.json()
            detail = body.get("message") or body.get("detail") or str(body)
        except Exception:
            detail = resp.text[:500]
        prefix = f"[{symbol}] " if symbol else ""
        msg = f"{prefix}Alpaca {resp.status_code} ({self._mode_label} @ {self._base_url}): {detail}"
        logger.error("Alpaca order error: %s", msg)
        if resp.status_code in (401, 403):
            raise AlpacaAuthError(msg)
        raise AlpacaOrderError(msg)

    def _handle_api_error(self, e: APIError, *, symbol: str = "") -> None:
        """Convert Alpaca SDK APIError into our custom exceptions."""
        prefix = f"[{symbol}] " if symbol else ""
        status = getattr(e, "status_code", None) or 0
        msg = f"{prefix}Alpaca {status} ({self._mode_label}): {e}"
        logger.error("Alpaca API error: %s", msg)
        if status in (401, 403):
            raise AlpacaAuthError(msg) from e
        raise AlpacaOrderError(msg) from e

    def format_option_symbol(
        self, ticker: str, expiration: str, option_type: str, strike: float
    ) -> str:
        root = _INDEX_SYMBOL_MAP.get(ticker.upper(), ticker.upper())
        exp_date = datetime.strptime(expiration, "%Y-%m-%d")
        opt_char = "C" if option_type == "CALL" else "P"
        strike_str = f"{int(strike * 1000):08d}"
        symbol = f"{root}{exp_date.strftime('%y%m%d')}{opt_char}{strike_str}"
        if root != ticker.upper():
            logger.debug("Symbol mapped: %s -> %s (OCC: %s)", ticker, root, symbol)
        return symbol

    async def place_limit_order(
        self, symbol: str, qty: int, side: str, price: float
    ) -> str:
        order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        order_request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            limit_price=price,
            time_in_force=TimeInForce.DAY,
        )
        try:
            order = await asyncio.to_thread(
                self._client.submit_order, order_request
            )
            logger.info(
                "Order placed (%s): %s %d %s @ %.2f (ID: %s)",
                self._mode_label, side, qty, symbol, price, order.id,
            )
            return str(order.id)
        except APIError as e:
            self._handle_api_error(e, symbol=symbol)
            return ""  # unreachable, _handle_api_error always raises

    async def place_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        price: float,
        take_profit: float,
        stop_loss: float,
    ) -> str:
        order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        order_request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            limit_price=price,
            time_in_force=TimeInForce.DAY,
            order_class="bracket",
            take_profit={"limit_price": take_profit},
            stop_loss={"stop_price": stop_loss},
        )
        try:
            order = await asyncio.to_thread(
                self._client.submit_order, order_request
            )
            logger.info(
                "Bracket order placed (%s): %s %d %s @ %.2f (ID: %s)",
                self._mode_label, side, qty, symbol, price, order.id,
            )
            return str(order.id)
        except APIError as e:
            self._handle_api_error(e, symbol=symbol)
            return ""

    async def cancel_order(self, order_id: str) -> bool:
        try:
            await asyncio.to_thread(self._client.cancel_order_by_id, order_id)
            return True
        except APIError:
            return False

    async def get_order_status(self, order_id: str) -> dict:
        try:
            order = await asyncio.to_thread(
                self._client.get_order_by_id, order_id
            )
            return {
                "status": str(order.status.value) if order.status else "unknown",
                "filled_qty": int(order.filled_qty or 0),
                "fill_price": float(order.filled_avg_price or 0),
            }
        except APIError as e:
            self._handle_api_error(e, symbol=order_id)
            return {}

    async def get_orders(self, status: str = "open") -> list[dict]:
        status_map = {
            "open": QueryOrderStatus.OPEN,
            "closed": QueryOrderStatus.CLOSED,
            "all": QueryOrderStatus.ALL,
        }
        query_status = status_map.get(status, QueryOrderStatus.OPEN)
        try:
            orders = await asyncio.to_thread(
                self._client.get_orders,
                GetOrdersRequest(status=query_status, limit=100),
            )
            result = []
            for o in orders:
                sym = str(o.symbol)
                parsed = parse_occ_symbol(sym)
                entry = {
                    "order_id": str(o.id),
                    "symbol": sym,
                    "side": str(o.side.value) if o.side else "",
                    "qty": float(o.qty or 0),
                    "filled_qty": float(o.filled_qty or 0),
                    "order_type": str(o.type.value) if o.type else "",
                    "limit_price": float(o.limit_price) if o.limit_price else None,
                    "status": str(o.status.value) if o.status else "",
                    "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
                    "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                }
                if parsed:
                    entry.update(parsed)
                else:
                    entry["ticker"] = sym
                    entry["strike"] = 0.0
                    entry["option_type"] = ""
                    entry["expiration"] = None
                result.append(entry)
            return result
        except APIError as e:
            self._handle_api_error(e)
            return []

    async def get_positions(self) -> list[dict]:
        try:
            positions = await asyncio.to_thread(
                self._client.get_all_positions
            )
            return [
                {
                    "symbol": pos.symbol,
                    "qty": int(pos.qty),
                    "avg_entry_price": float(pos.avg_entry_price),
                    "market_value": float(pos.market_value),
                    "current_price": float(pos.current_price),
                    "unrealized_pl": float(pos.unrealized_pl),
                }
                for pos in positions
            ]
        except APIError as e:
            self._handle_api_error(e)
            return []

    async def close_position(self, symbol: str) -> bool:
        """Close (liquidate) an open position by symbol."""
        try:
            await asyncio.to_thread(
                self._client.close_position, symbol
            )
            logger.info("Position closed (%s): %s", self._mode_label, symbol)
            return True
        except APIError as e:
            self._handle_api_error(e, symbol=symbol)
            return False

    async def get_quote(self, symbol: str) -> dict:
        """Get latest quote. Uses httpx for the data API (not covered by trading SDK)."""
        async with httpx.AsyncClient(
            base_url=ALPACA_DATA_BASE,
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
            },
            timeout=5.0,
        ) as client:
            resp = await client.get(f"/v2/stocks/{symbol}/quotes/latest")
            resp.raise_for_status()
            q = resp.json()["quote"]
            return {
                "bid": float(q["bp"]),
                "ask": float(q["ap"]),
                "last": float(q["ap"]),
            }

    async def get_account(self) -> dict:
        try:
            account = await asyncio.to_thread(self._client.get_account)
            return {
                "buying_power": float(account.buying_power),
                "cash": float(account.cash),
                "equity": float(account.equity),
                "portfolio_value": float(account.portfolio_value),
            }
        except APIError as e:
            self._handle_api_error(e)
            return {}

    async def close(self) -> None:
        pass  # SDK client doesn't require explicit cleanup

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def is_paper(self) -> bool:
        return self._paper
