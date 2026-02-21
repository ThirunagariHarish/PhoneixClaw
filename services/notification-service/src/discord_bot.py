import logging
import uuid
from datetime import datetime, timezone

from discord import Intents
from discord.ext import commands

logger = logging.getLogger(__name__)

ADMIN_IDS: set[int] = set()


def _is_admin(author_id: int) -> bool:
    return not ADMIN_IDS or author_id in ADMIN_IDS


class TradingBot(commands.Bot):
    def __init__(self, admin_ids: list[int] | None = None):
        intents = Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        if admin_ids:
            ADMIN_IDS.update(admin_ids)
        self._approval_callback = None
        self._stats_callback = None
        self._kafka_producer = None

    def set_approval_callback(self, cb):
        self._approval_callback = cb

    def set_stats_callback(self, cb):
        self._stats_callback = cb

    def set_kafka_producer(self, producer):
        self._kafka_producer = producer

    async def on_ready(self):
        logger.info("Trading bot ready as %s", self.user)

    @commands.command(name="pending")
    async def cmd_pending(self, ctx):
        if not _is_admin(ctx.author.id):
            await ctx.send("Permission denied.")
            return
        try:
            from sqlalchemy import select

            from shared.models.database import AsyncSessionLocal
            from shared.models.trade import Trade

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Trade).where(Trade.status == "PENDING").order_by(Trade.created_at.desc()).limit(10)
                )
                trades = result.scalars().all()

            if not trades:
                await ctx.send("No pending trades.")
                return

            lines = [f"**{len(trades)} pending trade(s):**"]
            for t in trades:
                lines.append(
                    f"- `{t.trade_id}` {t.action} {t.ticker} {t.strike}{t.option_type[0]} @ {t.price}"
                )
            await ctx.send("\n".join(lines))
        except Exception as e:
            logger.exception("!pending failed")
            await ctx.send(f"Error fetching pending trades: {e}")

    @commands.command(name="approve")
    async def cmd_approve(self, ctx, trade_id: str = "all"):
        if not _is_admin(ctx.author.id):
            await ctx.send("Permission denied.")
            return
        try:
            from sqlalchemy import select

            from shared.models.database import AsyncSessionLocal
            from shared.models.trade import Trade

            async with AsyncSessionLocal() as session:
                if trade_id == "all":
                    result = await session.execute(
                        select(Trade).where(Trade.status == "PENDING")
                    )
                    trades = result.scalars().all()
                else:
                    result = await session.execute(
                        select(Trade).where(Trade.trade_id == uuid.UUID(trade_id))
                    )
                    trades = [t for t in result.scalars().all() if t.status == "PENDING"]

                if not trades:
                    await ctx.send("No pending trades found.")
                    return

                approved = 0
                for t in trades:
                    t.status = "APPROVED"
                    t.approved_by = str(ctx.author)
                    t.approved_at = datetime.now(timezone.utc)
                    approved += 1

                    if self._kafka_producer:
                        trade_dict = {
                            "trade_id": str(t.trade_id),
                            "user_id": str(t.user_id),
                            "trading_account_id": str(t.trading_account_id) if t.trading_account_id else None,
                            "ticker": t.ticker,
                            "strike": float(t.strike),
                            "option_type": t.option_type,
                            "expiration": t.expiration.strftime("%Y-%m-%d") if t.expiration else None,
                            "action": t.action,
                            "quantity": t.quantity,
                            "price": float(t.price),
                            "source": t.source,
                            "raw_message": t.raw_message,
                            "status": "APPROVED",
                            "approved_by": str(ctx.author),
                        }
                        await self._kafka_producer.send(
                            "approved-trades", value=trade_dict, key=str(t.trade_id)
                        )

                await session.commit()
                await ctx.send(f"Approved {approved} trade(s).")
        except Exception as e:
            logger.exception("!approve failed")
            await ctx.send(f"Error: {e}")

    @commands.command(name="reject")
    async def cmd_reject(self, ctx, trade_id: str, *, reason: str = ""):
        if not _is_admin(ctx.author.id):
            await ctx.send("Permission denied.")
            return
        try:
            from sqlalchemy import select

            from shared.models.database import AsyncSessionLocal
            from shared.models.trade import Trade

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Trade).where(Trade.trade_id == uuid.UUID(trade_id))
                )
                trade = result.scalar_one_or_none()
                if not trade:
                    await ctx.send(f"Trade {trade_id} not found.")
                    return
                if trade.status != "PENDING":
                    await ctx.send(f"Trade {trade_id} is {trade.status}, not PENDING.")
                    return
                trade.status = "REJECTED"
                trade.rejection_reason = reason or "Rejected via Discord"
                await session.commit()
            await ctx.send(f"Rejected trade {trade_id}.")
        except Exception as e:
            logger.exception("!reject failed")
            await ctx.send(f"Error: {e}")

    @commands.command(name="stats")
    async def cmd_stats(self, ctx):
        try:
            from sqlalchemy import func, select

            from shared.models.database import AsyncSessionLocal
            from shared.models.trade import Position, Trade

            async with AsyncSessionLocal() as session:
                total = (await session.execute(select(func.count(Trade.id)))).scalar() or 0
                executed = (await session.execute(
                    select(func.count(Trade.id)).where(Trade.status.in_(["EXECUTED", "FILLED"]))
                )).scalar() or 0
                pending = (await session.execute(
                    select(func.count(Trade.id)).where(Trade.status == "PENDING")
                )).scalar() or 0
                errors = (await session.execute(
                    select(func.count(Trade.id)).where(Trade.status == "ERROR")
                )).scalar() or 0
                open_pos = (await session.execute(
                    select(func.count(Position.id)).where(Position.status == "OPEN")
                )).scalar() or 0
                realized = (await session.execute(
                    select(func.coalesce(func.sum(Position.realized_pnl), 0)).where(
                        Position.status == "CLOSED"
                    )
                )).scalar() or 0

            msg = (
                f"**Trading Stats:**\n"
                f"Total trades: {total}\n"
                f"Executed: {executed}\n"
                f"Pending: {pending}\n"
                f"Errors: {errors}\n"
                f"Open positions: {open_pos}\n"
                f"Realized P&L: ${realized:,.2f}"
            )
            await ctx.send(msg)
        except Exception as e:
            logger.exception("!stats failed")
            await ctx.send(f"Error: {e}")

    @commands.command(name="kill")
    async def cmd_kill(self, ctx):
        if not _is_admin(ctx.author.id):
            await ctx.send("Permission denied.")
            return
        try:
            from sqlalchemy import select

            from shared.models.database import AsyncSessionLocal
            from shared.models.trade import Configuration

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Configuration).where(Configuration.key == "enable_trading")
                )
                cfg = result.scalar_one_or_none()
                if cfg:
                    cfg.value = False
                    cfg.updated_by = str(ctx.author)
                    cfg.updated_at = datetime.now(timezone.utc)
                else:
                    session.add(Configuration(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                        key="enable_trading",
                        value=False,
                        description="Global kill switch",
                        category="system",
                        updated_by=str(ctx.author),
                    ))
                await session.commit()
            await ctx.send("Kill switch activated. Trading disabled.")
        except Exception as e:
            logger.exception("!kill failed")
            await ctx.send(f"Error: {e}")

    @commands.command(name="resume")
    async def cmd_resume(self, ctx):
        if not _is_admin(ctx.author.id):
            await ctx.send("Permission denied.")
            return
        try:
            from sqlalchemy import select

            from shared.models.database import AsyncSessionLocal
            from shared.models.trade import Configuration

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Configuration).where(Configuration.key == "enable_trading")
                )
                cfg = result.scalar_one_or_none()
                if cfg:
                    cfg.value = True
                    cfg.updated_by = str(ctx.author)
                    cfg.updated_at = datetime.now(timezone.utc)
                    await session.commit()
            await ctx.send("Trading resumed. Kill switch deactivated.")
        except Exception as e:
            logger.exception("!resume failed")
            await ctx.send(f"Error: {e}")
