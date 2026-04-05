"""Robinhood MCP server — production-grade, JSON-RPC 2.0 compliant.

Exposes trading operations as MCP tools over stdio transport.
Supports real mode (robin_stocks) and paper mode (in-memory simulation).

Env vars:
    RH_USERNAME      — Robinhood username/email
    RH_PASSWORD      — Robinhood password
    RH_TOTP_SECRET   — TOTP secret for MFA
    PAPER_MODE       — "true" to simulate orders without Robinhood
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import threading
import time
import uuid
from collections import deque
from typing import Any

# ---------------------------------------------------------------------------
# Logging — write to stderr so stdout stays clean for JSON-RPC
# ---------------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("robinhood_mcp")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SERVER_NAME = "robinhood-mcp"
SERVER_VERSION = "2.0.0"
PROTOCOL_VERSION = "2024-11-05"
JSONRPC = "2.0"

ORDER_POLL_INTERVAL = 2.0
ORDER_POLL_TIMEOUT = 30.0
RATE_LIMIT_SECONDS = 5.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0

PAPER_MODE = os.environ.get("PAPER_MODE", "").lower() == "true"

# ---------------------------------------------------------------------------
# Rate limiter — max 1 order per RATE_LIMIT_SECONDS
# ---------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._last: float = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last)
            if wait > 0:
                log.debug("Rate-limiting: sleeping %.2fs", wait)
                time.sleep(wait)
            self._last = time.monotonic()


_order_limiter = _RateLimiter(RATE_LIMIT_SECONDS)

# ---------------------------------------------------------------------------
# Paper-mode state
# ---------------------------------------------------------------------------

_paper_orders: dict[str, dict] = {}
_paper_positions: dict[str, dict] = {}
_paper_cash: float = 100_000.00


def _paper_fill_price(price: float) -> float:
    slippage = random.uniform(0.01, 0.05)
    return round(price + random.choice([-1, 1]) * slippage, 4)


def _paper_place_order(
    ticker: str,
    quantity: float,
    side: str,
    price: float,
    order_type: str = "limit",
    *,
    option_type: str | None = None,
    strike: float | None = None,
    expiry: str | None = None,
) -> dict:
    global _paper_cash
    fill = _paper_fill_price(price)
    oid = str(uuid.uuid4())
    order = {
        "id": oid,
        "ticker": ticker,
        "quantity": quantity,
        "side": side,
        "price": price,
        "fill_price": fill,
        "order_type": order_type,
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry,
        "state": "filled",
        "created_at": time.time(),
    }
    _paper_orders[oid] = order

    cost = fill * quantity
    if side == "buy":
        _paper_cash -= cost
        pos = _paper_positions.get(ticker, {"quantity": 0.0, "avg_cost": 0.0})
        total_qty = pos["quantity"] + quantity
        pos["avg_cost"] = round(
            (pos["avg_cost"] * pos["quantity"] + fill * quantity) / total_qty, 4
        ) if total_qty else 0.0
        pos["quantity"] = total_qty
        _paper_positions[ticker] = pos
    else:
        _paper_cash += cost
        pos = _paper_positions.get(ticker)
        if pos:
            pos["quantity"] = max(0.0, pos["quantity"] - quantity)
            if pos["quantity"] == 0:
                _paper_positions.pop(ticker, None)

    log.info("PAPER order %s: %s %s %s @ %.4f (fill %.4f)", oid, side, quantity, ticker, price, fill)
    return order


def _paper_cancel_order(order_id: str) -> dict:
    order = _paper_orders.get(order_id)
    if not order:
        return {"error": f"Order {order_id} not found"}
    order["state"] = "cancelled"
    return {"id": order_id, "state": "cancelled"}


# ---------------------------------------------------------------------------
# Robinhood wrapper — lazy import so paper mode needs no robin_stocks
# ---------------------------------------------------------------------------

_rh = None
_rh_logged_in = False


def _get_rh():
    global _rh
    if _rh is None:
        import robin_stocks.robinhood as rh
        _rh = rh
    return _rh


def _retry(fn, *args, **kwargs):
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            log.warning("Retry %d/%d after error: %s (backoff %.1fs)", attempt, MAX_RETRIES, exc, wait)
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def _ensure_login() -> None:
    global _rh_logged_in
    if PAPER_MODE:
        _rh_logged_in = True
        return
    if _rh_logged_in:
        return
    rh = _get_rh()
    username = os.environ.get("RH_USERNAME", "")
    password = os.environ.get("RH_PASSWORD", "")
    totp_secret = os.environ.get("RH_TOTP_SECRET", "")
    if not username or not password:
        raise ValueError("RH_USERNAME and RH_PASSWORD env vars are required")
    mfa_code = None
    if totp_secret:
        import pyotp
        mfa_code = pyotp.TOTP(totp_secret).now()
    _retry(rh.login, username, password, mfa_code=mfa_code, store_session=True)
    _rh_logged_in = True
    log.info("Logged in to Robinhood as %s", username)


def _poll_order_status(order_id: str) -> dict:
    """Poll an order until filled, cancelled, or timeout."""
    if PAPER_MODE:
        order = _paper_orders.get(order_id, {})
        return {"order_id": order_id, "state": order.get("state", "unknown"), "fill_price": order.get("fill_price")}

    rh = _get_rh()
    deadline = time.monotonic() + ORDER_POLL_TIMEOUT
    while time.monotonic() < deadline:
        info = _retry(rh.orders.get_stock_order_info, order_id)
        state = info.get("state", "unknown")
        if state in ("filled", "cancelled", "failed", "rejected"):
            return {
                "order_id": order_id,
                "state": state,
                "fill_price": info.get("average_price"),
                "filled_quantity": info.get("cumulative_quantity"),
            }
        time.sleep(ORDER_POLL_INTERVAL)

    info = _retry(rh.orders.get_stock_order_info, order_id)
    return {
        "order_id": order_id,
        "state": info.get("state", "unknown"),
        "fill_price": info.get("average_price"),
        "filled_quantity": info.get("cumulative_quantity"),
        "timed_out": True,
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_robinhood_login(_args: dict) -> dict:
    _ensure_login()
    return {"success": True, "paper_mode": PAPER_MODE}


def _tool_get_quote(args: dict) -> dict:
    ticker = args["ticker"]
    if PAPER_MODE:
        base = random.uniform(10, 500)
        return {"ticker": ticker, "price": round(base, 2), "paper_mode": True}
    rh = _get_rh()
    _ensure_login()
    prices = _retry(rh.stocks.get_latest_price, ticker)
    price = float(prices[0]) if prices and prices[0] else 0.0
    quote = _retry(rh.stocks.get_stock_quote_by_symbol, ticker)
    return {
        "ticker": ticker,
        "price": price,
        "bid": float(quote.get("bid_price", 0) or 0),
        "ask": float(quote.get("ask_price", 0) or 0),
        "volume": int(float(quote.get("last_trade_volume", 0) or 0)),
        "previous_close": float(quote.get("previous_close", 0) or 0),
    }


def _tool_get_positions(_args: dict) -> dict:
    _ensure_login()
    if PAPER_MODE:
        return {"positions": [{"ticker": t, **p} for t, p in _paper_positions.items()], "paper_mode": True}
    rh = _get_rh()
    positions = _retry(rh.account.get_open_stock_positions)
    result = []
    for p in positions:
        instr = _retry(rh.stocks.get_instrument_by_url, p["instrument"])
        result.append({
            "ticker": instr.get("symbol", "?"),
            "quantity": float(p["quantity"]),
            "avg_cost": float(p["average_buy_price"]),
            "current_price": float(p.get("last_trade_price", 0) or 0),
        })
    return {"positions": result}


def _tool_place_stock_order(args: dict) -> dict:
    _ensure_login()
    ticker = args["ticker"]
    quantity = float(args["quantity"])
    side = args["side"]
    price = float(args["price"])

    _order_limiter.acquire()

    if PAPER_MODE:
        order = _paper_place_order(ticker, quantity, side, price)
        return {"order_id": order["id"], "state": order["state"], "fill_price": order["fill_price"], "paper_mode": True}

    rh = _get_rh()
    if side == "buy":
        order = _retry(rh.orders.order_buy_limit, ticker, quantity, price)
    else:
        order = _retry(rh.orders.order_sell_limit, ticker, quantity, price)

    oid = order.get("id", "")
    result = _poll_order_status(oid) if oid else {"order_id": oid, "state": order.get("state", "unknown")}
    return result


def _tool_place_option_order(args: dict) -> dict:
    _ensure_login()
    ticker = args["ticker"]
    quantity = int(args["quantity"])
    side = args["side"]
    price = float(args["price"])
    expiry = args["expiry"]
    strike = float(args["strike"])
    option_type = args["option_type"]

    _order_limiter.acquire()

    if PAPER_MODE:
        order = _paper_place_order(ticker, quantity, side, price, option_type=option_type, strike=strike, expiry=expiry)
        return {"order_id": order["id"], "state": order["state"], "fill_price": order["fill_price"], "paper_mode": True}

    rh = _get_rh()
    pos_effect = "open" if side == "buy" else "close"
    order = _retry(
        rh.orders.order_buy_option_limit if side == "buy" else rh.orders.order_sell_option_limit,
        pos_effect, ticker, quantity, price, expiry, strike, option_type,
    )
    oid = order.get("id", "")
    result = _poll_order_status(oid) if oid else {"order_id": oid, "state": order.get("state", "unknown")}
    return result


def _tool_close_position(args: dict) -> dict:
    _ensure_login()
    ticker = args["ticker"]
    quantity = float(args["quantity"])

    _order_limiter.acquire()

    if PAPER_MODE:
        cur_price = random.uniform(10, 500)
        order = _paper_place_order(ticker, quantity, "sell", cur_price, "market")
        return {"order_id": order["id"], "state": order["state"], "fill_price": order["fill_price"], "paper_mode": True}

    rh = _get_rh()
    order = _retry(rh.orders.order_sell_market, ticker, quantity)
    oid = order.get("id", "")
    result = _poll_order_status(oid) if oid else {"order_id": oid, "state": order.get("state", "unknown")}
    return result


def _tool_get_account(_args: dict) -> dict:
    _ensure_login()
    if PAPER_MODE:
        total = _paper_cash + sum(
            p["quantity"] * p["avg_cost"] for p in _paper_positions.values()
        )
        return {"portfolio_value": round(total, 2), "buying_power": round(_paper_cash, 2), "paper_mode": True}
    rh = _get_rh()
    profile = _retry(rh.profiles.load_portfolio_profile)
    account = _retry(rh.profiles.load_account_profile)
    return {
        "portfolio_value": float(profile.get("equity", 0)),
        "buying_power": float(account.get("buying_power", 0)),
        "cash": float(account.get("cash", 0)),
    }


def _tool_get_order_status(args: dict) -> dict:
    _ensure_login()
    order_id = args["order_id"]
    if PAPER_MODE:
        order = _paper_orders.get(order_id)
        if not order:
            return {"error": f"Order {order_id} not found"}
        return {"order_id": order_id, "state": order["state"], "fill_price": order.get("fill_price")}
    rh = _get_rh()
    info = _retry(rh.orders.get_stock_order_info, order_id)
    return {
        "order_id": order_id,
        "state": info.get("state", "unknown"),
        "fill_price": info.get("average_price"),
        "filled_quantity": info.get("cumulative_quantity"),
        "created_at": info.get("created_at"),
        "updated_at": info.get("updated_at"),
    }


# -- New composite tools ---------------------------------------------------

def _tool_place_order_with_stop_loss(args: dict) -> dict:
    """Place main limit order + a separate stop-loss order."""
    _ensure_login()
    ticker = args["ticker"]
    quantity = float(args["quantity"])
    side = args["side"]
    price = float(args["price"])
    stop_price = float(args["stop_price"])
    option_type = args.get("option_type")
    strike = args.get("strike")
    expiry = args.get("expiry")

    _order_limiter.acquire()

    if PAPER_MODE:
        main = _paper_place_order(ticker, quantity, side, price, option_type=option_type, strike=strike and float(strike), expiry=expiry)
        _order_limiter.acquire()
        stop = _paper_place_order(ticker, quantity, "sell", stop_price, "stop_loss")
        return {
            "main_order_id": main["id"], "main_state": main["state"], "main_fill_price": main["fill_price"],
            "stop_order_id": stop["id"], "stop_state": stop["state"],
            "paper_mode": True,
        }

    rh = _get_rh()
    if option_type and strike and expiry:
        pos_effect = "open" if side == "buy" else "close"
        main_order = _retry(
            rh.orders.order_buy_option_limit if side == "buy" else rh.orders.order_sell_option_limit,
            pos_effect, ticker, int(quantity), price, expiry, float(strike), option_type,
        )
    else:
        if side == "buy":
            main_order = _retry(rh.orders.order_buy_limit, ticker, quantity, price)
        else:
            main_order = _retry(rh.orders.order_sell_limit, ticker, quantity, price)

    main_id = main_order.get("id", "")
    main_status = _poll_order_status(main_id) if main_id else {"state": main_order.get("state", "unknown")}

    _order_limiter.acquire()
    stop_order = _retry(rh.orders.order_sell_stop_loss, ticker, quantity, stop_price)
    stop_id = stop_order.get("id", "")

    return {
        "main_order_id": main_id,
        "main_state": main_status.get("state"),
        "main_fill_price": main_status.get("fill_price"),
        "stop_order_id": stop_id,
        "stop_state": stop_order.get("state", "queued"),
    }


def _tool_cancel_and_close(args: dict) -> dict:
    """Cancel the stop-loss order, then market-sell the position."""
    _ensure_login()
    ticker = args["ticker"]
    quantity = float(args["quantity"])
    cancel_id = args.get("cancel_stop_order_id")

    if cancel_id:
        if PAPER_MODE:
            _paper_cancel_order(cancel_id)
        else:
            rh = _get_rh()
            _retry(rh.orders.cancel_stock_order, cancel_id)
        log.info("Cancelled stop order %s", cancel_id)

    _order_limiter.acquire()

    if PAPER_MODE:
        cur_price = random.uniform(10, 500)
        order = _paper_place_order(ticker, quantity, "sell", cur_price, "market")
        return {
            "cancelled_stop_id": cancel_id,
            "close_order_id": order["id"],
            "close_state": order["state"],
            "close_fill_price": order["fill_price"],
            "paper_mode": True,
        }

    rh = _get_rh()
    close_order = _retry(rh.orders.order_sell_market, ticker, quantity)
    close_id = close_order.get("id", "")
    result = _poll_order_status(close_id) if close_id else {"state": close_order.get("state", "unknown")}
    return {
        "cancelled_stop_id": cancel_id,
        "close_order_id": close_id,
        "close_state": result.get("state"),
        "close_fill_price": result.get("fill_price"),
    }


def _tool_modify_stop_loss(args: dict) -> dict:
    """Cancel old stop-loss, place new one at different price."""
    _ensure_login()
    old_id = args["old_order_id"]
    ticker = args["ticker"]
    quantity = float(args["quantity"])
    new_stop = float(args["new_stop_price"])

    if PAPER_MODE:
        _paper_cancel_order(old_id)
        _order_limiter.acquire()
        new_order = _paper_place_order(ticker, quantity, "sell", new_stop, "stop_loss")
        return {
            "cancelled_order_id": old_id,
            "new_order_id": new_order["id"],
            "new_stop_price": new_stop,
            "state": new_order["state"],
            "paper_mode": True,
        }

    rh = _get_rh()
    _retry(rh.orders.cancel_stock_order, old_id)
    log.info("Cancelled old stop %s", old_id)

    _order_limiter.acquire()
    new_order = _retry(rh.orders.order_sell_stop_loss, ticker, quantity, new_stop)
    new_id = new_order.get("id", "")
    return {
        "cancelled_order_id": old_id,
        "new_order_id": new_id,
        "new_stop_price": new_stop,
        "state": new_order.get("state", "queued"),
    }


def _tool_place_order_with_buffer(args: dict) -> dict:
    """Place limit order with price adjusted by buffer_pct."""
    _ensure_login()
    ticker = args["ticker"]
    quantity = float(args["quantity"])
    side = args["side"]
    price = float(args["price"])
    buffer_pct = float(args["buffer_pct"])
    option_type = args.get("option_type")
    strike = args.get("strike")
    expiry = args.get("expiry")

    if side == "buy":
        adjusted = round(price * (1 + buffer_pct / 100), 2)
    else:
        adjusted = round(price * (1 - buffer_pct / 100), 2)

    log.info("Buffer %.2f%%: %s %s %.2f -> %.2f", buffer_pct, side, ticker, price, adjusted)

    order_args: dict[str, Any] = {
        "ticker": ticker, "quantity": quantity, "side": side, "price": adjusted,
    }
    if option_type:
        order_args.update(option_type=option_type, strike=strike, expiry=expiry)
        result = _tool_place_option_order(order_args)
    else:
        result = _tool_place_stock_order(order_args)

    result["original_price"] = price
    result["adjusted_price"] = adjusted
    result["buffer_pct"] = buffer_pct
    return result


def _tool_get_option_chain(args: dict) -> dict:
    """Get option chain for a ticker and expiry date."""
    _ensure_login()
    ticker = args["ticker"]
    expiry = args["expiry"]

    if PAPER_MODE:
        chain: list[dict] = []
        base = random.uniform(100, 400)
        for i in range(-5, 6):
            strike = round(base + i * 5, 2)
            for otype in ("call", "put"):
                chain.append({
                    "type": otype, "strike": strike, "expiry": expiry,
                    "bid": round(random.uniform(0.1, 15), 2),
                    "ask": round(random.uniform(0.1, 15), 2),
                    "volume": random.randint(0, 5000),
                    "open_interest": random.randint(0, 20000),
                })
        return {"ticker": ticker, "expiry": expiry, "options": chain, "paper_mode": True}

    rh = _get_rh()
    options = _retry(rh.options.find_options_by_expiration, ticker, expirationDate=expiry, optionType=None)
    chain = []
    for opt in (options or []):
        chain.append({
            "type": opt.get("type", "unknown"),
            "strike": float(opt.get("strike_price", 0)),
            "expiry": opt.get("expiration_date", expiry),
            "bid": float(opt.get("bid_price", 0) or 0),
            "ask": float(opt.get("ask_price", 0) or 0),
            "volume": int(opt.get("volume", 0) or 0),
            "open_interest": int(opt.get("open_interest", 0) or 0),
        })
    return {"ticker": ticker, "expiry": expiry, "options": chain}


# ---------------------------------------------------------------------------
# Tool registry & JSON schemas
# ---------------------------------------------------------------------------

TOOL_HANDLERS: dict[str, Any] = {
    "robinhood_login": _tool_robinhood_login,
    "get_quote": _tool_get_quote,
    "get_positions": _tool_get_positions,
    "place_stock_order": _tool_place_stock_order,
    "place_option_order": _tool_place_option_order,
    "close_position": _tool_close_position,
    "get_account": _tool_get_account,
    "get_order_status": _tool_get_order_status,
    "place_order_with_stop_loss": _tool_place_order_with_stop_loss,
    "cancel_and_close": _tool_cancel_and_close,
    "modify_stop_loss": _tool_modify_stop_loss,
    "place_order_with_buffer": _tool_place_order_with_buffer,
    "get_option_chain": _tool_get_option_chain,
}

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "robinhood_login",
        "description": "Authenticate with Robinhood. Reads credentials from RH_USERNAME, RH_PASSWORD, RH_TOTP_SECRET env vars. In paper mode, no-ops.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_quote",
        "description": "Get real-time quote for a stock ticker including bid, ask, volume, and previous close.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Stock ticker symbol (e.g. AAPL)"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_positions",
        "description": "List all open stock positions with ticker, quantity, average cost, and current price.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "place_stock_order",
        "description": "Place a stock limit order. Polls for fill status up to 30s.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "quantity": {"type": "number", "description": "Number of shares"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "price": {"type": "number", "description": "Limit price per share"},
            },
            "required": ["ticker", "quantity", "side", "price"],
        },
    },
    {
        "name": "place_option_order",
        "description": "Place an options limit order. Polls for fill status up to 30s.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "quantity": {"type": "integer", "description": "Number of contracts"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "price": {"type": "number", "description": "Limit price per contract"},
                "expiry": {"type": "string", "description": "Expiration date YYYY-MM-DD"},
                "strike": {"type": "number", "description": "Strike price"},
                "option_type": {"type": "string", "enum": ["call", "put"]},
            },
            "required": ["ticker", "quantity", "side", "price", "expiry", "strike", "option_type"],
        },
    },
    {
        "name": "close_position",
        "description": "Market-sell shares to close a position. Polls for fill status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "quantity": {"type": "number"},
            },
            "required": ["ticker", "quantity"],
        },
    },
    {
        "name": "get_account",
        "description": "Get account overview: portfolio value, buying power, and cash.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_order_status",
        "description": "Check the current status and fill price of an order by its ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "Robinhood order UUID"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "place_order_with_stop_loss",
        "description": "Place a main limit order AND a companion stop-loss order. Returns both order IDs. Works for stocks and options.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "quantity": {"type": "number"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "price": {"type": "number", "description": "Limit price for the main order"},
                "stop_price": {"type": "number", "description": "Trigger price for the stop-loss sell"},
                "option_type": {"type": "string", "enum": ["call", "put"], "description": "If trading options"},
                "strike": {"type": "number", "description": "Option strike price"},
                "expiry": {"type": "string", "description": "Option expiry YYYY-MM-DD"},
            },
            "required": ["ticker", "quantity", "side", "price", "stop_price"],
        },
    },
    {
        "name": "cancel_and_close",
        "description": "Cancel an existing stop-loss order (if provided), then market-sell the position to close it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "quantity": {"type": "number"},
                "cancel_stop_order_id": {"type": "string", "description": "Stop-loss order ID to cancel first"},
            },
            "required": ["ticker", "quantity"],
        },
    },
    {
        "name": "modify_stop_loss",
        "description": "Cancel an existing stop-loss order and place a new one at a different price (e.g. to trail).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_order_id": {"type": "string", "description": "Current stop-loss order ID to cancel"},
                "ticker": {"type": "string"},
                "quantity": {"type": "number"},
                "new_stop_price": {"type": "number", "description": "New stop-loss trigger price"},
            },
            "required": ["old_order_id", "ticker", "quantity", "new_stop_price"],
        },
    },
    {
        "name": "place_order_with_buffer",
        "description": "Place a limit order with the price adjusted by a buffer percentage. For buys: price*(1+buffer/100). For sells: price*(1-buffer/100).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "quantity": {"type": "number"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "price": {"type": "number", "description": "Base price before buffer adjustment"},
                "buffer_pct": {"type": "number", "description": "Buffer percentage (e.g. 0.5 for 0.5%)"},
                "option_type": {"type": "string", "enum": ["call", "put"]},
                "strike": {"type": "number"},
                "expiry": {"type": "string"},
            },
            "required": ["ticker", "quantity", "side", "price", "buffer_pct"],
        },
    },
    {
        "name": "get_option_chain",
        "description": "Get the full option chain for a ticker at a specific expiry. Returns strike, bid, ask, volume, and open interest for calls and puts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "expiry": {"type": "string", "description": "Expiration date YYYY-MM-DD"},
            },
            "required": ["ticker", "expiry"],
        },
    },
]

# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def _rpc_result(req_id: int | str | None, result: Any) -> dict:
    return {"jsonrpc": JSONRPC, "id": req_id, "result": result}


def _rpc_error(req_id: int | str | None, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": JSONRPC, "id": req_id, "error": err}


def _send(msg: dict) -> None:
    payload = json.dumps(msg, separators=(",", ":"))
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# MCP message router
# ---------------------------------------------------------------------------

def _handle_message(request: dict) -> dict | None:
    """Process one JSON-RPC message. Returns response dict, or None for notifications."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})
    is_notification = "id" not in request

    # -- Lifecycle ----------------------------------------------------------

    if method == "initialize":
        return _rpc_result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        })

    if method == "notifications/initialized":
        log.info("Client initialized — ready to serve tools")
        return None

    if method == "notifications/cancelled":
        log.debug("Client cancelled request %s", params.get("requestId"))
        return None

    # -- Tool discovery -----------------------------------------------------

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOL_DEFINITIONS})

    # -- Tool invocation ----------------------------------------------------

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)

        if handler is None:
            return _rpc_result(req_id, {
                "content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"})}],
                "isError": True,
            })

        try:
            result = handler(arguments)
            return _rpc_result(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            })
        except Exception as exc:
            log.exception("Tool %s failed", tool_name)
            return _rpc_result(req_id, {
                "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                "isError": True,
            })

    # -- Ping ---------------------------------------------------------------

    if method == "ping":
        return _rpc_result(req_id, {})

    # -- Unknown method -----------------------------------------------------

    if is_notification:
        log.debug("Ignoring unknown notification: %s", method)
        return None

    return _rpc_error(req_id, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Main loop — stdio transport
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Starting %s v%s (paper_mode=%s)", SERVER_NAME, SERVER_VERSION, PAPER_MODE)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _send(_rpc_error(None, -32700, f"Parse error: {exc}"))
            continue

        if not isinstance(request, dict):
            _send(_rpc_error(None, -32600, "Invalid Request: expected JSON object"))
            continue

        response = _handle_message(request)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
