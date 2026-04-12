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
from pathlib import Path
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
# Session-pickle home directory — must be the agent's persistent work-dir,
# NOT the ephemeral container /root.  Override HOME at process startup so that
# both the Claude Code-managed MCP server (settings.json) and any subprocess
# started by execute_trade.py see the same .tokens/ path.  The agent work-dir
# is the parent of this tools/ directory.
# Guard: skip the override when running directly from the template source tree
# (e.g. during development) so pickle files don't accumulate in the repo.
# ---------------------------------------------------------------------------
_AGENT_WORK_DIR = str(Path(__file__).resolve().parent.parent)
if "templates" not in Path(__file__).resolve().parts:
    os.environ["HOME"] = _AGENT_WORK_DIR

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
# Thread-local flag used by _retry to prevent recursive re-auth calls.
_in_retry_reauth = threading.local()


def _get_rh():
    global _rh
    if _rh is None:
        import robin_stocks.robinhood as rh
        _rh = rh
    return _rh


_AUTH_ERROR_KEYWORDS = ("401", "unauthorized", "unauthenticated")


def _retry(fn, *args, **kwargs):
    global _rh_logged_in
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            err_str = str(exc).lower()
            # On 401/Unauthorized, reset the auth flag AND attempt a silent
            # re-auth before the next retry so that subsequent attempts use
            # a fresh session instead of replaying against a dead token.
            # The thread-local guard prevents infinite recursion when _retry
            # is called from within _ensure_login itself (e.g. for rh.login).
            if any(kw in err_str for kw in _AUTH_ERROR_KEYWORDS):
                _rh_logged_in = False
                log.warning("Auth error on attempt %d — session marked for renewal", attempt)
                if (
                    attempt < MAX_RETRIES
                    and not PAPER_MODE
                    and not getattr(_in_retry_reauth, "active", False)
                ):
                    _in_retry_reauth.active = True
                    try:
                        _ensure_login()
                        log.info("Re-authenticated on attempt %d", attempt)
                    except Exception as reauth_exc:
                        log.warning("Re-auth failed during retry: %s", reauth_exc)
                    finally:
                        _in_retry_reauth.active = False
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            log.warning("Retry %d/%d after error: %s (backoff %.1fs)", attempt, MAX_RETRIES, exc, wait)
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def _load_credentials() -> tuple[str, str, str]:
    """Load Robinhood credentials from env vars, then config.json in CWD.

    Order of precedence:
      1. Env vars: RH_USERNAME, RH_PASSWORD, RH_TOTP_SECRET
      2. ROBINHOOD_CONFIG env var pointing to a JSON file
      3. ./config.json in current working directory (the agent's work_dir)
         Looks under the `robinhood_credentials` key first (Phoenix spawn format),
         then the `robinhood` key (local dev format).
    """
    username = os.environ.get("RH_USERNAME", "")
    password = os.environ.get("RH_PASSWORD", "")
    totp_secret = os.environ.get("RH_TOTP_SECRET", "")

    if username and password:
        return username, password, totp_secret

    # Try ROBINHOOD_CONFIG first, then ./config.json
    config_candidates = []
    if os.environ.get("ROBINHOOD_CONFIG"):
        config_candidates.append(os.environ["ROBINHOOD_CONFIG"])
    config_candidates.append("config.json")

    for cfg_path in config_candidates:
        try:
            from pathlib import Path as _Path
            p = _Path(cfg_path)
            if not p.exists():
                continue
            import json as _json
            with open(p) as f:
                cfg = _json.load(f)
            # Phoenix writes robinhood_credentials; local dev uses robinhood
            rh_cfg = cfg.get("robinhood_credentials") or cfg.get("robinhood") or {}
            if rh_cfg:
                username = username or rh_cfg.get("username", "")
                password = password or rh_cfg.get("password", "")
                totp_secret = totp_secret or rh_cfg.get("totp_secret", "")
                if username and password:
                    log.info("Loaded Robinhood credentials from %s", cfg_path)
                    return username, password, totp_secret
        except Exception as exc:
            log.warning("Failed to read %s: %s", cfg_path, exc)

    return username, password, totp_secret


def _ensure_token_dir() -> None:
    """Ensure the .tokens/ directory exists for session pickle persistence.

    robin_stocks stores session pickles in ~/.tokens/ by default.
    We create it under HOME (the agent's persistent work-dir) so pickles
    survive container restarts without re-authenticating.
    Mode 0o700 (owner-only) limits exposure of the session pickle files.
    """
    from pathlib import Path as _P
    home_tokens = _P.home() / ".tokens"
    home_tokens.mkdir(parents=True, exist_ok=True)
    try:
        home_tokens.chmod(0o700)
    except OSError as chmod_exc:
        log.warning(
            "Could not set .tokens/ to mode 0700 (%s) — pickle may be world-readable; "
            "ensure the directory is protected at the filesystem level.",
            chmod_exc,
        )


def _try_restore_session_from_pickle(rh: Any, pickle_name: str) -> bool:
    """Restore a live session directly from the robin_stocks pickle file.

    Returns True if the session was restored successfully (NO network call).
    Returns False if the pickle is missing, unreadable, or the token has
    expired (with a 5-minute buffer so we don't use a nearly-stale token).

    This is a zero-network-call fast-path that prevents Robinhood from seeing
    repeated login events and triggering "suspicious login" device-approval
    push notifications.

    Expiry handling:
      - robin_stocks >= 3.x writes ``expires_in`` (duration in seconds).
      - Some versions write ``expires_at`` (absolute UNIX timestamp).
      - We support both; when only ``expires_in`` is present we compute
        ``expires_at`` from the pickle file's mtime + expires_in.
      - If neither is present we cannot validate expiry and return False so
        ``rh.login()`` handles the session safely.
    """
    import os as _os
    import pickle as _pickle
    from pathlib import Path as _P

    pickle_path = _P.home() / ".tokens" / f"{pickle_name}.pickle"
    if not pickle_path.exists():
        log.debug("No session pickle at %s", pickle_path)
        return False

    # Security: ensure the pickle is owned by the current process user so we
    # don't deserialise a file dropped by another user on a shared volume.
    try:
        stat = pickle_path.stat()
        if stat.st_uid != _os.getuid():
            log.warning(
                "Session pickle %s is owned by uid %d, current uid %d — refusing to load",
                pickle_path,
                stat.st_uid,
                _os.getuid(),
            )
            return False
    except AttributeError:
        # os.getuid() not available on Windows (dev machine) — skip ownership check
        pass
    except Exception as sec_exc:
        log.warning("Could not check pickle ownership: %s — skipping restore", sec_exc)
        return False

    try:
        with open(pickle_path, "rb") as fh:
            data = _pickle.load(fh)

        access_token: str = data.get("access_token", "")
        if not access_token:
            log.debug("Pickle has no access_token — skipping restore")
            return False

        # Determine absolute expiry time, supporting both pickle formats
        expires_at: float = float(data.get("expires_at", 0) or 0)
        if not expires_at:
            expires_in = float(data.get("expires_in", 0) or 0)
            if expires_in > 0:
                # Approximate absolute expiry from file mtime + duration
                expires_at = pickle_path.stat().st_mtime + expires_in
            else:
                # No expiry information — cannot validate; force full re-auth
                log.debug("Pickle has no expiry info — will re-authenticate")
                return False

        # Require at least 5 minutes of remaining validity
        if time.time() >= expires_at - 300:
            log.info(
                "Session pickle expired (%.0f s ago) — will re-authenticate",
                time.time() - expires_at,
            )
            return False

        # Restore the session token — identical to what robin_stocks does internally
        rh.SESSION.headers.update({"Authorization": f"Bearer {access_token}"})
        remaining_h = (expires_at - time.time()) / 3600
        log.info(
            "Session restored from pickle (pickle=%s, ~%.1fh remaining)",
            pickle_name,
            remaining_h,
        )
        return True

    except Exception as exc:
        log.warning("Failed to restore session from pickle %s: %s", pickle_path, exc)
        return False


def _ensure_login() -> None:
    global _rh_logged_in
    if PAPER_MODE:
        _rh_logged_in = True
        return
    if _rh_logged_in:
        return
    rh = _get_rh()

    username, password, totp_secret = _load_credentials()

    if not username or not password:
        raise ValueError(
            "Robinhood credentials missing. Provide RH_USERNAME and RH_PASSWORD env vars, "
            "or a config.json with `robinhood_credentials` in the current working directory."
        )

    _ensure_token_dir()

    # Stable pickle name so sessions persist across process restarts.
    pickle_name = f"phoenix_{username.split('@')[0]}" if username else ""

    # Strategy 1: Restore from valid pickle — ZERO network calls.
    # This is the primary path for every call after the first daily login.
    # It prevents Robinhood from seeing repeated login events and avoids
    # triggering "suspicious login" device-approval push notifications.
    if _try_restore_session_from_pickle(rh, pickle_name):
        _rh_logged_in = True
        return

    # Strategy 2: Full login with TOTP — avoids device-approval notifications.
    # Requires Robinhood 2FA set to "Authenticator App" (not "Device Approval").
    # Store the TOTP base32 secret in the connector credentials (totp_secret field).
    mfa_code = None
    if totp_secret:
        try:
            import pyotp
            mfa_code = pyotp.TOTP(totp_secret).now()
            log.info("Generated TOTP code for %s", username)
        except Exception as exc:
            log.warning("TOTP generation failed: %s — will attempt device approval", exc)

    # Strategy 3: rh.login() with store_session=True writes the pickle so the
    # next process restart uses Strategy 1 (no network call).
    # expiresIn=86400 requests a 24-hour token — valid for a full trading day.
    try:
        _retry(
            rh.login,
            username,
            password,
            mfa_code=mfa_code,
            store_session=True,
            expiresIn=86400,
            pickle_name=pickle_name,
        )
    except Exception as first_err:
        # If TOTP was provided but login failed (e.g. wrong secret or clock skew),
        # attempt once without mfa_code so the pickle-restore path can succeed on
        # the next invocation even if this attempt requires device approval.
        # We do NOT retry in a loop here to avoid sending multiple push notifications.
        if mfa_code:
            log.warning("Login with TOTP failed (%s), retrying once without MFA code", first_err)
            try:
                rh.login(
                    username,
                    password,
                    store_session=True,
                    expiresIn=86400,
                    pickle_name=pickle_name,
                )
            except Exception as second_err:
                log.warning("No-MFA fallback also failed: %s", second_err)
                raise first_err
        else:
            raise

    _rh_logged_in = True
    log.info("Logged in to Robinhood as %s (pickle=%s)", username, pickle_name)


def _poll_order_status(order_id: str, is_option: bool = False) -> dict:
    """Poll an order until filled, cancelled, or timeout."""
    if PAPER_MODE:
        order = _paper_orders.get(order_id, {})
        return {"order_id": order_id, "state": order.get("state", "unknown"), "fill_price": order.get("fill_price")}

    rh = _get_rh()
    TERMINAL_STATES = ("filled", "cancelled", "failed", "rejected")
    deadline = time.monotonic() + ORDER_POLL_TIMEOUT

    def _get_info():
        if is_option:
            try:
                return _retry(rh.orders.get_option_order_info, order_id)
            except Exception:
                return _retry(rh.orders.get_stock_order_info, order_id)
        return _retry(rh.orders.get_stock_order_info, order_id)

    while time.monotonic() < deadline:
        info = _get_info()
        state = info.get("state", "unknown")
        if state in TERMINAL_STATES:
            return {
                "order_id": order_id,
                "state": state,
                "fill_price": info.get("average_price") or info.get("price"),
                "filled_quantity": info.get("cumulative_quantity") or info.get("processed_quantity"),
            }
        time.sleep(ORDER_POLL_INTERVAL)

    info = _get_info()
    final_state = info.get("state", "unknown")
    return {
        "order_id": order_id,
        "state": "timed_out",
        "broker_state": final_state,
        "fill_price": info.get("average_price") or info.get("price"),
        "filled_quantity": info.get("cumulative_quantity") or info.get("processed_quantity"),
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

    if side == "buy":
        acct = _tool_get_account({})
        buying_power = float(acct.get("buying_power") or 0)
        notional = quantity * price
        if notional > buying_power:
            return {
                "status": "rejected",
                "reason": "insufficient_buying_power",
                "needed": round(notional, 2),
                "available": round(buying_power, 2),
            }

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

    if side == "buy":
        acct = _tool_get_account({})
        buying_power = float(acct.get("buying_power") or 0)
        notional = quantity * price * 100  # each contract = 100 shares
        if notional > buying_power:
            return {
                "status": "rejected",
                "reason": "insufficient_buying_power",
                "needed": round(notional, 2),
                "available": round(buying_power, 2),
            }

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
    result = _poll_order_status(oid, is_option=True) if oid else {"order_id": oid, "state": order.get("state", "unknown")}
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
    is_option = args.get("is_option", False)
    if PAPER_MODE:
        order = _paper_orders.get(order_id)
        if not order:
            return {"error": f"Order {order_id} not found"}
        return {"order_id": order_id, "state": order["state"], "fill_price": order.get("fill_price")}
    rh = _get_rh()
    # Try stock order first, fall back to option order
    info = None
    if not is_option:
        try:
            info = _retry(rh.orders.get_stock_order_info, order_id)
            if info and info.get("state"):
                return {
                    "order_id": order_id,
                    "type": "stock",
                    "state": info.get("state", "unknown"),
                    "fill_price": info.get("average_price"),
                    "filled_quantity": info.get("cumulative_quantity"),
                    "created_at": info.get("created_at"),
                    "updated_at": info.get("updated_at"),
                }
        except Exception:
            pass
    # Try option order lookup
    try:
        info = _retry(rh.orders.get_option_order_info, order_id)
        if info and info.get("state"):
            return {
                "order_id": order_id,
                "type": "option",
                "state": info.get("state", "unknown"),
                "fill_price": info.get("price") or info.get("premium"),
                "filled_quantity": info.get("processed_quantity") or info.get("quantity"),
                "created_at": info.get("created_at"),
                "updated_at": info.get("updated_at"),
            }
    except Exception:
        pass
    return {"order_id": order_id, "state": "unknown", "error": "Could not find order in stock or option orders"}


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

    is_option_trade = bool(option_type and strike and expiry)
    if is_option_trade:
        # robin_stocks doesn't support stop-loss for options; record intent only
        return {
            "main_order_id": main_id,
            "main_state": main_status.get("state"),
            "main_fill_price": main_status.get("fill_price"),
            "stop_order_id": None,
            "stop_state": "not_supported_for_options",
            "stop_price_target": stop_price,
            "note": "Option stop-loss tracked by position monitor agent, not as a broker order",
        }

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
# Watchlist tools (Phase 1.5 — used by paper trading mode)
# ---------------------------------------------------------------------------

DEFAULT_WATCHLIST_NAME = "Phoenix Paper"


def _tool_add_to_watchlist(args: dict) -> dict:
    """Add one or more symbols to a Robinhood watchlist."""
    _ensure_login()
    symbols = args.get("symbols")
    if isinstance(symbols, str):
        symbols = [symbols]
    if not symbols:
        return {"error": "no symbols provided"}
    watchlist_name = args.get("watchlist_name", DEFAULT_WATCHLIST_NAME)

    if PAPER_MODE:
        return {
            "status": "added_paper",
            "symbols": symbols,
            "watchlist_name": watchlist_name,
            "paper_mode": True,
        }

    try:
        rh = _get_rh()
        result = _retry(rh.account.post_symbols_to_watchlist, symbols, watchlist_name)
        return {
            "status": "added",
            "symbols": symbols,
            "watchlist_name": watchlist_name,
            "result": result,
        }
    except Exception as exc:
        log.warning("add_to_watchlist failed: %s", exc)
        return {
            "status": "fallback_only",
            "symbols": symbols,
            "watchlist_name": watchlist_name,
            "error": str(exc)[:200],
        }


def _tool_remove_from_watchlist(args: dict) -> dict:
    """Remove one or more symbols from a Robinhood watchlist."""
    _ensure_login()
    symbols = args.get("symbols")
    if isinstance(symbols, str):
        symbols = [symbols]
    if not symbols:
        return {"error": "no symbols provided"}
    watchlist_name = args.get("watchlist_name", DEFAULT_WATCHLIST_NAME)

    try:
        rh = _get_rh()
        result = _retry(rh.account.delete_symbols_from_watchlist, symbols, watchlist_name)
        return {
            "status": "removed",
            "symbols": symbols,
            "watchlist_name": watchlist_name,
            "result": result,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}


def _tool_get_watchlist(args: dict) -> dict:
    """Get all symbols in a Robinhood watchlist."""
    _ensure_login()
    watchlist_name = args.get("watchlist_name", DEFAULT_WATCHLIST_NAME)

    try:
        rh = _get_rh()
        items = _retry(rh.account.get_watchlist_by_name, watchlist_name)
        symbols = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    sym = item.get("symbol") or item.get("instrument", {}).get("symbol")
                    if sym:
                        symbols.append(sym)
        return {
            "watchlist_name": watchlist_name,
            "symbols": symbols,
            "count": len(symbols),
        }
    except Exception as exc:
        return {"watchlist_name": watchlist_name, "symbols": [], "error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# P13 — HFT / algo tools
# ---------------------------------------------------------------------------

_nbbo_cache: dict[str, tuple[float, dict]] = {}
_account_cache: tuple[float, dict] | None = None


def _tool_get_nbbo(args: dict) -> dict:
    """P13: Return NBBO snapshot {bid, ask, mid, spread_pct, stale_ms} cached 500ms."""
    import time as _time
    ticker = args["ticker"]
    now = _time.time()
    cached = _nbbo_cache.get(ticker)
    if cached and (now - cached[0]) * 1000 < 500:
        return cached[1]
    quote = _tool_get_quote({"ticker": ticker})
    bid = float(quote.get("bid", 0) or 0)
    ask = float(quote.get("ask", 0) or 0)
    last = float(quote.get("price", 0) or 0)
    mid = (bid + ask) / 2 if (bid and ask and ask > bid) else last
    spread_pct = ((ask - bid) / mid) if mid > 0 else 0.0
    nbbo = {
        "ticker": ticker,
        "bid": bid,
        "ask": ask,
        "mid": round(mid, 2),
        "last": last,
        "spread_pct": round(spread_pct, 6),
        "spread_bps": round(spread_pct * 10000, 2),
        "stale_ms": 0,
        "fetched_at": now,
    }
    _nbbo_cache[ticker] = (now, nbbo)
    return nbbo


def _tool_get_account_snapshot(_args: dict) -> dict:
    """P13: Account snapshot cached 500ms for pre-trade risk checks."""
    import time as _time
    global _account_cache
    now = _time.time()
    if _account_cache and (now - _account_cache[0]) * 1000 < 500:
        return _account_cache[1]
    snap = _tool_get_account({})
    _account_cache = (now, snap)
    return snap


def _tool_smart_limit_order(args: dict) -> dict:
    """P13: Place a limit order pegged to the current NBBO midpoint.

    Pre-trade: checks buying power, fetches NBBO, decides marketable vs passive.
    Uses existing place_stock_order / place_option_order under the hood.
    """
    ticker = args["ticker"]
    side = args.get("side", "buy")
    quantity = float(args["quantity"])
    buffer_bps = float(args.get("buffer_bps", 5.0))

    nbbo = _tool_get_nbbo({"ticker": ticker})
    if nbbo.get("mid", 0) <= 0:
        return {"status": "error", "reason": "no_nbbo"}

    acct = _tool_get_account_snapshot({})
    buying_power = float(acct.get("buying_power") or 0)
    notional = quantity * nbbo["mid"]
    if side == "buy" and notional > buying_power:
        return {
            "status": "rejected",
            "reason": "insufficient_buying_power",
            "needed": round(notional, 2),
            "available": round(buying_power, 2),
        }

    # Peg to mid + side-directional offset
    bps_offset = (buffer_bps / 10000.0) * nbbo["mid"]
    half_spread = (nbbo["ask"] - nbbo["bid"]) / 2 if nbbo["ask"] > nbbo["bid"] else 0.0
    offset = max(bps_offset, half_spread, 0.01)
    limit_price = round(
        nbbo["mid"] + (offset if side == "buy" else -offset), 2
    )

    return _tool_place_stock_order({
        "ticker": ticker,
        "quantity": quantity,
        "side": side,
        "price": limit_price,
    }) | {
        "nbbo": nbbo,
        "limit_price": limit_price,
        "buffer_bps_used": buffer_bps,
        "notional": round(notional, 2),
    }


# ---------------------------------------------------------------------------
# Options positions, order history, and Greeks tools
# ---------------------------------------------------------------------------

def _tool_get_option_positions(_args: dict) -> dict:
    """List ALL open option positions with contract details, P&L, and Greeks."""
    _ensure_login()
    if PAPER_MODE:
        return {"positions": [], "paper_mode": True}

    rh = _get_rh()
    positions = _retry(rh.account.get_open_option_positions) or []
    result = []
    for p in positions:
        qty = float(p.get("quantity", 0))
        if qty == 0:
            continue
        avg_price = float(p.get("average_price", 0) or 0) / 100.0
        option_id = p.get("option", "")

        entry = {
            "quantity": qty,
            "avg_cost_per_contract": round(avg_price, 4),
            "type": p.get("type", "unknown"),
            "option_id": option_id.split("/")[-2] if "/" in option_id else option_id,
        }

        try:
            from robin_stocks.robinhood.options import get_option_market_data_by_id
            md = get_option_market_data_by_id(entry["option_id"])
            if md and isinstance(md, list):
                md = md[0] if md else {}
            if md:
                entry.update({
                    "ticker": md.get("chain_symbol", "?"),
                    "strike": float(md.get("strike_price", 0) or 0),
                    "expiry": md.get("expiration_date", "?"),
                    "option_type": md.get("type", "?"),
                    "mark_price": float(md.get("mark_price", 0) or 0),
                    "bid": float(md.get("bid_price", 0) or 0),
                    "ask": float(md.get("ask_price", 0) or 0),
                    "delta": float(md.get("delta", 0) or 0),
                    "gamma": float(md.get("gamma", 0) or 0),
                    "theta": float(md.get("theta", 0) or 0),
                    "vega": float(md.get("vega", 0) or 0),
                    "iv": float(md.get("implied_volatility", 0) or 0),
                    "volume": int(float(md.get("volume", 0) or 0)),
                    "open_interest": int(float(md.get("open_interest", 0) or 0)),
                })
                mark = entry.get("mark_price", 0)
                pnl_per = (mark - avg_price) if qty > 0 else (avg_price - mark)
                entry["pnl_per_contract"] = round(pnl_per, 4)
                entry["pnl_total"] = round(pnl_per * qty * 100, 2)
                entry["pnl_pct"] = round((pnl_per / avg_price) * 100, 2) if avg_price else 0
        except Exception as exc:
            log.warning("Failed to enrich option position %s: %s", entry.get("option_id"), exc)

        result.append(entry)

    return {"positions": result, "count": len(result)}


def _tool_get_all_positions(_args: dict) -> dict:
    """Combined view: ALL stock + option positions in one call."""
    stocks = _tool_get_positions({})
    options = _tool_get_option_positions({})
    return {
        "stock_positions": stocks.get("positions", []),
        "option_positions": options.get("positions", []),
        "stock_count": len(stocks.get("positions", [])),
        "option_count": options.get("count", 0),
    }


def _tool_close_option_position(args: dict) -> dict:
    """Close an option position by selling the contracts at limit or market."""
    _ensure_login()
    ticker = args["ticker"]
    quantity = int(args["quantity"])
    expiry = args["expiry"]
    strike = float(args["strike"])
    option_type = args["option_type"]
    price = float(args.get("price", 0))

    _order_limiter.acquire()

    if PAPER_MODE:
        order = _paper_place_order(ticker, quantity, "sell", price or 1.0, option_type=option_type, strike=strike, expiry=expiry)
        return {"order_id": order["id"], "state": order["state"], "paper_mode": True}

    rh = _get_rh()
    if price > 0:
        order = _retry(
            rh.orders.order_sell_option_limit,
            "close", ticker, quantity, price, expiry, strike, option_type,
        )
    else:
        order = _retry(
            rh.orders.order_sell_option_limit,
            "close", ticker, quantity, 0.01, expiry, strike, option_type,
        )
    oid = order.get("id", "")
    result = _poll_order_status(oid, is_option=True) if oid else {"order_id": oid, "state": order.get("state", "unknown")}
    return result


def _tool_get_order_history(args: dict) -> dict:
    """Get recent order history (stocks and/or options)."""
    _ensure_login()
    order_type = args.get("type", "all")
    limit = int(args.get("limit", 20))

    if PAPER_MODE:
        orders = list(_paper_orders.values())[-limit:]
        return {"orders": orders, "count": len(orders), "paper_mode": True}

    rh = _get_rh()
    result = []

    if order_type in ("all", "stock"):
        stock_orders = _retry(rh.orders.get_all_stock_orders) or []
        for o in stock_orders[:limit]:
            ticker = "?"
            instrument_url = o.get("instrument", "")
            if instrument_url:
                try:
                    instr = _retry(rh.stocks.get_instrument_by_url, instrument_url)
                    ticker = instr.get("symbol", "?") if instr else "?"
                except Exception:
                    ticker = o.get("instrument_id", "?")
            result.append({
                "id": o.get("id", ""),
                "type": "stock",
                "side": o.get("side", ""),
                "ticker": ticker,
                "quantity": o.get("quantity", ""),
                "price": o.get("price") or o.get("average_price"),
                "state": o.get("state", ""),
                "created_at": o.get("created_at", ""),
                "updated_at": o.get("updated_at", ""),
            })

    if order_type in ("all", "option"):
        try:
            from datetime import datetime as _dt
            from datetime import timedelta as _td
            start = (_dt.now() - _td(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            option_orders = _retry(rh.orders.get_all_option_orders, start_date=start) or []
        except TypeError:
            option_orders = _retry(rh.orders.get_all_option_orders) or []
        for o in option_orders[:limit]:
            legs = o.get("legs", [{}])
            leg = legs[0] if legs else {}
            result.append({
                "id": o.get("id", ""),
                "type": "option",
                "side": leg.get("side", o.get("direction", "")),
                "quantity": o.get("quantity") or o.get("processed_quantity"),
                "price": o.get("price") or o.get("premium"),
                "state": o.get("state", ""),
                "opening_strategy": o.get("opening_strategy", ""),
                "closing_strategy": o.get("closing_strategy", ""),
                "created_at": o.get("created_at", ""),
                "updated_at": o.get("updated_at", ""),
            })

    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"orders": result[:limit], "count": len(result[:limit])}


def _tool_get_option_greeks(args: dict) -> dict:
    """Get real-time Greeks and market data for a specific option contract."""
    _ensure_login()
    ticker = args["ticker"]
    expiry = args["expiry"]
    strike = float(args["strike"])
    option_type = args["option_type"]

    if PAPER_MODE:
        return {
            "ticker": ticker, "strike": strike, "expiry": expiry, "option_type": option_type,
            "delta": round(random.uniform(0.1, 0.9), 4),
            "gamma": round(random.uniform(0.01, 0.1), 4),
            "theta": round(random.uniform(-0.5, -0.01), 4),
            "vega": round(random.uniform(0.01, 0.3), 4),
            "iv": round(random.uniform(0.15, 1.5), 4),
            "paper_mode": True,
        }

    rh = _get_rh()
    try:
        md = _retry(rh.options.get_option_market_data, ticker, expiry, str(strike), option_type)
        if md and isinstance(md, list):
            md = md[0] if md else [{}]
            if isinstance(md, list):
                md = md[0] if md else {}
        if not md:
            return {"error": f"No market data for {ticker} {strike} {option_type} {expiry}"}
        return {
            "ticker": ticker, "strike": strike, "expiry": expiry, "option_type": option_type,
            "bid": float(md.get("bid_price", 0) or 0),
            "ask": float(md.get("ask_price", 0) or 0),
            "mark": float(md.get("mark_price", 0) or 0),
            "last": float(md.get("last_trade_price", 0) or 0),
            "delta": float(md.get("delta", 0) or 0),
            "gamma": float(md.get("gamma", 0) or 0),
            "theta": float(md.get("theta", 0) or 0),
            "vega": float(md.get("vega", 0) or 0),
            "rho": float(md.get("rho", 0) or 0),
            "iv": float(md.get("implied_volatility", 0) or 0),
            "volume": int(float(md.get("volume", 0) or 0)),
            "open_interest": int(float(md.get("open_interest", 0) or 0)),
            "high": float(md.get("high_price", 0) or 0),
            "low": float(md.get("low_price", 0) or 0),
            "chance_of_profit_long": float(md.get("chance_of_profit_long", 0) or 0),
            "chance_of_profit_short": float(md.get("chance_of_profit_short", 0) or 0),
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Tool registry & JSON schemas
# ---------------------------------------------------------------------------

TOOL_HANDLERS: dict[str, Any] = {
    "robinhood_login": _tool_robinhood_login,
    "get_quote": _tool_get_quote,
    "get_nbbo": _tool_get_nbbo,
    "get_account_snapshot": _tool_get_account_snapshot,
    "smart_limit_order": _tool_smart_limit_order,
    "get_positions": _tool_get_positions,
    "get_option_positions": _tool_get_option_positions,
    "get_all_positions": _tool_get_all_positions,
    "place_stock_order": _tool_place_stock_order,
    "place_option_order": _tool_place_option_order,
    "close_position": _tool_close_position,
    "close_option_position": _tool_close_option_position,
    "get_account": _tool_get_account,
    "get_order_status": _tool_get_order_status,
    "get_order_history": _tool_get_order_history,
    "get_option_greeks": _tool_get_option_greeks,
    "place_order_with_stop_loss": _tool_place_order_with_stop_loss,
    "cancel_and_close": _tool_cancel_and_close,
    "modify_stop_loss": _tool_modify_stop_loss,
    "place_order_with_buffer": _tool_place_order_with_buffer,
    "get_option_chain": _tool_get_option_chain,
    "add_to_watchlist": _tool_add_to_watchlist,
    "remove_from_watchlist": _tool_remove_from_watchlist,
    "get_watchlist": _tool_get_watchlist,
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
        "description": "List all open STOCK positions with ticker, quantity, average cost, and current price.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_option_positions",
        "description": "List ALL open OPTION positions with full details: ticker, strike, expiry, type, quantity, avg cost, current mark price, P&L, and live Greeks (delta, gamma, theta, vega, IV).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_all_positions",
        "description": "Get a combined view of ALL open positions — both stocks AND options — in a single call. Best for portfolio overview.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "close_option_position",
        "description": "Close an option position by selling the contracts. Specify ticker, quantity, expiry, strike, option_type, and optionally a limit price (omit price or set 0 for market-like close at $0.01).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "quantity": {"type": "integer", "description": "Number of contracts to sell"},
                "expiry": {"type": "string", "description": "Expiration date YYYY-MM-DD"},
                "strike": {"type": "number", "description": "Strike price"},
                "option_type": {"type": "string", "enum": ["call", "put"]},
                "price": {"type": "number", "description": "Limit price per contract (optional; 0 = market-like)"},
            },
            "required": ["ticker", "quantity", "expiry", "strike", "option_type"],
        },
    },
    {
        "name": "get_order_history",
        "description": "Get recent order history for stocks and/or options. Returns the most recent orders with status, fills, and timestamps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["all", "stock", "option"], "description": "Filter by order type (default: all)"},
                "limit": {"type": "integer", "description": "Max number of orders to return (default: 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_option_greeks",
        "description": "Get real-time Greeks (delta, gamma, theta, vega, rho), IV, bid/ask, volume, open interest, and chance of profit for a specific option contract.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "expiry": {"type": "string", "description": "Expiration date YYYY-MM-DD"},
                "strike": {"type": "number"},
                "option_type": {"type": "string", "enum": ["call", "put"]},
            },
            "required": ["ticker", "expiry", "strike", "option_type"],
        },
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
    {
        "name": "add_to_watchlist",
        "description": "Add one or more symbols to a Robinhood watchlist (default: 'Phoenix Paper'). Used in PAPER mode instead of placing real orders.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Single ticker or list of tickers to add",
                },
                "watchlist_name": {"type": "string", "description": "Watchlist name (default: 'Phoenix Paper')"},
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "remove_from_watchlist",
        "description": "Remove one or more symbols from a Robinhood watchlist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "watchlist_name": {"type": "string"},
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_watchlist",
        "description": "Get all symbols in a Robinhood watchlist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "watchlist_name": {"type": "string", "description": "Watchlist name (default: 'Phoenix Paper')"},
            },
            "required": [],
        },
    },
    {
        "name": "smart_limit_order",
        "description": "Place a limit order pegged to the current NBBO midpoint with buffer. Pre-checks buying power. Preferred over place_stock_order for most trades.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "quantity": {"type": "number", "description": "Number of shares"},
                "side": {"type": "string", "enum": ["buy", "sell"], "description": "Order side (default: buy)"},
                "buffer_bps": {"type": "number", "description": "Price buffer in basis points (default: 5.0)"},
            },
            "required": ["ticker", "quantity"],
        },
    },
    {
        "name": "get_nbbo",
        "description": "Get the National Best Bid and Offer (NBBO) for a stock: bid, ask, mid, spread. Cached 500ms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_account_snapshot",
        "description": "Get account snapshot (portfolio value, buying power, cash). Cached 500ms for rapid pre-trade checks.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
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
