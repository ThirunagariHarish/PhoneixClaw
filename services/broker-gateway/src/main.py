"""Broker Gateway — multi-account Robinhood session pool as an HTTP service.

Supports multiple Robinhood accounts loaded from the connectors table,
with lazy authentication, per-account paper mode, and backward-compatible
env-var fallback for legacy single-account usage.

Env vars:
    DATABASE_URL             — PostgreSQL connection string
    CREDENTIAL_ENCRYPTION_KEY — Fernet key for connector credential decryption
    RH_USERNAME              — (legacy) Robinhood email
    RH_PASSWORD              — (legacy) Robinhood password
    RH_TOTP_SECRET           — (legacy) TOTP base32 secret for 2FA
    PAPER_MODE               — "true" to force paper mode globally
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import threading
import time
import uuid as uuid_mod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from shared.utils.circuit_breaker import CircuitBreaker as _CBAsync
from shared.utils.circuit_breaker import CircuitBreakerOpen

from . import rh_client

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("broker-gateway")

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------
RH_USERNAME = os.environ.get("RH_USERNAME", "")
RH_PASSWORD = os.environ.get("RH_PASSWORD", "")
RH_TOTP_SECRET = os.environ.get("RH_TOTP_SECRET", "")
GLOBAL_PAPER_MODE = os.environ.get("PAPER_MODE", "").lower() == "true"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

TOKEN_DIR = Path(os.environ.get("TOKEN_DIR", "/app/data/.tokens"))
SESSION_MAX_AGE_HOURS = 24.0
SESSION_REFRESH_THRESHOLD_HOURS = 20.0

ORDER_POLL_INTERVAL = 2.0
ORDER_POLL_TIMEOUT = 30.0
RATE_LIMIT_SECONDS = 5.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0

LEGACY_ACCOUNT_ID = "legacy"

_AUTH_ERROR_KEYWORDS = ("401", "unauthorized", "unauthenticated")


# ---------------------------------------------------------------------------
# Rate limiter
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
                time.sleep(wait)
            self._last = time.monotonic()


_order_limiter = _RateLimiter(RATE_LIMIT_SECONDS)

_rh_circuit = _CBAsync(
    name="robinhood",
    failure_threshold=5,
    cooldown_seconds=60,
    half_open_max_calls=2,
)


# ---------------------------------------------------------------------------
# Robinhood session dataclass
# ---------------------------------------------------------------------------
@dataclass
class RobinhoodSession:
    account_id: str
    username: str
    password: str
    totp_secret: str = ""
    paper_mode: bool = False
    logged_in: bool = False
    login_time: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    paper_orders: dict[str, dict] = field(default_factory=dict)
    paper_positions: dict[str, dict] = field(default_factory=dict)
    paper_cash: float = 100_000.00
    paper_watchlists: dict[str, list[str]] = field(default_factory=dict)

    def session_age_hours(self) -> float:
        if not self.login_time:
            return 0.0
        return (time.time() - self.login_time) / 3600.0

    def needs_refresh(self) -> bool:
        return self.logged_in and self.session_age_hours() >= SESSION_REFRESH_THRESHOLD_HOURS


# ---------------------------------------------------------------------------
# Session pool
# ---------------------------------------------------------------------------
_sessions: dict[str, RobinhoodSession] = {}
_sessions_lock = threading.Lock()


def _get_session(account_id: str) -> RobinhoodSession:
    with _sessions_lock:
        session = _sessions.get(account_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found. Load connectors first.")
    return session


def _resolve_account_id(account_id: str | None) -> str:
    """Resolve account_id with legacy fallback."""
    if account_id:
        return account_id
    if LEGACY_ACCOUNT_ID in _sessions:
        return LEGACY_ACCOUNT_ID
    with _sessions_lock:
        ids = list(_sessions.keys())
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise HTTPException(status_code=400, detail="No accounts configured. Set RH_USERNAME or load connectors.")
    raise HTTPException(status_code=400, detail="Multiple accounts configured — account_id is required.")


# ---------------------------------------------------------------------------
# robin_stocks accessor
# ---------------------------------------------------------------------------
_rh_module: Any = None


def _get_rh() -> Any:
    global _rh_module
    if _rh_module is None:
        import robin_stocks.robinhood as rh
        _rh_module = rh
    return _rh_module


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------
def _retry(fn: Any, *args: Any, session: RobinhoodSession | None = None, **kwargs: Any) -> Any:
    """Sync retry wrapper with circuit breaker. Blocks caller thread."""
    cb_state = _rh_circuit.state
    if cb_state == _CBAsync.OPEN:
        remaining = max(0, _rh_circuit.cooldown_seconds - (time.monotonic() - _rh_circuit._last_failure_time))
        raise CircuitBreakerOpen(_rh_circuit.name, _rh_circuit._failure_count, remaining)

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = fn(*args, **kwargs)
            _rh_circuit._on_success()
            return result
        except Exception as exc:
            last_exc = exc
            err_str = str(exc).lower()
            if any(kw in err_str for kw in _AUTH_ERROR_KEYWORDS) and session:
                session.logged_in = False
                log.warning("Auth error for %s on attempt %d — session marked for renewal", session.account_id, attempt)
                if attempt == 1 and not session.paper_mode:
                    try:
                        _do_login(session)
                    except Exception as reauth_exc:
                        log.warning("Re-auth failed during retry for %s: %s", session.account_id, reauth_exc)
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            log.warning("Retry %d/%d after error: %s (backoff %.1fs)", attempt, MAX_RETRIES, exc, wait)
            time.sleep(wait)
    _rh_circuit._on_failure()
    raise last_exc  # type: ignore[misc]


async def _async_retry(fn: Any, *args: Any, session: RobinhoodSession | None = None, **kwargs: Any) -> Any:
    """Async wrapper around _retry. Offloads blocking call to thread pool."""
    return await asyncio.to_thread(_retry, fn, *args, session=session, **kwargs)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _ensure_token_dir() -> None:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        TOKEN_DIR.chmod(0o700)
    except OSError:
        pass


def _do_login(session: RobinhoodSession) -> None:
    """Perform robin_stocks login with 30s timeout and pickle invalidation on failure."""
    if session.paper_mode:
        session.logged_in = True
        rh_client.reset_auth_fail_count()
        return

    if not session.username or not session.password:
        raise ValueError(f"Robinhood credentials missing for account {session.account_id}")

    # Check backoff before attempting
    try:
        rh_client.check_backoff()
    except RuntimeError as exc:
        log.warning("Login skipped for %s: %s", session.account_id, exc)
        raise

    rh = _get_rh()
    _ensure_token_dir()
    os.environ["HOME"] = str(TOKEN_DIR.parent)

    pickle_name = f"phoenix_{session.account_id}_{session.username.split('@')[0]}"

    mfa_code: str | None = None
    if session.totp_secret:
        try:
            import pyotp
            mfa_code = pyotp.TOTP(session.totp_secret).now()
            log.info("Generated TOTP code for %s (%s)", session.account_id, session.username)
        except Exception as exc:
            log.warning("TOTP generation failed for %s: %s", session.account_id, exc)

    # Hard 30s login timeout via thread-pool future. Replaces SIGALRM
    # (process-global, not thread-safe — multi-account login can race).
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout

    def _do_login(use_mfa: bool) -> None:
        kwargs = {
            "store_session": True,
            "expiresIn": 86400,
            "pickle_name": pickle_name,
        }
        if use_mfa and mfa_code:
            kwargs["mfa_code"] = mfa_code
        rh.login(session.username, session.password, **kwargs)

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(_do_login, True).result(timeout=30)
    except _FuturesTimeout:
        log.error("Login timeout for %s after 30s — invalidating pickle", session.account_id)
        rh_client.invalidate_session_pickle(pickle_name)
        rh_client.record_auth_fail()
        raise TimeoutError("rh.login exceeded 30s")
    except Exception as first_err:
        if mfa_code:
            log.warning("Login with TOTP failed for %s (%s), retrying without MFA", session.account_id, first_err)
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    ex.submit(_do_login, False).result(timeout=30)
            except Exception:
                rh_client.invalidate_session_pickle(pickle_name)
                rh_client.record_auth_fail()
                raise first_err
        else:
            rh_client.invalidate_session_pickle(pickle_name)
            rh_client.record_auth_fail()
            raise

    session.logged_in = True
    session.login_time = time.time()
    rh_client.reset_auth_fail_count()
    log.info("Logged in to Robinhood for account %s (%s)", session.account_id, session.username)


def _ensure_login(session: RobinhoodSession) -> None:
    if session.paper_mode:
        session.logged_in = True
        return
    if session.logged_in:
        return
    with session.lock:
        if session.logged_in:
            return
        _do_login(session)


# ---------------------------------------------------------------------------
# DB connector loading
# ---------------------------------------------------------------------------
def _load_connectors_from_db() -> list[RobinhoodSession]:
    """Load active Robinhood connectors from PostgreSQL."""
    if not DATABASE_URL:
        log.info("DATABASE_URL not set — skipping connector loading")
        return []

    try:
        from sqlalchemy import create_engine, text

        from shared.crypto.credentials import decrypt_credentials
    except ImportError as exc:
        log.warning("Cannot load connectors — missing dependency: %s", exc)
        return []

    sync_url = DATABASE_URL
    if sync_url.startswith("postgresql+asyncpg://"):
        sync_url = sync_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    engine = create_engine(sync_url, pool_pre_ping=True)
    sessions: list[RobinhoodSession] = []

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, credentials_encrypted, config, is_active "
                    "FROM connectors WHERE type = :ctype AND is_active = true"
                ),
                {"ctype": "robinhood"},
            ).fetchall()

        for row in rows:
            connector_id = str(row[0])
            creds_encrypted = row[1]
            config = row[2] or {}
            if isinstance(config, str):
                config = json.loads(config)

            if not creds_encrypted:
                log.warning("Connector %s has no encrypted credentials — skipping", connector_id)
                continue

            try:
                creds = decrypt_credentials(creds_encrypted)
            except Exception as exc:
                log.error("Failed to decrypt credentials for connector %s: %s", connector_id, exc)
                continue

            paper = GLOBAL_PAPER_MODE or bool(config.get("paper_mode", False))
            sessions.append(RobinhoodSession(
                account_id=connector_id,
                username=creds.get("username", ""),
                password=creds.get("password", ""),
                totp_secret=creds.get("totp_secret", ""),
                paper_mode=paper,
            ))
            log.info("Loaded connector %s (user=%s, paper=%s)", connector_id, creds.get("username", "?"), paper)

    except Exception as exc:
        log.error("Failed to load connectors from DB: %s", exc)
    finally:
        engine.dispose()

    return sessions


def _init_sessions() -> None:
    """Initialize the session pool from DB connectors and env-var fallback."""
    db_sessions = _load_connectors_from_db()
    with _sessions_lock:
        for s in db_sessions:
            _sessions[s.account_id] = s

        if RH_USERNAME and LEGACY_ACCOUNT_ID not in _sessions:
            legacy_paper = GLOBAL_PAPER_MODE or not RH_USERNAME
            _sessions[LEGACY_ACCOUNT_ID] = RobinhoodSession(
                account_id=LEGACY_ACCOUNT_ID,
                username=RH_USERNAME,
                password=RH_PASSWORD,
                totp_secret=RH_TOTP_SECRET,
                paper_mode=legacy_paper,
            )
            log.info("Legacy env-var session registered (user=%s, paper=%s)", RH_USERNAME, legacy_paper)

        if not _sessions and not RH_USERNAME:
            log.info("No accounts configured — running in global paper mode")
            _sessions[LEGACY_ACCOUNT_ID] = RobinhoodSession(
                account_id=LEGACY_ACCOUNT_ID,
                username="",
                password="",
                paper_mode=True,
            )


# ---------------------------------------------------------------------------
# Paper-mode helpers
# ---------------------------------------------------------------------------
def _paper_fill_price(price: float) -> float:
    slippage = random.uniform(0.01, 0.05)
    return round(price + random.choice([-1, 1]) * slippage, 4)


def _paper_place_order(
    session: RobinhoodSession,
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
    fill = _paper_fill_price(price)
    oid = str(uuid_mod.uuid4())
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
    session.paper_orders[oid] = order

    cost = fill * quantity
    if side == "buy":
        session.paper_cash -= cost
        pos = session.paper_positions.get(ticker, {"quantity": 0.0, "avg_cost": 0.0})
        total_qty = pos["quantity"] + quantity
        pos["avg_cost"] = round(
            (pos["avg_cost"] * pos["quantity"] + fill * quantity) / total_qty, 4
        ) if total_qty else 0.0
        pos["quantity"] = total_qty
        session.paper_positions[ticker] = pos
    else:
        session.paper_cash += cost
        pos = session.paper_positions.get(ticker)
        if pos:
            pos["quantity"] = max(0.0, pos["quantity"] - quantity)
            if pos["quantity"] == 0:
                session.paper_positions.pop(ticker, None)

    return order


# ---------------------------------------------------------------------------
# Order polling
# ---------------------------------------------------------------------------
def _poll_order_status(order_id: str, session: RobinhoodSession, *, is_option: bool = False) -> dict:
    if session.paper_mode:
        order = session.paper_orders.get(order_id, {})
        return {"order_id": order_id, "state": order.get("state", "unknown"), "fill_price": order.get("fill_price")}

    rh = _get_rh()
    terminal_states = ("filled", "cancelled", "failed", "rejected")
    deadline = time.monotonic() + ORDER_POLL_TIMEOUT

    def _get_info() -> Any:
        if is_option:
            try:
                return _retry(rh.orders.get_option_order_info, order_id, session=session)
            except Exception:
                return _retry(rh.orders.get_stock_order_info, order_id, session=session)
        return _retry(rh.orders.get_stock_order_info, order_id, session=session)

    while time.monotonic() < deadline:
        info = _get_info()
        state = info.get("state", "unknown")
        if state in terminal_states:
            return {
                "order_id": order_id,
                "state": state,
                "fill_price": info.get("average_price") or info.get("price"),
                "filled_quantity": info.get("cumulative_quantity") or info.get("processed_quantity"),
            }
        time.sleep(ORDER_POLL_INTERVAL)

    info = _get_info()
    return {
        "order_id": order_id,
        "state": "timed_out",
        "broker_state": info.get("state", "unknown"),
        "fill_price": info.get("average_price") or info.get("price"),
        "timed_out": True,
    }


# ---------------------------------------------------------------------------
# Session refresh background task
# ---------------------------------------------------------------------------
async def _auto_refresh_loop() -> None:
    """Background task: refresh sessions every 15 min to keep them warm."""
    while True:
        await asyncio.sleep(rh_client.REFRESH_INTERVAL_S)
        with _sessions_lock:
            sessions_snapshot = list(_sessions.values())

        for session in sessions_snapshot:
            if session.paper_mode or not session.logged_in:
                continue
            if session.needs_refresh():
                log.info(
                    "Session %s age %.1fh exceeds threshold — refreshing",
                    session.account_id,
                    session.session_age_hours(),
                )
                pickle_name = f"phoenix_{session.account_id}_{session.username.split('@')[0]}"
                try:
                    await rh_client.refresh_session_light(session.username, pickle_name)
                    session.login_time = time.time()  # Update timestamp on successful refresh
                    log.info("Session %s refreshed successfully", session.account_id)
                except Exception as exc:
                    log.error("Session %s refresh failed: %s", session.account_id, exc)
                    session.logged_in = False  # Force re-login on next request
                    rh_client.record_auth_fail()


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------
class StockOrderRequest(BaseModel):
    ticker: str
    quantity: float
    side: str = Field(pattern="^(buy|sell)$")
    order_type: str = "limit"
    price: float
    account_id: str | None = None


class OptionOrderRequest(BaseModel):
    ticker: str
    strike: float
    expiry: str
    option_type: str = Field(pattern="^(call|put)$")
    side: str = Field(pattern="^(buy|sell)$")
    quantity: int
    price: float
    account_id: str | None = None


class WatchlistAddRequest(BaseModel):
    ticker: str
    watchlist_name: str = "Phoenix Paper"
    account_id: str | None = None


class LoginRequest(BaseModel):
    account_id: str | None = None


class OptionOrderByContractRequest(BaseModel):
    """Option order using contract_id URL instead of strike/expiry/type."""
    contract_id: str = Field(description="Robinhood option instrument URL")
    quantity: int
    side: str = Field(pattern="^(buy|sell)$")
    price: float
    time_in_force: str = "gfd"
    account_id: str | None = None


class OptionWatchlistAddRequest(BaseModel):
    ticker: str
    expiry: str = Field(description="YYYY-MM-DD")
    strike: float
    option_type: str = Field(pattern="^(call|put)$")
    watchlist_name: str = "Options Watchlist"
    account_id: str | None = None


class WatchlistRemoveRequest(BaseModel):
    ticker: str = Field(description="Stock ticker or option contract identifier")
    watchlist_name: str = "Phoenix Paper"
    account_id: str | None = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
_refresh_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    global _refresh_task
    log.info("Broker Gateway starting (global_paper_mode=%s)", GLOBAL_PAPER_MODE)

    await asyncio.get_event_loop().run_in_executor(None, _init_sessions)

    with _sessions_lock:
        count = len(_sessions)
    log.info("Session pool initialized with %d account(s)", count)

    _refresh_task = asyncio.create_task(_auto_refresh_loop())
    yield
    if _refresh_task:
        _refresh_task.cancel()
    log.info("Broker Gateway shutting down")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Phoenix Broker Gateway", version="2.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    with _sessions_lock:
        accounts = {
            aid: {"paper_mode": s.paper_mode, "authenticated": s.logged_in}
            for aid, s in _sessions.items()
        }
    return {"status": "ok", "global_paper_mode": GLOBAL_PAPER_MODE, "accounts": accounts}


@app.post("/auth/login")
async def auth_login(req: LoginRequest | None = None):
    account_id = req.account_id if req else None
    if account_id:
        session = _get_session(account_id)
    else:
        aid = _resolve_account_id(None)
        session = _get_session(aid)

    if session.paper_mode:
        session.logged_in = True
        return {"authenticated": True, "paper_mode": True, "account_id": session.account_id}

    session.logged_in = False
    try:
        await asyncio.get_event_loop().run_in_executor(None, _ensure_login, session)
        return {"authenticated": True, "paper_mode": False, "account_id": session.account_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/auth/status")
async def auth_status(account_id: str | None = Query(default=None)):
    if account_id:
        session = _get_session(account_id)
        return {
            "account_id": session.account_id,
            "authenticated": session.logged_in,
            "paper_mode": session.paper_mode,
            "session_age_hours": round(session.session_age_hours(), 1),
        }
    with _sessions_lock:
        result = []
        for s in _sessions.values():
            result.append({
                "account_id": s.account_id,
                "authenticated": s.logged_in,
                "paper_mode": s.paper_mode,
                "session_age_hours": round(s.session_age_hours(), 1),
            })
    return {"accounts": result}


@app.post("/orders/stock")
async def place_stock_order(req: StockOrderRequest):
    aid = _resolve_account_id(req.account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)
        _order_limiter.acquire()

        if session.paper_mode:
            order = _paper_place_order(session, req.ticker, req.quantity, req.side, req.price, req.order_type)
            return {
                "order_id": order["id"],
                "state": order["state"],
                "fill_price": order["fill_price"],
                "paper_mode": True,
                "account_id": session.account_id,
            }

        rh = _get_rh()
        if req.side == "buy":
            order = _retry(rh.orders.order_buy_limit, req.ticker, req.quantity, req.price, session=session)
        else:
            order = _retry(rh.orders.order_sell_limit, req.ticker, req.quantity, req.price, session=session)

        oid = order.get("id", "")
        if oid:
            result = _poll_order_status(oid, session)
            result["account_id"] = session.account_id
            # Audit log
            rh_client._audit(
                "order_placed",
                account_id=session.account_id,
                ticker=req.ticker,
                side=req.side,
                qty=req.quantity,
                price=req.price,
                order_id=oid,
                state=result.get("state"),
            )
            return result
        return {"order_id": oid, "state": order.get("state", "unknown"), "account_id": session.account_id}

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/orders/option")
async def place_option_order(req: OptionOrderRequest):
    aid = _resolve_account_id(req.account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)
        _order_limiter.acquire()

        if session.paper_mode:
            order = _paper_place_order(
                session, req.ticker, req.quantity, req.side, req.price,
                option_type=req.option_type, strike=req.strike, expiry=req.expiry,
            )
            return {
                "order_id": order["id"],
                "state": order["state"],
                "fill_price": order["fill_price"],
                "paper_mode": True,
                "account_id": session.account_id,
            }

        rh = _get_rh()
        pos_effect = "open" if req.side == "buy" else "close"
        fn = rh.orders.order_buy_option_limit if req.side == "buy" else rh.orders.order_sell_option_limit
        order = _retry(
            fn, pos_effect, req.ticker, req.quantity, req.price, req.expiry, req.strike, req.option_type,
            session=session,
        )

        oid = order.get("id", "")
        if oid:
            result = _poll_order_status(oid, session, is_option=True)
            result["account_id"] = session.account_id
            # Audit log
            rh_client._audit(
                "option_order_placed",
                account_id=session.account_id,
                ticker=req.ticker,
                side=req.side,
                strike=req.strike,
                expiry=req.expiry,
                option_type=req.option_type,
                qty=req.quantity,
                price=req.price,
                order_id=oid,
                state=result.get("state"),
            )
            return result
        return {"order_id": oid, "state": order.get("state", "unknown"), "account_id": session.account_id}

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/positions")
async def get_positions(account_id: str | None = Query(default=None)):
    aid = _resolve_account_id(account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)

        if session.paper_mode:
            return {
                "positions": [{"ticker": t, **p} for t, p in session.paper_positions.items()],
                "paper_mode": True,
                "account_id": session.account_id,
            }

        rh = _get_rh()
        positions = _retry(rh.account.get_open_stock_positions, session=session)
        result = []
        for p in positions:
            instr = _retry(rh.stocks.get_instrument_by_url, p["instrument"], session=session)
            result.append({
                "ticker": instr.get("symbol", "?"),
                "quantity": float(p["quantity"]),
                "avg_cost": float(p["average_buy_price"]),
                "current_price": float(p.get("last_trade_price", 0) or 0),
            })
        return {"positions": result, "account_id": session.account_id}

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/watchlist")
async def add_to_watchlist(req: WatchlistAddRequest):
    aid = _resolve_account_id(req.account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)

        if session.paper_mode:
            wl = session.paper_watchlists.setdefault(req.watchlist_name, [])
            if req.ticker not in wl:
                wl.append(req.ticker)
            return {
                "status": "added",
                "ticker": req.ticker,
                "watchlist_name": req.watchlist_name,
                "paper_mode": True,
                "account_id": session.account_id,
            }

        rh = _get_rh()
        result = _retry(rh.account.post_symbols_to_watchlist, [req.ticker], req.watchlist_name, session=session)
        rh_client._audit(
            "watchlist_add_stock",
            account_id=session.account_id,
            ticker=req.ticker,
            watchlist=req.watchlist_name,
        )
        return {
            "status": "added",
            "ticker": req.ticker,
            "watchlist_name": req.watchlist_name,
            "result": result,
            "account_id": session.account_id,
        }

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/watchlist")
async def get_watchlist(
    name: str = Query(default="Phoenix Paper"),
    account_id: str | None = Query(default=None),
):
    aid = _resolve_account_id(account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)

        if session.paper_mode:
            symbols = session.paper_watchlists.get(name, [])
            return {
                "watchlist_name": name,
                "symbols": symbols,
                "count": len(symbols),
                "paper_mode": True,
                "account_id": session.account_id,
            }

        rh = _get_rh()
        items = _retry(rh.account.get_watchlist_by_name, name, session=session)
        symbols = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    sym = item.get("symbol") or (item.get("instrument", {}) or {}).get("symbol")
                    if sym:
                        symbols.append(sym)
        return {
            "watchlist_name": name,
            "symbols": symbols,
            "count": len(symbols),
            "account_id": session.account_id,
        }

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/account")
async def get_account(account_id: str | None = Query(default=None)):
    aid = _resolve_account_id(account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)

        if session.paper_mode:
            total = session.paper_cash + sum(
                p["quantity"] * p["avg_cost"] for p in session.paper_positions.values()
            )
            return {
                "portfolio_value": round(total, 2),
                "buying_power": round(session.paper_cash, 2),
                "paper_mode": True,
                "account_id": session.account_id,
            }

        rh = _get_rh()
        profile = _retry(rh.profiles.load_portfolio_profile, session=session)
        account = _retry(rh.profiles.load_account_profile, session=session)
        return {
            "portfolio_value": float(profile.get("equity", 0)),
            "buying_power": float(account.get("buying_power", 0)),
            "cash": float(account.get("cash", 0)),
            "account_id": session.account_id,
        }

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# New endpoints (ported from SelfAgentBot)
# ---------------------------------------------------------------------------


@app.post("/orders/option/contract")
async def place_option_order_by_contract(req: OptionOrderByContractRequest):
    """Place option order using contract_id URL instead of strike/expiry/type triple.

    Modern path that agents should prefer when they already have the contract URL
    from a previous option chain lookup.
    """
    aid = _resolve_account_id(req.account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)
        _order_limiter.acquire()

        if session.paper_mode:
            oid = f"paper-opt-contract-{uuid_mod.uuid4().hex[:12]}"
            return {
                "order_id": oid,
                "state": "filled",
                "paper_mode": True,
                "account_id": session.account_id,
            }

        rh = _get_rh()
        pos_effect = "open" if req.side == "buy" else "close"
        price_effect = "debit" if req.side == "buy" else "credit"

        # robin_stocks option-by-id helpers take the contract URL
        if req.side == "buy":
            order = _retry(
                rh.orders.order_buy_option_limit,
                pos_effect,
                price_effect,
                req.price,
                req.contract_id,
                req.quantity,
                "", 0.0, "",  # Empty strike/expiry/type — contract_id is enough
                timeInForce=req.time_in_force,
                session=session,
            )
        else:
            order = _retry(
                rh.orders.order_sell_option_limit,
                pos_effect,
                price_effect,
                req.price,
                req.contract_id,
                req.quantity,
                "", 0.0, "",
                timeInForce=req.time_in_force,
                session=session,
            )

        oid = order.get("id", "")
        if oid:
            result = _poll_order_status(oid, session, is_option=True)
            result["account_id"] = session.account_id
            rh_client._audit(
                "option_order_by_contract",
                account_id=session.account_id,
                contract_id=req.contract_id,
                side=req.side,
                qty=req.quantity,
                price=req.price,
                order_id=oid,
                state=result.get("state"),
            )
            return result
        return {"order_id": oid, "state": order.get("state", "unknown"), "account_id": session.account_id}

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/orders")
async def get_orders(
    status: str = Query(default="all", description="all, open, filled, or cancelled"),
    order_type: str = Query(default="all", description="all, stock, or option"),
    account_id: str | None = Query(default=None),
):
    """List recent orders with optional status and type filters."""
    aid = _resolve_account_id(account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)

        if session.paper_mode:
            orders = list(session.paper_orders.values())
            if status.lower() == "open":
                orders = [o for o in orders if o.get("state") in ("queued", "confirmed", "partially_filled")]
            elif status.lower() == "filled":
                orders = [o for o in orders if o.get("state") == "filled"]
            return {"orders": orders, "paper_mode": True, "account_id": session.account_id}

        rh = _get_rh()
        result = []

        if order_type.lower() in ("all", "option"):
            try:
                raw_options = _retry(rh.orders.get_all_option_orders, session=session)
            except Exception:
                raw_options = []
            for entry in raw_options or []:
                if not isinstance(entry, dict):
                    continue
                state = str(entry.get("state", "unknown"))
                if status.lower() == "open" and state not in ("queued", "confirmed", "partially_filled"):
                    continue
                if status.lower() == "filled" and state != "filled":
                    continue
                result.append({
                    "order_id": entry.get("id", ""),
                    "symbol": entry.get("chain_symbol", ""),
                    "side": entry.get("direction", "unknown"),
                    "quantity": float(entry.get("quantity") or 0),
                    "price": entry.get("price"),
                    "state": state,
                    "asset_class": "option",
                    "created_at": entry.get("created_at"),
                })

        if order_type.lower() in ("all", "stock"):
            try:
                raw_stocks = _retry(rh.orders.get_all_stock_orders, session=session)
            except Exception:
                raw_stocks = []
            for entry in raw_stocks or []:
                if not isinstance(entry, dict):
                    continue
                state = str(entry.get("state", "unknown"))
                if status.lower() == "open" and state not in ("queued", "confirmed", "partially_filled"):
                    continue
                if status.lower() == "filled" and state != "filled":
                    continue
                result.append({
                    "order_id": entry.get("id", ""),
                    "symbol": entry.get("symbol", ""),
                    "side": entry.get("side", "unknown"),
                    "quantity": float(entry.get("quantity") or 0),
                    "price": entry.get("price"),
                    "state": state,
                    "asset_class": "stock",
                    "created_at": entry.get("created_at"),
                })

        return {"orders": result, "account_id": session.account_id}

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/quotes")
async def get_quotes(
    tickers: str = Query(description="Comma-separated tickers, e.g. AAPL,MSFT"),
    account_id: str | None = Query(default=None),
):
    """Bulk stock quotes (bid, ask, last, prev_close, day_pct)."""
    aid = _resolve_account_id(account_id)
    session = _get_session(aid)
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    if not ticker_list:
        raise HTTPException(status_code=400, detail="No tickers provided")

    def _execute() -> dict:
        _ensure_login(session)

        if session.paper_mode:
            # Synthetic quotes for paper mode
            quotes = {
                t: {
                    "bid": 99.95,
                    "ask": 100.05,
                    "last": 100.0,
                    "prev_close": 99.0,
                    "day_pct": 1.01,
                }
                for t in ticker_list
            }
            return {"quotes": quotes, "paper_mode": True, "account_id": session.account_id}

        rh = _get_rh()
        try:
            raw = _retry(rh.stocks.get_quotes, ticker_list, session=session)
        except Exception:
            raw = []

        quotes = {}
        for entry in raw or []:
            if not isinstance(entry, dict):
                continue
            try:
                sym = str(entry.get("symbol", "")).upper()
                if not sym:
                    continue
                last = float(entry.get("last_trade_price") or entry.get("last_extended_hours_trade_price") or 0.0)
                prev = float(entry.get("previous_close") or 0.0)
                bid = float(entry.get("bid_price") or 0.0)
                ask = float(entry.get("ask_price") or 0.0)
                day_pct = ((last - prev) / prev * 100.0) if prev else 0.0
                quotes[sym] = {
                    "bid": bid,
                    "ask": ask,
                    "last": last,
                    "prev_close": prev,
                    "day_pct": round(day_pct, 2),
                }
            except Exception:
                continue

        # Fill missing tickers with zeros
        for t in ticker_list:
            if t not in quotes:
                quotes[t] = {"bid": 0.0, "ask": 0.0, "last": 0.0, "prev_close": 0.0, "day_pct": 0.0}

        return {"quotes": quotes, "account_id": session.account_id}

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/watchlist/option")
async def add_option_to_watchlist(req: OptionWatchlistAddRequest):
    """Add option contract to watchlist via RH quick_add API.

    Discovers contract from ticker/expiry/strike/type and posts to
    /discovery/lists/items/quick_add/. Auto-targets "Options Watchlist".
    """
    aid = _resolve_account_id(req.account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)

        if session.paper_mode:
            wl_key = f"{req.watchlist_name}_options"
            wl = session.paper_watchlists.setdefault(wl_key, [])
            contract_sig = f"{req.ticker} {req.option_type} ${req.strike} {req.expiry}"
            if contract_sig not in wl:
                wl.append(contract_sig)
            return {
                "status": "added",
                "contract": contract_sig,
                "watchlist_name": req.watchlist_name,
                "paper_mode": True,
                "account_id": session.account_id,
            }

        rh = _get_rh()
        # Discover contract
        chain = _retry(
            rh.options.find_options_by_strike,
            inputSymbols=req.ticker,
            strikePrice=req.strike,
            optionType=req.option_type.lower(),
            session=session,
        )
        contracts = [c for c in (chain or []) if c.get("expiration_date") == req.expiry]
        if not contracts:
            raise HTTPException(
                status_code=404,
                detail=f"No contract found for {req.ticker} {req.option_type} ${req.strike} {req.expiry}",
            )

        contract = contracts[0]
        contract_id = contract["id"]

        # POST quick_add
        url = "https://api.robinhood.com/discovery/lists/items/quick_add/"
        body = {
            "legs": [{
                "option_id": contract_id,
                "position_type": "long",
                "ratio_quantity": 1,
            }],
            "object_type": "option_strategy",
        }

        # Use robin_stocks helper for authenticated POST
        from robin_stocks.robinhood.helper import request_post
        resp = _retry(request_post, url, body, json=True, session=session)

        if not isinstance(resp, dict):
            raise HTTPException(status_code=500, detail=f"Unexpected RH response: {resp!r}")
        if "failed operations" in resp or "detail" in resp:
            raise HTTPException(
                status_code=400,
                detail=f"RH quick_add rejected: {resp.get('failed operations') or resp.get('detail')}",
            )

        rh_client._audit(
            "watchlist_add_option",
            account_id=session.account_id,
            ticker=req.ticker,
            strike=req.strike,
            expiry=req.expiry,
            option_type=req.option_type,
            contract_id=contract_id,
        )

        return {
            "status": "added",
            "contract_id": contract_id,
            "watchlist_name": req.watchlist_name,
            "account_id": session.account_id,
        }

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/watchlist/{ticker}")
async def remove_from_watchlist(
    ticker: str,
    watchlist_name: str = Query(default="Phoenix Paper"),
    account_id: str | None = Query(default=None),
):
    """Remove a stock ticker from a named watchlist."""
    aid = _resolve_account_id(account_id)
    session = _get_session(aid)

    def _execute() -> dict:
        _ensure_login(session)

        if session.paper_mode:
            wl = session.paper_watchlists.get(watchlist_name, [])
            if ticker.upper() in wl:
                wl.remove(ticker.upper())
            return {
                "status": "removed",
                "ticker": ticker,
                "watchlist_name": watchlist_name,
                "paper_mode": True,
                "account_id": session.account_id,
            }

        rh = _get_rh()
        try:
            result = _retry(
                rh.account.delete_symbols_from_watchlist,
                ticker.upper(),
                watchlist_name,
                session=session,
            )
            rh_client._audit(
                "watchlist_remove_stock",
                account_id=session.account_id,
                ticker=ticker,
                watchlist=watchlist_name,
            )
            return {
                "status": "removed",
                "ticker": ticker,
                "watchlist_name": watchlist_name,
                "account_id": session.account_id,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        return await asyncio.to_thread(_execute)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
