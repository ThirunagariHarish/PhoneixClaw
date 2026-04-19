"""Pre-trade risk validation against DB portfolio state — enhanced with OldProject logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Ticker blacklist from OldProject (high-volatility or problematic tickers)
DEFAULT_TICKER_BLACKLIST = frozenset({"UVXY", "TVIX", "VXX", "SQQQ", "SPXS", "TECS", "FAZ"})


@dataclass
class RiskCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class RiskResult:
    approved: bool
    reason: str
    checks: list[RiskCheck] = field(default_factory=list)


async def check_risk(
    signal: dict,
    prediction: dict,
    agent_id: str,
    config: dict,
    session: AsyncSession,
) -> RiskResult:
    """Validate risk rules against current portfolio state from DB.

    Enhanced with OldProject validation: blacklist, position limits, buying power,
    percentage-sell position lookup.
    """
    # Lazy imports to avoid model loading issues
    from shared.db.models.agent_trade import AgentTrade
    from shared.db.models.trade import TradeIntent

    risk_params = config.get("risk_params", {})
    checks: list[RiskCheck] = []

    # Configuration
    max_positions = risk_params.get("max_concurrent_positions", 5)
    max_daily_loss_pct = risk_params.get("max_daily_loss_pct", 5.0)
    max_position_size_pct = risk_params.get("max_position_size_pct", 10.0)
    max_position_size = risk_params.get("max_position_size", 10)
    max_total_contracts = risk_params.get("max_total_contracts", 50)
    confidence_threshold = risk_params.get("confidence_threshold", 0.6)
    ticker_blacklist = set(risk_params.get("ticker_blacklist", [])) | DEFAULT_TICKER_BLACKLIST

    ticker = signal.get("ticker", "").upper()
    direction = signal.get("direction", "").upper()
    quantity = signal.get("quantity", 1)
    is_percentage = signal.get("is_percentage", False)
    price = signal.get("price", 0.0)
    strike = signal.get("strike")
    expiry = signal.get("expiry")
    option_type = signal.get("option_type")

    # 1. Ticker blacklist (OldProject pattern)
    blacklist_ok = ticker not in ticker_blacklist
    checks.append(RiskCheck(
        name="ticker_blacklist",
        passed=blacklist_ok,
        detail=f"{ticker} not blacklisted" if blacklist_ok
        else f"{ticker} is blacklisted",
    ))

    # 2. Required fields validation
    required_ok = all([ticker, direction, price is not None])
    if direction == "BUY":
        required_ok = required_ok and all([strike, option_type, expiry])
    checks.append(RiskCheck(
        name="required_fields",
        passed=required_ok,
        detail="All required fields present" if required_ok
        else "Missing required fields (ticker, direction, price, strike/expiry for options)",
    ))

    # 3. Confidence threshold
    pred_confidence = float(prediction.get("confidence", 0.0))
    conf_ok = pred_confidence >= confidence_threshold
    checks.append(RiskCheck(
        name="confidence_threshold",
        passed=conf_ok,
        detail=f"{pred_confidence:.3f} >= {confidence_threshold}" if conf_ok
        else f"{pred_confidence:.3f} < {confidence_threshold}",
    ))

    # 4. Percentage-sell position existence check (OldProject pattern)
    if direction == "SELL" and is_percentage:
        position_exists, current_qty = await _get_position_quantity(
            session, agent_id, ticker, strike, option_type, expiry
        )
        if not position_exists or current_qty <= 0:
            checks.append(RiskCheck(
                name="percentage_sell_position",
                passed=False,
                detail=f"No open position for {ticker} {strike}{option_type} to sell percentage",
            ))
        else:
            checks.append(RiskCheck(
                name="percentage_sell_position",
                passed=True,
                detail=f"Position exists with {current_qty} contracts",
            ))

    # 5. Quantity validation (for absolute quantities)
    if not is_percentage:
        qty_int = int(quantity) if isinstance(quantity, (int, float)) else 1
        qty_ok = 0 < qty_int <= max_position_size
        checks.append(RiskCheck(
            name="max_position_size",
            passed=qty_ok,
            detail=f"{qty_int} <= {max_position_size} max" if qty_ok
            else f"{qty_int} exceeds max position size {max_position_size}",
        ))

    # 6. Max concurrent positions — count open trade intents
    try:
        count_result = await session.execute(
            select(func.count(TradeIntent.id)).where(
                TradeIntent.agent_id == agent_id,
                TradeIntent.status.notin_(["REJECTED", "FAILED", "CANCELLED"]),
            )
        )
        open_positions = count_result.scalar_one()
    except Exception as exc:
        logger.warning("Failed to query open positions: %s", exc)
        open_positions = 0

    positions_ok = open_positions < max_positions
    checks.append(RiskCheck(
        name="max_concurrent_positions",
        passed=positions_ok,
        detail=f"{open_positions}/{max_positions} positions" if positions_ok
        else f"{open_positions} >= {max_positions} max",
    ))

    # 7. Total contracts limit (OldProject pattern)
    if direction == "BUY" and not is_percentage:
        try:
            total_result = await session.execute(
                select(func.sum(TradeIntent.qty)).where(
                    TradeIntent.agent_id == agent_id,
                    TradeIntent.status.notin_(["REJECTED", "FAILED", "CANCELLED"]),
                )
            )
            total_contracts = total_result.scalar_one() or 0
            qty_int = int(quantity) if isinstance(quantity, (int, float)) else 1
            new_total = total_contracts + qty_int
            total_ok = new_total <= max_total_contracts
            checks.append(RiskCheck(
                name="max_total_contracts",
                passed=total_ok,
                detail=f"{new_total}/{max_total_contracts} total contracts" if total_ok
                else f"{new_total} exceeds {max_total_contracts} max total contracts",
            ))
        except Exception as exc:
            logger.warning("Failed to query total contracts: %s", exc)

    # 8. Daily loss limit
    daily_pnl_pct = float(config.get("daily_pnl_pct", 0.0))
    daily_loss_ok = daily_pnl_pct > -max_daily_loss_pct
    checks.append(RiskCheck(
        name="max_daily_loss_pct",
        passed=daily_loss_ok,
        detail=f"daily PnL {daily_pnl_pct:.2f}% > -{max_daily_loss_pct}%" if daily_loss_ok
        else f"daily PnL {daily_pnl_pct:.2f}% exceeds -{max_daily_loss_pct}% limit",
    ))

    # 9. Buying power check (for BUY orders, OldProject pattern)
    if direction == "BUY" and not is_percentage:
        buying_power = float(config.get("buying_power", 0.0))
        qty_int = int(quantity) if isinstance(quantity, (int, float)) else 1
        required_cash = float(price) * qty_int * 100  # Options are per 100 shares
        buying_power_ok = buying_power >= required_cash
        checks.append(RiskCheck(
            name="buying_power",
            passed=buying_power_ok,
            detail=f"${buying_power:.2f} >= ${required_cash:.2f} required" if buying_power_ok
            else f"Insufficient buying power: need ${required_cash:.2f}, have ${buying_power:.2f}",
        ))

    all_passed = all(c.passed for c in checks)
    first_failure = next((c.name for c in checks if not c.passed), "")

    return RiskResult(
        approved=all_passed,
        reason="" if all_passed else first_failure,
        checks=checks,
    )


async def _get_position_quantity(
    session: AsyncSession,
    agent_id: str,
    ticker: str,
    strike: Optional[float],
    option_type: Optional[str],
    expiry: Optional[str],
) -> tuple[bool, int]:
    """Query current position quantity for percentage-sell validation.

    Returns (exists, quantity).
    """
    from shared.db.models.agent_trade import AgentTrade

    try:
        # Query agent_trades for matching open position
        conditions = [
            AgentTrade.agent_id == agent_id,
            AgentTrade.ticker == ticker,
            AgentTrade.exit_time.is_(None),  # Open position
        ]
        if strike is not None:
            conditions.append(AgentTrade.strike == strike)
        if option_type:
            conditions.append(AgentTrade.option_type == option_type)
        if expiry:
            conditions.append(AgentTrade.expiry == expiry)

        result = await session.execute(
            select(func.sum(AgentTrade.quantity)).where(and_(*conditions))
        )
        qty = result.scalar_one()
        if qty is None:
            qty = 0
        return int(qty) > 0, int(qty)
    except Exception as exc:
        logger.warning("Failed to query position quantity: %s", exc)
        return False, 0
