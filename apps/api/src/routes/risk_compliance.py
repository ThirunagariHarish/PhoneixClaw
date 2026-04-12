"""
Risk Compliance API routes: status, position-limits, checks, compliance, hedging.

Phoenix v3 — Live risk data from DB positions, agent metrics, and circuit breaker state.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.agent_trade import AgentTrade

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/risk", tags=["risk-compliance"])

# Default risk limits (can be overridden per-agent via config)
DEFAULT_MAX_DAILY_LOSS_PCT = -5.0
DEFAULT_MAX_POSITION_PCT = 10.0
DEFAULT_MAX_SECTOR_PCT = 30.0
DEFAULT_MAX_CONCURRENT = 5

# In-memory risk config store (persisted via save/load endpoint)
_risk_config: dict = {
    "max_daily_loss_pct": abs(DEFAULT_MAX_DAILY_LOSS_PCT),
    "max_sector_exposure_pct": DEFAULT_MAX_SECTOR_PCT,
    "max_position_pct": DEFAULT_MAX_POSITION_PCT,
    "max_concurrent": DEFAULT_MAX_CONCURRENT,
}

# In-memory circuit breaker state (persisted across requests)
_circuit_breaker_state: dict = {
    "state": "NORMAL",
    "triggered_at": None,
    "reason": None,
    "consecutive_losses": 0,
}

# Sector mapping cache
_sector_cache: dict[str, str] = {}


def _get_sector(ticker: str) -> str:
    """Get sector for a ticker using yfinance, with caching."""
    if ticker in _sector_cache:
        return _sector_cache[ticker]
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        sector = info.get("sector", "Unknown")
        _sector_cache[ticker] = sector
        return sector
    except Exception:
        _sector_cache[ticker] = "Unknown"
        return "Unknown"


@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_session)) -> dict:
    """Overall risk status from agent metrics and trades."""
    today_start = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)

    # Get today's aggregate P&L across all agents
    result = await db.execute(
        select(
            func.sum(AgentTrade.pnl_dollar).label("total_pnl"),
            func.count(AgentTrade.id).label("trade_count"),
        )
        .where(AgentTrade.entry_time >= today_start)
    )
    row = result.first()
    daily_pnl = float(row.total_pnl or 0) if row else 0
    trade_count = row.trade_count or 0 if row else 0

    # Open positions count
    open_result = await db.execute(
        select(func.count(AgentTrade.id)).where(AgentTrade.status == "open")
    )
    open_positions = open_result.scalar() or 0

    # Count consecutive losses for circuit breaker proxy
    recent_trades = await db.execute(
        select(AgentTrade.pnl_dollar)
        .where(AgentTrade.status == "closed")
        .where(AgentTrade.pnl_dollar.isnot(None))
        .order_by(AgentTrade.exit_time.desc())
        .limit(20)
    )
    recent_pnls = [r[0] for r in recent_trades.all()]
    consecutive_losses = 0
    for pnl in recent_pnls:
        if pnl < 0:
            consecutive_losses += 1
        else:
            break

    # Update circuit breaker state
    circuit_state = _circuit_breaker_state["state"]
    threshold = _risk_config["max_daily_loss_pct"]
    if circuit_state == "NORMAL":
        if consecutive_losses >= 5 or daily_pnl < -threshold * 100:
            _circuit_breaker_state["state"] = "TRIGGERED"
            _circuit_breaker_state["triggered_at"] = datetime.now(timezone.utc).isoformat()
            reason = "Consecutive losses" if consecutive_losses >= 5 else "Daily loss threshold"
            _circuit_breaker_state["reason"] = reason
            _circuit_breaker_state["consecutive_losses"] = consecutive_losses
            circuit_state = "TRIGGERED"
        elif consecutive_losses >= 3:
            circuit_state = "WARNING"

    return {
        "dailyPnl": round(daily_pnl, 2),
        "tradesToday": trade_count,
        "openPositions": open_positions,
        "consecutiveLosses": consecutive_losses,
        "circuitBreaker": circuit_state,
        "circuit": {
            "state": circuit_state,
            "dailyLoss": round(daily_pnl, 2),
            "thresholdPct": -threshold,
            "consecutiveLosses": consecutive_losses,
            "triggeredAt": _circuit_breaker_state.get("triggered_at"),
            "reason": _circuit_breaker_state.get("reason"),
        },
    }


@router.get("/position-limits")
async def get_position_limits(db: AsyncSession = Depends(get_session)) -> dict:
    """Open position concentration by ticker and sector with yfinance sector mapping."""
    open_trades = await db.execute(
        select(AgentTrade.ticker, AgentTrade.entry_price, AgentTrade.quantity)
        .where(AgentTrade.status == "open")
    )
    rows = open_trades.all()

    # Ticker concentration
    ticker_exposure: dict[str, float] = defaultdict(float)
    total_exposure = 0.0
    for ticker, price, qty in rows:
        value = (price or 0) * (qty or 1)
        ticker_exposure[ticker] += value
        total_exposure += value

    concentration = []
    for ticker, value in sorted(ticker_exposure.items(), key=lambda x: x[1], reverse=True):
        pct = round(value / total_exposure * 100, 1) if total_exposure > 0 else 0
        concentration.append({
            "ticker": ticker,
            "exposure": round(value, 2),
            "pct": pct,
            "limit_pct": _risk_config["max_position_pct"],
            "breached": pct > _risk_config["max_position_pct"],
        })

    # Sector exposure via yfinance
    sector_exposure: dict[str, float] = defaultdict(float)
    for ticker, value in ticker_exposure.items():
        sector = _get_sector(ticker)
        sector_exposure[sector] += value

    max_sector = _risk_config["max_sector_exposure_pct"]
    sectors = []
    for sector_name, value in sorted(sector_exposure.items(), key=lambda x: x[1], reverse=True):
        pct = round(value / total_exposure * 100, 1) if total_exposure > 0 else 0
        sectors.append({
            "name": sector_name,
            "exposure": pct,
            "max": max_sector,
            "breached": pct > max_sector,
            "value": round(value, 2),
        })

    return {
        "tickerConcentration": concentration,
        "sectors": sectors,
        "totalExposure": round(total_exposure, 2),
        "openPositionCount": len(rows),
        "maxConcurrent": _risk_config["max_concurrent"],
        "breached": len(rows) > _risk_config["max_concurrent"],
    }


@router.get("/checks")
async def get_checks(db: AsyncSession = Depends(get_session)) -> list:
    """Recent risk-related agent log entries."""
    from shared.db.models.agent import AgentLog

    result = await db.execute(
        select(AgentLog)
        .where(AgentLog.level.in_(["WARNING", "ERROR"]))
        .order_by(AgentLog.created_at.desc())
        .limit(20)
    )
    logs = result.scalars().all()

    return [
        {
            "id": str(log.id),
            "agent_id": str(log.agent_id),
            "level": log.level,
            "message": log.message,
            "context": log.context or {},
            "timestamp": log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.get("/compliance")
async def get_compliance(db: AsyncSession = Depends(get_session)) -> list:
    """Compliance checks: PDT rule (day trade count in rolling 5 days), wash sale detection."""
    alerts = []
    five_days_ago = datetime.now(timezone.utc) - timedelta(days=5)

    # PDT check: count round-trips in 5 trading days
    result = await db.execute(
        select(func.count(AgentTrade.id))
        .where(AgentTrade.status == "closed")
        .where(AgentTrade.exit_time >= five_days_ago)
        .where(AgentTrade.entry_time >= five_days_ago)
    )
    day_trade_count = result.scalar() or 0

    if day_trade_count >= 3:
        alerts.append({
            "type": "PDT_WARNING",
            "severity": "high" if day_trade_count >= 4 else "medium",
            "message": f"{day_trade_count} day trades in rolling 5 days (PDT limit: 3)",
            "count": day_trade_count,
        })

    # Wash sale check: same ticker bought within 30 days of a loss close
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    loss_result = await db.execute(
        select(AgentTrade.ticker, AgentTrade.exit_time)
        .where(AgentTrade.status == "closed")
        .where(AgentTrade.pnl_dollar < 0)
        .where(AgentTrade.exit_time >= thirty_days_ago)
    )
    loss_tickers = {(r.ticker, r.exit_time) for r in loss_result.all()}

    repurchase_result = await db.execute(
        select(AgentTrade.ticker, AgentTrade.entry_time)
        .where(AgentTrade.entry_time >= thirty_days_ago)
    )
    repurchases = repurchase_result.all()

    wash_sales = set()
    for ticker, entry_time in repurchases:
        for loss_ticker, loss_exit in loss_tickers:
            if ticker == loss_ticker and loss_exit and entry_time:
                delta = (entry_time - loss_exit).days
                if 0 < delta <= 30:
                    wash_sales.add(ticker)

    for ticker in wash_sales:
        alerts.append({
            "type": "WASH_SALE",
            "severity": "medium",
            "message": f"Potential wash sale on {ticker}: repurchased within 30 days of loss",
            "ticker": ticker,
        })

    return alerts


@router.get("/hedging")
async def get_hedging(db: AsyncSession = Depends(get_session)) -> dict:
    """Hedge status from open positions — check for protective puts."""
    open_trades = await db.execute(
        select(AgentTrade)
        .where(AgentTrade.status == "open")
    )
    positions = open_trades.scalars().all()

    # Find protective puts (open put positions where we also have a long stock/call)
    long_tickers = {p.ticker for p in positions if p.side == "buy" and p.option_type != "put"}
    protective_puts = [
        {
            "ticker": p.ticker,
            "strike": p.strike,
            "expiry": p.expiry.isoformat() if p.expiry else None,
            "entry_price": p.entry_price,
        }
        for p in positions
        if p.option_type == "put" and p.ticker in long_tickers
    ]

    return {
        "blackSwanStatus": "ACTIVE" if protective_puts else "INACTIVE",
        "protectivePuts": protective_puts,
        "hedgeCostPct": 0,
        "openPositions": len(positions),
    }


class RiskConfigUpdate(BaseModel):
    max_daily_loss_pct: float | None = None
    max_sector_exposure_pct: float | None = None
    max_position_pct: float | None = None
    max_concurrent: int | None = None


@router.get("/config")
async def get_risk_config() -> dict:
    """Get current risk configuration."""
    return _risk_config.copy()


@router.post("/config")
async def update_risk_config(config: RiskConfigUpdate) -> dict:
    """Save risk configuration thresholds."""
    if config.max_daily_loss_pct is not None:
        _risk_config["max_daily_loss_pct"] = config.max_daily_loss_pct
    if config.max_sector_exposure_pct is not None:
        _risk_config["max_sector_exposure_pct"] = config.max_sector_exposure_pct
    if config.max_position_pct is not None:
        _risk_config["max_position_pct"] = config.max_position_pct
    if config.max_concurrent is not None:
        _risk_config["max_concurrent"] = config.max_concurrent
    return {"status": "saved", "config": _risk_config.copy()}


@router.get("/margin")
async def get_margin() -> dict:
    """Broker margin data — fetch real margin usage if available."""
    margin_data = {
        "marginUsed": 0,
        "marginAvailable": 0,
        "marginUsagePct": 0,
        "buyingPower": 0,
        "source": "unavailable",
    }
    try:
        # Try to get real margin from Robinhood connector
        from services.connector_manager.src.brokers.robinhood import RobinhoodBroker
        broker = RobinhoodBroker()
        account = broker.get_account_info()
        if account:
            margin_used = float(account.get("margin_balances", {}).get("used_margin", 0) or 0)
            margin_available = float(account.get("margin_balances", {}).get("margin_limit", 0) or 0)
            buying_power = float(account.get("buying_power", 0) or 0)
            usage_pct = round(margin_used / margin_available * 100, 1) if margin_available > 0 else 0
            margin_data = {
                "marginUsed": round(margin_used, 2),
                "marginAvailable": round(margin_available, 2),
                "marginUsagePct": usage_pct,
                "buyingPower": round(buying_power, 2),
                "source": "robinhood",
            }
    except Exception as e:
        logger.debug("Failed to fetch margin data: %s", e)

    return margin_data


@router.get("/drawdown")
async def get_drawdown(db: AsyncSession = Depends(get_session)) -> dict:
    """Drawdown % over time computed from equity curve (cumulative P&L)."""
    # Get closed trades ordered by exit time to build equity curve
    result = await db.execute(
        select(AgentTrade.exit_time, AgentTrade.pnl_dollar)
        .where(AgentTrade.status == "closed")
        .where(AgentTrade.pnl_dollar.isnot(None))
        .where(AgentTrade.exit_time.isnot(None))
        .order_by(AgentTrade.exit_time.asc())
    )
    trades = result.all()

    if not trades:
        return {"drawdown": [], "maxDrawdownPct": 0, "currentDrawdownPct": 0}

    # Build equity curve
    equity = 0.0
    peak = 0.0
    drawdown_series = []

    for exit_time, pnl in trades:
        equity += float(pnl or 0)
        if equity > peak:
            peak = equity
        dd_pct = round((equity - peak) / peak * 100, 2) if peak > 0 else 0
        date_str = exit_time.strftime("%Y-%m-%d") if hasattr(exit_time, "strftime") else str(exit_time)[:10]
        drawdown_series.append({
            "date": date_str,
            "equity": round(equity, 2),
            "drawdownPct": dd_pct,
        })

    max_dd = min(d["drawdownPct"] for d in drawdown_series) if drawdown_series else 0
    current_dd = drawdown_series[-1]["drawdownPct"] if drawdown_series else 0

    return {
        "drawdown": drawdown_series,
        "maxDrawdownPct": max_dd,
        "currentDrawdownPct": current_dd,
    }


@router.get("/correlation")
async def get_correlation(db: AsyncSession = Depends(get_session)) -> dict:
    """Pairwise correlation matrix of open positions using recent returns."""
    # Get unique tickers from open positions
    open_result = await db.execute(
        select(AgentTrade.ticker)
        .where(AgentTrade.status == "open")
        .distinct()
    )
    tickers = [r[0] for r in open_result.all() if r[0]]

    if len(tickers) < 2:
        return {"tickers": tickers, "matrix": [], "message": "Need at least 2 positions for correlation"}

    # Limit to 10 tickers
    tickers = tickers[:10]

    try:
        import yfinance as yf

        # Download recent price data
        tickers_str = " ".join(tickers)
        data = yf.download(tickers_str, period="30d", interval="1d", progress=False)

        if data.empty:
            return {"tickers": tickers, "matrix": [], "message": "No price data available"}

        # Compute returns
        if len(tickers) == 1:
            return {"tickers": tickers, "matrix": [[1.0]], "message": "Single ticker"}

        closes = data["Close"]
        if hasattr(closes, "columns"):
            # Filter to tickers that have data
            available = [t for t in tickers if t in closes.columns]
            if len(available) < 2:
                return {"tickers": tickers, "matrix": [], "message": "Insufficient data"}
            returns = closes[available].pct_change().dropna()
        else:
            returns = closes.pct_change().dropna()
            available = tickers[:1]

        if returns.empty or len(returns) < 5:
            return {"tickers": available, "matrix": [], "message": "Insufficient data"}

        # Compute correlation matrix
        corr_matrix = returns.corr()

        # Convert to list of lists, NaN-safe
        matrix = []
        for t1 in available:
            row = []
            for t2 in available:
                val = corr_matrix.loc[t1, t2] if t1 in corr_matrix.index and t2 in corr_matrix.columns else 0
                val_f = float(val) if val == val else 0  # NaN check
                row.append(round(val_f, 3))
            matrix.append(row)

        return {"tickers": available, "matrix": matrix}

    except ImportError:
        logger.error("yfinance or numpy not installed")
        return {"tickers": tickers, "matrix": [], "message": "Dependencies missing"}
    except Exception as e:
        logger.error("Failed to compute correlation: %s", e)
        return {"tickers": tickers, "matrix": [], "message": str(e)}


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker() -> dict:
    """Manual reset of circuit breaker state."""
    _circuit_breaker_state["state"] = "NORMAL"
    _circuit_breaker_state["triggered_at"] = None
    _circuit_breaker_state["reason"] = None
    _circuit_breaker_state["consecutive_losses"] = 0
    return {"status": "reset", "message": "Circuit breaker reset. Agents will resume normal operation."}
