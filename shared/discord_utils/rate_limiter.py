"""Discord API rate limiter with leaky bucket and 429 handling.

Implements a reusable rate limiter for Discord API calls with:
- Leaky bucket algorithm (min 20ms between requests per channel)
- 429 response handling with Retry-After header + jitter
- Conservative mode (5s fixed delay) after 3 consecutive 429s
- Per-channel state tracking
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ChannelRateLimitState:
    """Tracks rate limit state for a single Discord channel."""
    channel_id: str
    last_request_time: Optional[datetime] = None
    consecutive_429_count: int = 0
    conservative_mode: bool = False
    total_requests: int = 0
    total_429s: int = 0


class DiscordRateLimiter:
    """Rate limiter for Discord API calls with leaky bucket and 429 handling."""

    MIN_INTERVAL_MS: int = 20  # Discord allows ~50 req/s per channel
    JITTER_MS: int = 1000  # 1s jitter added to Retry-After
    CONSECUTIVE_429_THRESHOLD: int = 3
    CONSERVATIVE_DELAY_MS: int = 5000  # 5s fixed delay in conservative mode

    def __init__(self) -> None:
        """Initialize rate limiter with empty channel state."""
        self._channels: dict[str, ChannelRateLimitState] = {}

    def _get_channel_state(self, channel_id: str) -> ChannelRateLimitState:
        """Get or create channel rate limit state."""
        if channel_id not in self._channels:
            self._channels[channel_id] = ChannelRateLimitState(channel_id=channel_id)
        return self._channels[channel_id]

    async def wait_if_needed(self, channel_id: str) -> None:
        """Wait if needed to respect minimum interval (leaky bucket)."""
        state = self._get_channel_state(channel_id)

        if state.conservative_mode:
            delay_ms = self.CONSERVATIVE_DELAY_MS
            logger.warning(
                f"Channel {channel_id} in conservative mode (3+ consecutive 429s) — "
                f"waiting {delay_ms}ms before request"
            )
            await asyncio.sleep(delay_ms / 1000.0)
            state.last_request_time = datetime.utcnow()
            state.total_requests += 1
            return

        # Leaky bucket: enforce minimum interval
        if state.last_request_time is not None:
            elapsed = (datetime.utcnow() - state.last_request_time).total_seconds() * 1000
            if elapsed < self.MIN_INTERVAL_MS:
                wait_ms = self.MIN_INTERVAL_MS - elapsed
                logger.debug(f"Channel {channel_id} rate limit — waiting {wait_ms:.1f}ms")
                await asyncio.sleep(wait_ms / 1000.0)

        state.last_request_time = datetime.utcnow()
        state.total_requests += 1

    async def handle_429(self, channel_id: str, retry_after: Optional[float] = None) -> None:
        """Handle a 429 response with Retry-After + jitter and conservative mode.

        Args:
            channel_id: Discord channel snowflake
            retry_after: Retry-After header value in seconds (if present)
        """
        state = self._get_channel_state(channel_id)
        state.consecutive_429_count += 1
        state.total_429s += 1

        # Calculate delay: Retry-After + jitter, or MIN_INTERVAL if no header
        if retry_after is not None:
            delay_ms = (retry_after * 1000) + self.JITTER_MS
        else:
            delay_ms = self.MIN_INTERVAL_MS + self.JITTER_MS

        logger.warning(
            f"Channel {channel_id} received 429 "
            f"(consecutive: {state.consecutive_429_count}, total: {state.total_429s}) — "
            f"waiting {delay_ms}ms"
        )

        await asyncio.sleep(delay_ms / 1000.0)

        # Enter conservative mode after threshold
        if state.consecutive_429_count >= self.CONSECUTIVE_429_THRESHOLD:
            state.conservative_mode = True
            logger.error(
                f"Channel {channel_id} entering conservative mode after "
                f"{self.CONSECUTIVE_429_THRESHOLD} consecutive 429s — "
                f"will use {self.CONSERVATIVE_DELAY_MS}ms fixed delay"
            )

        state.last_request_time = datetime.utcnow()

    def mark_success(self, channel_id: str) -> None:
        """Mark a successful request (reset consecutive 429 counter)."""
        state = self._get_channel_state(channel_id)
        if state.consecutive_429_count > 0:
            logger.info(
                f"Channel {channel_id} request succeeded — "
                f"resetting consecutive 429 counter (was {state.consecutive_429_count})"
            )
            state.consecutive_429_count = 0
            state.conservative_mode = False

    def get_stats(self, channel_id: str) -> dict:
        """Get rate limit statistics for a channel."""
        state = self._get_channel_state(channel_id)
        return {
            "channel_id": channel_id,
            "total_requests": state.total_requests,
            "total_429s": state.total_429s,
            "consecutive_429_count": state.consecutive_429_count,
            "conservative_mode": state.conservative_mode,
            "last_request_time": state.last_request_time.isoformat() if state.last_request_time else None,
        }
