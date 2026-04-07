"""
JurisdictionAttestationGate (Phase 1, Polymarket v1.0).

Reference: docs/architecture/polymarket-tab.md sections 1, 4.8, 10 (R-A).

This primitive answers a single question: does a given user currently have
an unexpired, valid jurisdiction attestation row in
`pm_jurisdiction_attestations`?

It is invoked by:
  - `PolymarketBroker.connect()` (Phase 2) — refuses to start without one.
  - The promotion-gate engine (Phase 11) — every promotion re-checks.
  - The risk chain PM extension (Phase 6) — every order re-checks.

The gate is intentionally pure and synchronous over a SQLAlchemy Session
so that it composes with both the existing risk chain (sync) and the
async API routes (which can wrap it in `run_in_threadpool` if needed).
There is no business logic beyond "find the most recent attestation row
for this user and check `valid_until > now` and `acknowledged_geoblock`."

The TTL itself is enforced at write time (the API route stamps
`valid_until = now + DEFAULT_TTL`), not here. This gate only reads.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db.models.polymarket import PMJurisdictionAttestation

# Default TTL used by the writer side (API route in a later phase). Surfaced
# here so callers do not need a second source of truth.
DEFAULT_ATTESTATION_TTL = timedelta(days=30)


class JurisdictionGateError(RuntimeError):
    """Raised when a caller asserts a valid attestation but none exists."""


@dataclass(frozen=True)
class AttestationState:
    """Snapshot of a user's current attestation state."""

    valid: bool
    reason: str
    attestation_id: Optional[uuid.UUID] = None
    valid_until: Optional[datetime] = None

    def require_valid(self) -> None:
        """Raise if the attestation is not currently valid."""
        if not self.valid:
            raise JurisdictionGateError(f"jurisdiction attestation invalid: {self.reason}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JurisdictionAttestationGate:
    """Reads attestation rows and reports validity.

    Stateless. One instance can be reused across requests / strategies.
    """

    def __init__(self, *, now_fn=_utcnow) -> None:
        self._now_fn = now_fn

    def evaluate(self, session: Session, user_id: uuid.UUID) -> AttestationState:
        """Return the current attestation state for `user_id`.

        Selects the most recently created attestation row for the user and
        checks both `acknowledged_geoblock` and `valid_until > now`.
        """
        stmt = (
            select(PMJurisdictionAttestation)
            .where(PMJurisdictionAttestation.user_id == user_id)
            .order_by(PMJurisdictionAttestation.created_at.desc())
            .limit(1)
        )
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            return AttestationState(valid=False, reason="missing")

        if not row.acknowledged_geoblock:
            return AttestationState(
                valid=False,
                reason="not_acknowledged",
                attestation_id=row.id,
                valid_until=row.valid_until,
            )

        valid_until = row.valid_until
        if valid_until is not None and valid_until.tzinfo is None:
            # Normalize naive timestamps coming back from SQLite to UTC.
            valid_until = valid_until.replace(tzinfo=timezone.utc)

        now = self._now_fn()
        if valid_until is None or valid_until <= now:
            return AttestationState(
                valid=False,
                reason="expired",
                attestation_id=row.id,
                valid_until=valid_until,
            )

        return AttestationState(
            valid=True,
            reason="ok",
            attestation_id=row.id,
            valid_until=valid_until,
        )

    def assert_valid(self, session: Session, user_id: uuid.UUID) -> AttestationState:
        """Convenience helper: evaluate and raise on invalid."""
        state = self.evaluate(session, user_id)
        state.require_valid()
        return state
