import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.trade import DailyMetrics, Position, Trade

logger = logging.getLogger(__name__)


class DailyAggregator:
    async def aggregate(
        self, session: AsyncSession, user_id: str,
        trading_account_id: str, target_date: date | None = None,
    ):
        d = target_date or date.today()

        result = await session.execute(
            select(
                func.count(Trade.id).label("total"),
                func.count().filter(Trade.status == "EXECUTED").label("executed"),
                func.count().filter(Trade.status == "REJECTED").label("rejected"),
                func.count().filter(Trade.status == "ERROR").label("errored"),
            ).where(
                Trade.trading_account_id == trading_account_id,
                func.date(Trade.created_at) == d,
            )
        )
        row = result.one()

        closed = await session.execute(
            select(func.count(Position.id), func.coalesce(func.sum(Position.realized_pnl), 0)).where(
                Position.trading_account_id == trading_account_id, func.date(Position.closed_at) == d
            )
        )
        closed_row = closed.one()

        metrics = DailyMetrics(
            user_id=user_id,
            trading_account_id=trading_account_id,
            date=d,
            total_trades=row.total,
            executed_trades=row.executed,
            rejected_trades=row.rejected,
            errored_trades=row.errored,
            closed_positions=closed_row[0],
            total_pnl=closed_row[1],
        )
        session.add(metrics)
        await session.commit()
        return metrics
