"""DiscoveryScanner — periodic multi-venue market scanner (Phase 4).

Responsibilities
----------------
1. Iterate every registered `MarketVenue`, call `scan()`, and collect
   `MarketRow`s. Per-venue failures are isolated: if Polymarket raises
   mid-scan, Kalshi (when implemented) still runs.
2. Apply basic edge filters (volume, time-to-resolution, spread) to
   drop markets that can't plausibly support edge calculation. These
   filters are intentionally cheap — F9 (Phase 5) and per-strategy
   gates do the real work later.
3. Hand surviving rows to a `sink` callable. The default sink upserts
   `pm_markets` via the ORM; tests inject a recording sink.
4. Optionally run forever (`run_forever`) with a fixed interval.

Reference: docs/architecture/polymarket-tab.md section 9, Phase 4.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable

from ..venues.base import (
    MarketRow,
    MarketVenue,
    NotConfiguredError,
    VenueError,
    VenueScanResult,
)

logger = logging.getLogger(__name__)


DEFAULT_MIN_VOLUME_USD = 1_000.0
DEFAULT_MIN_DAYS_TO_RESOLUTION = 0.25  # 6 hours
DEFAULT_MAX_DAYS_TO_RESOLUTION = 365.0
DEFAULT_MAX_SPREAD = 0.20  # 20¢ on a 0..1 probability book
DEFAULT_SCAN_INTERVAL_SEC = 30.0
DEFAULT_PER_VENUE_LIMIT = 500


Sink = Callable[[list[MarketRow]], Awaitable[int]]


@dataclass(frozen=True)
class EdgeFilters:
    """Cheap pre-F9 filters. All fields optional; `None` disables."""

    min_volume_usd: float | None = DEFAULT_MIN_VOLUME_USD
    min_days_to_resolution: float | None = DEFAULT_MIN_DAYS_TO_RESOLUTION
    max_days_to_resolution: float | None = DEFAULT_MAX_DAYS_TO_RESOLUTION
    max_spread: float | None = DEFAULT_MAX_SPREAD
    require_active: bool = True

    def evaluate(self, row: MarketRow, *, now: datetime | None = None) -> str | None:
        """Return None if row passes, otherwise a short reject reason."""
        if self.require_active and not row.is_active:
            return "inactive"

        if self.min_volume_usd is not None:
            if row.total_volume is None:
                return "volume_unknown"
            if row.total_volume < self.min_volume_usd:
                return "volume_below_min"

        if self.min_days_to_resolution is not None or self.max_days_to_resolution is not None:
            if row.expiry is None:
                return "expiry_unknown"
            now = now or datetime.now(timezone.utc)
            expiry = row.expiry if row.expiry.tzinfo else row.expiry.replace(tzinfo=timezone.utc)
            delta_days = (expiry - now).total_seconds() / 86400.0
            if (
                self.min_days_to_resolution is not None
                and delta_days < self.min_days_to_resolution
            ):
                return "expiry_too_soon"
            if (
                self.max_days_to_resolution is not None
                and delta_days > self.max_days_to_resolution
            ):
                return "expiry_too_far"

        if self.max_spread is not None:
            spread = row.spread
            # None spread is allowed — F9 / strategy-level will re-check
            # once RTDS populates the book. Only reject when we have a
            # spread and it is wider than the cap.
            if spread is not None and spread > self.max_spread:
                return "spread_too_wide"

        return None


@dataclass
class ScanCycleResult:
    """Result of one full scan across all venues."""

    started_at: datetime
    finished_at: datetime
    venues: list[VenueScanResult] = field(default_factory=list)
    accepted: list[MarketRow] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)
    persisted_count: int = 0

    @property
    def total_scanned(self) -> int:
        return sum(len(v.rows) for v in self.venues)

    @property
    def venue_errors(self) -> list[tuple[str, str]]:
        return [(v.venue, v.error) for v in self.venues if v.error]


class DiscoveryScanner:
    """Periodic multi-venue market scanner.

    The scanner is intentionally stateless between cycles: each call to
    `scan_once` is independent. Callers wanting a long-running loop can
    use `run_forever`.
    """

    def __init__(
        self,
        venues: Iterable[MarketVenue],
        *,
        sink: Sink | None = None,
        filters: EdgeFilters | None = None,
        per_venue_limit: int = DEFAULT_PER_VENUE_LIMIT,
        interval_sec: float = DEFAULT_SCAN_INTERVAL_SEC,
    ) -> None:
        self._venues = list(venues)
        if not self._venues:
            raise ValueError("DiscoveryScanner requires at least one venue")
        self._sink: Sink = sink or _noop_sink
        self._filters = filters or EdgeFilters()
        self._per_venue_limit = per_venue_limit
        self._interval_sec = interval_sec
        self._stopped = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def scan_once(self) -> ScanCycleResult:
        """Run one scan cycle across all venues."""
        started = datetime.now(timezone.utc)
        result = ScanCycleResult(started_at=started, finished_at=started)

        # Per-venue isolation: each venue runs in its own task so a
        # crash in one does not abort the others.
        tasks = [
            asyncio.create_task(self._scan_venue(v), name=f"pm-scan:{v.name}")
            for v in self._venues
        ]
        venue_results = await asyncio.gather(*tasks, return_exceptions=False)
        result.venues = list(venue_results)

        accepted: list[MarketRow] = []
        rejected: dict[str, int] = {}
        for vr in venue_results:
            for row in vr.rows:
                reason = self._filters.evaluate(row)
                if reason is None:
                    accepted.append(row)
                else:
                    rejected[reason] = rejected.get(reason, 0) + 1

        result.accepted = accepted
        result.rejected = rejected

        if accepted:
            try:
                persisted = await self._sink(accepted)
            except Exception as e:  # noqa: BLE001 - sink errors must not kill scanner
                logger.exception("discovery_scanner sink failed err=%s", type(e).__name__)
                persisted = 0
            result.persisted_count = int(persisted or 0)

        result.finished_at = datetime.now(timezone.utc)
        logger.info(
            "discovery_scanner cycle scanned=%d accepted=%d persisted=%d rejected=%s errors=%s",
            result.total_scanned,
            len(accepted),
            result.persisted_count,
            rejected,
            result.venue_errors,
        )
        return result

    async def run_forever(self) -> None:
        """Run scan cycles until `stop()` is called."""
        self._stopped.clear()
        while not self._stopped.is_set():
            try:
                await self.scan_once()
            except Exception as e:  # noqa: BLE001 - defensive; scan_once rarely raises
                logger.exception("discovery_scanner cycle crashed err=%s", type(e).__name__)
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval_sec)
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stopped.set()

    async def aclose(self) -> None:
        self.stop()
        for v in self._venues:
            try:
                await v.aclose()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "discovery_scanner venue_close_failed venue=%s err=%s",
                    v.name,
                    type(e).__name__,
                )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _scan_venue(self, venue: MarketVenue) -> VenueScanResult:
        rows: list[MarketRow] = []
        try:
            async for row in venue.scan(limit=self._per_venue_limit):
                rows.append(row)
                if len(rows) >= self._per_venue_limit:
                    break
        except NotConfiguredError as e:
            logger.info("discovery_scanner venue_skipped venue=%s reason=%s", venue.name, e)
            return VenueScanResult(venue=venue.name, rows=[], error=f"not_configured: {e}")
        except VenueError as e:
            logger.warning(
                "discovery_scanner venue_failed venue=%s err=%s", venue.name, e
            )
            return VenueScanResult(venue=venue.name, rows=rows, error=str(e))
        except Exception as e:  # noqa: BLE001 - isolate unknown venue crashes
            logger.exception(
                "discovery_scanner venue_crashed venue=%s err=%s", venue.name, type(e).__name__
            )
            return VenueScanResult(
                venue=venue.name, rows=rows, error=f"crashed: {type(e).__name__}"
            )
        return VenueScanResult(venue=venue.name, rows=rows)


# ----------------------------------------------------------------------
# Default sinks
# ----------------------------------------------------------------------
async def _noop_sink(rows: list[MarketRow]) -> int:
    return 0


def make_orm_sink(session_factory: Callable[[], Any]) -> Sink:
    """Build a sink that upserts `pm_markets` rows via SQLAlchemy.

    `session_factory` is any zero-arg callable returning a context-
    manageable SQLAlchemy `Session` (sync). Kept as a closure so the
    scanner module has no hard dependency on the DB layer — tests and
    benchmarks can inject a fake sink instead.
    """

    async def _sink(rows: list[MarketRow]) -> int:
        from shared.db.models.polymarket import PMMarket  # local import

        def _do_upsert() -> int:
            count = 0
            with session_factory() as session:
                now = datetime.now(timezone.utc)
                for r in rows:
                    existing = (
                        session.query(PMMarket)
                        .filter(
                            PMMarket.venue == r.venue,
                            PMMarket.venue_market_id == r.venue_market_id,
                        )
                        .one_or_none()
                    )
                    if existing is None:
                        session.add(
                            PMMarket(
                                venue=r.venue,
                                venue_market_id=r.venue_market_id,
                                slug=r.slug,
                                question=r.question,
                                category=r.category,
                                outcomes=list(r.outcomes),
                                total_volume=r.total_volume,
                                liquidity_usd=r.liquidity_usd,
                                expiry=r.expiry,
                                resolution_source=r.resolution_source,
                                oracle_type=r.oracle_type,
                                is_active=r.is_active,
                                last_scanned_at=now,
                            )
                        )
                    else:
                        existing.slug = r.slug
                        existing.question = r.question
                        existing.category = r.category
                        existing.outcomes = list(r.outcomes)
                        existing.total_volume = r.total_volume
                        existing.liquidity_usd = r.liquidity_usd
                        existing.expiry = r.expiry
                        existing.resolution_source = r.resolution_source
                        existing.oracle_type = r.oracle_type
                        existing.is_active = r.is_active
                        existing.last_scanned_at = now
                    count += 1
                session.commit()
            return count

        return await asyncio.to_thread(_do_upsert)

    return _sink
