"""Robinhood Context Fetcher — fetch live portfolio data for chat context injection.

Before spawning a chat Claude session for a live/approved agent, this service:
1. Loads the agent's Robinhood credentials from the DB (agent.config["robinhood_credentials"])
2. Calls robin_stocks in a thread-pool to avoid blocking the event loop
3. Returns a LivePortfolioContext dataclass injected into agent_context.json

Graceful fallback: any failure → error field set, no exception propagated, chat still works.
Security: credentials are never logged or included in responses.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Agent statuses that indicate a live, real-money trading session
LIVE_AGENT_STATUSES: frozenset[str] = frozenset({"RUNNING", "APPROVED"})


def _sanitize_error(exc: Exception, creds: dict | None = None) -> str:
    """Return a safe error string — cap length and scrub any credential values.

    Uses ``ClassName: message`` format so callers can distinguish error types
    without inspecting raw exception objects.  Credential values are replaced
    with ``***`` before the string ever reaches a JSON file or log line.
    """
    msg = type(exc).__name__ + ": " + str(exc)[:200]  # cap at 200 chars
    if creds:
        for key in ("username", "password", "totp_secret"):
            val = creds.get(key, "")
            if val and val in msg:
                msg = msg.replace(val, "***")
    return msg


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LivePortfolioContext:
    """Snapshot of a live agent's Robinhood portfolio."""

    positions: list[dict] = field(default_factory=list)
    account_value: float | None = None
    buying_power: float | None = None
    cash: float | None = None
    last_updated_at: str = field(default_factory=_now_iso)
    error: str | None = None

    def is_empty(self) -> bool:
        return not self.positions and self.account_value is None

    def to_dict(self) -> dict:
        return {
            "positions": self.positions,
            "account_value": self.account_value,
            "buying_power": self.buying_power,
            "cash": self.cash,
            "last_updated_at": self.last_updated_at,
            "error": self.error,
        }


class RobinhoodContextFetcher:
    """Fetch live Robinhood portfolio data for an agent's chat session."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._session = db_session

    async def fetch(self, agent_id: UUID) -> LivePortfolioContext:
        """Return live portfolio context, or an empty context on any failure."""
        try:
            creds = await self._load_credentials(agent_id)
            if creds is None:
                # Not a live agent, or no credentials — not an error
                return LivePortfolioContext(last_updated_at=_now_iso())
            return await self._fetch_from_robinhood(creds)
        except Exception as exc:
            logger.warning("[rh_ctx_fetcher] unexpected error for agent %s: %s", agent_id, exc)
            return LivePortfolioContext(last_updated_at=_now_iso(), error=_sanitize_error(exc))

    async def _load_credentials(self, agent_id: UUID) -> dict | None:
        """Return Robinhood credentials dict if agent is live and has them, else None."""
        from shared.db.models.agent import Agent  # noqa: PLC0415

        result = await self._session.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if agent is None:
            return None
        if agent.status not in LIVE_AGENT_STATUSES:
            logger.debug(
                "[rh_ctx_fetcher] agent %s status=%s not live — skipping fetch",
                agent_id,
                agent.status,
            )
            return None

        config = agent.config or {}
        rh_creds = config.get("robinhood_credentials") or {}
        if not rh_creds.get("username") or not rh_creds.get("password"):
            logger.debug("[rh_ctx_fetcher] agent %s has no Robinhood credentials", agent_id)
            return None

        return rh_creds

    async def _fetch_from_robinhood(self, creds: dict) -> LivePortfolioContext:
        """Run the synchronous robin_stocks calls in a thread-pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_sync, creds)

    def _fetch_sync(self, creds: dict) -> LivePortfolioContext:  # noqa: PLR0912
        """Synchronous portion: login → fetch positions + account → logout."""
        try:
            import robin_stocks.robinhood as rh  # noqa: PLC0415
        except ImportError as exc:
            return LivePortfolioContext(last_updated_at=_now_iso(), error=_sanitize_error(exc))

        username: str = creds.get("username", "")
        password: str = creds.get("password", "")
        totp_secret: str = creds.get("totp_secret", "") or ""

        try:
            # Generate TOTP code when a secret is configured
            mfa_code: str | None = None
            if totp_secret:
                try:
                    import pyotp  # noqa: PLC0415

                    mfa_code = pyotp.TOTP(totp_secret).now()
                except Exception as totp_exc:
                    logger.warning("[rh_ctx_fetcher] TOTP generation failed: %s", totp_exc)

            login_kwargs: dict = {"store_session": False, "pickle_name": ""}
            if mfa_code:
                login_kwargs["mfa_code"] = mfa_code
            rh.login(username, password, **login_kwargs)

            # ── Positions ────────────────────────────────────────────────────
            raw_positions: list[dict] = rh.account.get_open_stock_positions() or []
            positions: list[dict] = []
            for p in raw_positions:
                try:
                    instr = rh.stocks.get_instrument_by_url(p.get("instrument", "")) or {}
                    ticker = instr.get("symbol", "?")
                    quantity = float(p.get("quantity", 0) or 0)
                    avg_cost = float(p.get("average_buy_price", 0) or 0)
                    current_price = float(p.get("last_trade_price", 0) or 0)
                    if current_price == 0.0 and ticker != "?":
                        prices = rh.stocks.get_latest_price(ticker) or [0]
                        current_price = float(prices[0] or 0)
                    market_value = round(quantity * current_price, 2)
                    positions.append(
                        {
                            "ticker": ticker,
                            "quantity": quantity,
                            "avg_cost": avg_cost,
                            "current_price": current_price,
                            "market_value": market_value,
                        }
                    )
                except Exception as pos_exc:
                    logger.warning("[rh_ctx_fetcher] skipping position entry: %s", pos_exc)

            # ── Account summary ──────────────────────────────────────────────
            account_value: float | None = None
            buying_power: float | None = None
            cash: float | None = None
            try:
                profile = rh.profiles.load_portfolio_profile() or {}
                account = rh.profiles.load_account_profile() or {}
                account_value = float(profile.get("equity", 0) or 0)
                buying_power = float(account.get("buying_power", 0) or 0)
                cash = float(account.get("cash", 0) or 0)
            except Exception as acc_exc:
                logger.warning("[rh_ctx_fetcher] account summary fetch failed: %s", acc_exc)

            return LivePortfolioContext(
                positions=positions,
                account_value=account_value,
                buying_power=buying_power,
                cash=cash,
                last_updated_at=_now_iso(),
                error=None,
            )

        except Exception as exc:
            logger.warning("[rh_ctx_fetcher] robin_stocks fetch failed: %s", exc)
            return LivePortfolioContext(last_updated_at=_now_iso(), error=_sanitize_error(exc, creds))

        finally:
            try:
                rh.authentication.logout()
            except Exception:
                pass
