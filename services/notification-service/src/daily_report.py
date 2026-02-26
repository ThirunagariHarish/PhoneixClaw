import asyncio
import logging
from datetime import datetime, time, timedelta

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
MARKET_CLOSE = time(16, 0)


async def _generate_and_send_reports():
    """Query today's trades for each user and email a consolidated report."""
    try:
        from sqlalchemy import cast, Date as SQLDate, func, select

        from shared.email.sender import send_html_email
        from shared.models.database import AsyncSessionLocal
        from shared.models.trade import Trade, User

        today = datetime.now(ET).date()

        async with AsyncSessionLocal() as session:
            users_result = await session.execute(
                select(User).where(User.is_active.is_(True))
            )
            users = users_result.scalars().all()

            for user in users:
                prefs = user.notification_prefs or {}
                if not prefs.get("email_enabled", True):
                    continue
                if not user.email:
                    continue

                trades_result = await session.execute(
                    select(Trade)
                    .where(
                        Trade.user_id == user.id,
                        cast(Trade.created_at, SQLDate) == today,
                    )
                    .order_by(Trade.created_at)
                )
                trades = trades_result.scalars().all()
                if not trades:
                    continue

                total = len(trades)
                executed = sum(1 for t in trades if t.status == "EXECUTED")
                rejected = sum(1 for t in trades if t.status == "REJECTED")
                errored = sum(1 for t in trades if t.status == "ERROR")
                total_pnl = sum(float(t.realized_pnl or 0) for t in trades)
                winners = sum(1 for t in trades if (t.realized_pnl or 0) > 0)
                losers = sum(1 for t in trades if (t.realized_pnl or 0) < 0)
                win_rate = round(winners / max(winners + losers, 1) * 100, 1)

                pnl_color = "#10b981" if total_pnl >= 0 else "#ef4444"
                pnl_sign = "+" if total_pnl >= 0 else ""

                trade_rows = ""
                for t in trades:
                    action_color = "#10b981" if t.action in ("BUY", "BTO") else "#ef4444"
                    pnl_val = float(t.realized_pnl or 0)
                    pnl_cell_color = "#10b981" if pnl_val > 0 else "#ef4444" if pnl_val < 0 else "#888"
                    trade_rows += f"""
                    <tr>
                        <td style="padding:8px 12px;border-bottom:1px solid #eee;">{t.ticker}</td>
                        <td style="padding:8px 12px;border-bottom:1px solid #eee;color:{action_color};font-weight:600;">{t.action}</td>
                        <td style="padding:8px 12px;border-bottom:1px solid #eee;">{float(t.strike)}</td>
                        <td style="padding:8px 12px;border-bottom:1px solid #eee;">{t.option_type}</td>
                        <td style="padding:8px 12px;border-bottom:1px solid #eee;">${float(t.price):.2f}</td>
                        <td style="padding:8px 12px;border-bottom:1px solid #eee;">{t.status}</td>
                        <td style="padding:8px 12px;border-bottom:1px solid #eee;color:{pnl_cell_color};">${pnl_val:+.2f}</td>
                    </tr>"""

                html = f"""
                <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:640px;margin:0 auto;color:#333;">
                    <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;padding:24px 32px;border-radius:12px 12px 0 0;">
                        <h1 style="margin:0;font-size:22px;">PhoenixTrade Daily Report</h1>
                        <p style="margin:4px 0 0;opacity:0.8;font-size:14px;">{today.strftime('%A, %B %d, %Y')}</p>
                    </div>

                    <div style="background:#f8f9fa;padding:24px 32px;border:1px solid #e0e0e0;">
                        <div style="display:flex;gap:16px;flex-wrap:wrap;">
                            <div style="flex:1;min-width:120px;background:white;border-radius:8px;padding:16px;text-align:center;border:1px solid #eee;">
                                <p style="margin:0;font-size:28px;font-weight:700;color:{pnl_color};">{pnl_sign}${abs(total_pnl):.2f}</p>
                                <p style="margin:4px 0 0;font-size:12px;color:#888;">Total P&L</p>
                            </div>
                            <div style="flex:1;min-width:80px;background:white;border-radius:8px;padding:16px;text-align:center;border:1px solid #eee;">
                                <p style="margin:0;font-size:28px;font-weight:700;">{total}</p>
                                <p style="margin:4px 0 0;font-size:12px;color:#888;">Total Trades</p>
                            </div>
                            <div style="flex:1;min-width:80px;background:white;border-radius:8px;padding:16px;text-align:center;border:1px solid #eee;">
                                <p style="margin:0;font-size:28px;font-weight:700;">{win_rate}%</p>
                                <p style="margin:4px 0 0;font-size:12px;color:#888;">Win Rate</p>
                            </div>
                        </div>

                        <div style="display:flex;gap:12px;margin-top:16px;flex-wrap:wrap;">
                            <span style="background:#10b981;color:white;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;">{executed} Executed</span>
                            <span style="background:#10b981;color:white;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;">{winners}W / {losers}L</span>
                            {f'<span style="background:#f59e0b;color:white;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;">{rejected} Rejected</span>' if rejected else ''}
                            {f'<span style="background:#ef4444;color:white;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;">{errored} Errors</span>' if errored else ''}
                        </div>
                    </div>

                    <div style="padding:0 0 24px;border:1px solid #e0e0e0;border-top:none;border-radius:0 0 12px 12px;overflow:hidden;">
                        <table style="width:100%;border-collapse:collapse;font-size:13px;">
                            <thead>
                                <tr style="background:#f1f3f5;">
                                    <th style="padding:10px 12px;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;color:#666;">Ticker</th>
                                    <th style="padding:10px 12px;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;color:#666;">Action</th>
                                    <th style="padding:10px 12px;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;color:#666;">Strike</th>
                                    <th style="padding:10px 12px;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;color:#666;">Type</th>
                                    <th style="padding:10px 12px;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;color:#666;">Price</th>
                                    <th style="padding:10px 12px;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;color:#666;">Status</th>
                                    <th style="padding:10px 12px;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;color:#666;">P&L</th>
                                </tr>
                            </thead>
                            <tbody>{trade_rows}</tbody>
                        </table>
                    </div>

                    <p style="text-align:center;font-size:11px;color:#aaa;margin-top:16px;">
                        This is an automated report from PhoenixTrade. You can disable these emails in your notification preferences.
                    </p>
                </div>
                """

                await asyncio.to_thread(
                    send_html_email,
                    to_email=user.email,
                    subject=f"PhoenixTrade Daily Report — {pnl_sign}${abs(total_pnl):.2f} | {today.strftime('%b %d')}",
                    html_body=html,
                )
                logger.info("Daily report sent to %s (%d trades)", user.email, total)

    except Exception:
        logger.exception("Failed to generate daily reports")


def _seconds_until_market_close() -> float:
    """Calculate seconds until the next 4:00 PM ET."""
    now = datetime.now(ET)
    target = datetime.combine(now.date(), MARKET_CLOSE, tzinfo=ET)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_daily_report_scheduler():
    """Loop forever, sending daily reports at 4:00 PM ET."""
    while True:
        wait = _seconds_until_market_close()
        logger.info("Daily report scheduler: next run in %.0f seconds (%.1f hours)", wait, wait / 3600)
        await asyncio.sleep(wait)
        logger.info("Market close reached — generating daily reports")
        await _generate_and_send_reports()
        await asyncio.sleep(60)
