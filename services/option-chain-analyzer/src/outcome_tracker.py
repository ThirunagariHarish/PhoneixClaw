import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from shared.models.database import async_session_factory
from shared.models.trade import OptionAnalysisLog

logger = logging.getLogger(__name__)


async def check_past_recommendations():
    """Daily job: check past 7 days of recommendations and update outcomes."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    async with async_session_factory() as session:
        result = await session.execute(
            select(OptionAnalysisLog).where(
                OptionAnalysisLog.created_at >= cutoff,
                OptionAnalysisLog.outcome.is_(None),
            )
        )
        logs = result.scalars().all()

        if not logs:
            return 0

        updated = 0
        for log in logs:
            age_hours = (datetime.now(timezone.utc) - log.created_at).total_seconds() / 3600
            if age_hours < 24:
                continue

            outcome = {
                "status": "expired",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "note": "Auto-checked after 24h",
            }
            log.outcome = outcome
            updated += 1

        if updated:
            await session.commit()
            logger.info("Updated outcomes for %d past recommendations", updated)
        return updated
