import logging
from datetime import datetime, timedelta, timezone

import msgpack
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.trade import SentimentAlert

logger = logging.getLogger(__name__)


async def evaluate_alerts(
    session: AsyncSession,
    ticker: str,
    aggregate: dict,
    kafka_producer=None,
) -> int:
    """Check all enabled alerts matching this ticker. Returns count of fired alerts."""
    result = await session.execute(
        select(SentimentAlert).where(
            SentimentAlert.enabled.is_(True),
            (SentimentAlert.ticker == ticker) | (SentimentAlert.ticker.is_(None)),
        )
    )
    alerts = result.scalars().all()
    fired = 0

    for alert in alerts:
        if not _should_fire(alert, aggregate):
            continue

        cooldown = alert.config.get("cooldown_minutes", 60)
        if alert.last_triggered_at:
            if datetime.now(timezone.utc) - alert.last_triggered_at < timedelta(minutes=cooldown):
                continue

        alert.last_triggered_at = datetime.now(timezone.utc)
        fired += 1

        if kafka_producer:
            notification = {
                "type": "sentiment_alert",
                "title": f"Sentiment Alert: {ticker}",
                "body": _build_alert_body(alert, ticker, aggregate),
                "user_id": str(alert.user_id),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await kafka_producer.send("notifications", msgpack.packb(notification))
            except Exception:
                logger.exception("Failed to send alert notification")

    if fired:
        await session.flush()
        logger.info("Fired %d alerts for %s", fired, ticker)

    return fired


def _should_fire(alert: SentimentAlert, aggregate: dict) -> bool:
    alert_type = alert.alert_type
    config = alert.config or {}

    if alert_type == "threshold":
        direction = config.get("direction", "below")
        threshold = config.get("score_threshold", 0)
        score = aggregate.get("sentiment_score", 0)
        if direction == "below" and score < threshold:
            return True
        if direction == "above" and score > threshold:
            return True

    elif alert_type == "flip":
        prev_label = config.get("_prev_label")
        current_label = aggregate.get("sentiment_label", "")
        if prev_label and prev_label != current_label:
            bullish_set = {"Very Bullish", "Bullish"}
            bearish_set = {"Very Bearish", "Bearish"}
            if (prev_label in bullish_set and current_label in bearish_set) or \
               (prev_label in bearish_set and current_label in bullish_set):
                return True
        config["_prev_label"] = current_label

    elif alert_type == "spike":
        min_change = config.get("min_change_pct", 50)
        change = aggregate.get("mention_change_pct")
        if change is not None and abs(change) >= min_change:
            return True

    elif alert_type == "mention_count":
        min_mentions = config.get("min_mentions", 10)
        if aggregate.get("message_count", 0) >= min_mentions:
            return True

    return False


def _build_alert_body(alert: SentimentAlert, ticker: str, aggregate: dict) -> str:
    label = aggregate.get("sentiment_label", "N/A")
    score = aggregate.get("sentiment_score", 0)
    mentions = aggregate.get("message_count", 0)
    change = aggregate.get("mention_change_pct")

    body = f"{ticker} sentiment: {label} (score: {score:.2f}, {mentions} mentions)"
    if change is not None:
        body += f", change: {change:+.1f}%"
    body += f"\nAlert type: {alert.alert_type}"
    return body
