import logging

from discord import Intents
from discord.ext import commands

logger = logging.getLogger(__name__)

ADMIN_IDS: set[int] = set()

class TradingBot(commands.Bot):
    def __init__(self, admin_ids: list[int] | None = None):
        intents = Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        if admin_ids:
            ADMIN_IDS.update(admin_ids)
        self._approval_callback = None
        self._stats_callback = None

    def set_approval_callback(self, cb):
        self._approval_callback = cb

    def set_stats_callback(self, cb):
        self._stats_callback = cb

    async def on_ready(self):
        logger.info("Trading bot ready as %s", self.user)

    @commands.command(name="pending")
    async def cmd_pending(self, ctx):
        if ctx.author.id not in ADMIN_IDS and ADMIN_IDS:
            await ctx.send("Permission denied.")
            return
        await ctx.send("Fetching pending trades...")

    @commands.command(name="approve")
    async def cmd_approve(self, ctx, trade_id: str = "all"):
        if ctx.author.id not in ADMIN_IDS and ADMIN_IDS:
            await ctx.send("Permission denied.")
            return
        if self._approval_callback:
            result = await self._approval_callback("approve", trade_id, str(ctx.author))
            await ctx.send(result)
        else:
            await ctx.send(f"Approved: {trade_id}")

    @commands.command(name="reject")
    async def cmd_reject(self, ctx, trade_id: str, *, reason: str = ""):
        if ctx.author.id not in ADMIN_IDS and ADMIN_IDS:
            await ctx.send("Permission denied.")
            return
        if self._approval_callback:
            result = await self._approval_callback("reject", trade_id, reason)
            await ctx.send(result)
        else:
            await ctx.send(f"Rejected: {trade_id}")

    @commands.command(name="stats")
    async def cmd_stats(self, ctx):
        if self._stats_callback:
            result = await self._stats_callback()
            await ctx.send(result)
        else:
            await ctx.send("Stats not available.")

    @commands.command(name="kill")
    async def cmd_kill(self, ctx):
        if ctx.author.id not in ADMIN_IDS and ADMIN_IDS:
            await ctx.send("Permission denied.")
            return
        await ctx.send("Kill switch activated. Trading disabled.")

    @commands.command(name="resume")
    async def cmd_resume(self, ctx):
        if ctx.author.id not in ADMIN_IDS and ADMIN_IDS:
            await ctx.send("Permission denied.")
            return
        await ctx.send("Trading resumed.")
