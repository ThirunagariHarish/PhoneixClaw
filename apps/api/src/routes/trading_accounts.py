"""Trading accounts API routes."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.connector import Connector
from shared.db.models.trading_account import TradingAccount

router = APIRouter(prefix="/api/v2/trading-accounts", tags=["trading-accounts"])
logger = logging.getLogger(__name__)

BROKER_CONNECTOR_TYPES = {"robinhood", "alpaca", "ibkr", "tradier"}


async def _backfill_trading_accounts_from_connectors(session, user_id: uuid.UUID) -> int:
    """Create TradingAccount rows for active broker-type connectors that
    don't yet have a linked account. Idempotent; returns the number created.
    """
    from apps.api.src.routes.connectors import _ensure_trading_account_for_connector

    result = await session.execute(
        select(Connector).where(
            Connector.user_id == user_id,
            Connector.is_active == True,  # noqa: E712
            Connector.type.in_(BROKER_CONNECTOR_TYPES),
        )
    )
    connectors = result.scalars().all()
    created = 0
    for connector in connectors:
        _, was_created = await _ensure_trading_account_for_connector(session, connector)
        if was_created:
            created += 1
    if created:
        await session.commit()
        logger.info("Backfilled %d trading account(s) from connectors for user %s", created, user_id)
    return created


class TradingAccountResponse(BaseModel):
    id: str
    name: str
    broker: str
    broker_type: str  # alias of broker — the wizard reads this name
    account_type: str
    is_active: bool


@router.get("", response_model=list[TradingAccountResponse])
async def list_trading_accounts(
    request: Request,
    session: DbSession,
    category: str | None = Query(None, description="Filter by category (broker, data, etc)"),
):
    """List trading accounts for the authenticated user.

    For category=broker, returns broker accounts (robinhood, ibkr, alpaca).
    Used by the agent creation wizard to populate broker account dropdown.
    """
    caller_id = getattr(request.state, "user_id", None)
    if not caller_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    try:
        user_id = uuid.UUID(caller_id)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid user_id")

    # Ensure any broker-type connectors without a linked TradingAccount have one.
    # Fixes historical connectors created before trading_account auto-link existed.
    if category == "broker":
        try:
            await _backfill_trading_accounts_from_connectors(session, user_id)
        except Exception as exc:
            logger.warning("Trading-account backfill failed for user %s: %s", user_id, exc)

    query = select(TradingAccount).where(
        TradingAccount.user_id == user_id,
        TradingAccount.is_active == True,  # noqa: E712
    )

    if category == "broker":
        query = query.where(
            TradingAccount.broker.in_(list(BROKER_CONNECTOR_TYPES))
        )

    result = await session.execute(query)
    accounts = result.scalars().all()

    return [
        TradingAccountResponse(
            id=str(acc.id),
            name=acc.name,
            broker=acc.broker,
            broker_type=acc.broker,
            account_type=acc.account_type,
            is_active=acc.is_active,
        )
        for acc in accounts
    ]
