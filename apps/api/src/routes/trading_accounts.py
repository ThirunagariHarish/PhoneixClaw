"""Trading accounts API routes."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.trading_account import TradingAccount

router = APIRouter(prefix="/api/v2/trading-accounts", tags=["trading-accounts"])
logger = logging.getLogger(__name__)


class TradingAccountResponse(BaseModel):
    id: str
    name: str
    broker: str
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

    query = select(TradingAccount).where(
        TradingAccount.user_id == user_id,
        TradingAccount.is_active == True,  # noqa: E712
    )

    # Filter by category=broker for Phase A
    if category == "broker":
        query = query.where(
            TradingAccount.broker.in_(["robinhood", "ibkr", "alpaca"])
        )

    result = await session.execute(query)
    accounts = result.scalars().all()

    return [
        TradingAccountResponse(
            id=str(acc.id),
            name=acc.name,
            broker=acc.broker,
            account_type=acc.account_type,
            is_active=acc.is_active,
        )
        for acc in accounts
    ]
