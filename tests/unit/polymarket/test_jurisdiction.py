"""Unit tests for shared.polymarket.jurisdiction.JurisdictionAttestationGate.

The gate only does a single SELECT against `pm_jurisdiction_attestations`
ordered by created_at desc. We exercise it with a tiny in-memory fake
Session that mimics `session.execute(stmt).scalar_one_or_none()` so the
test does not need Postgres (the real model uses JSONB/UUID PG types).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from shared.db.models.polymarket import PMJurisdictionAttestation
from shared.polymarket.jurisdiction import (
    DEFAULT_ATTESTATION_TTL,
    AttestationState,
    JurisdictionAttestationGate,
    JurisdictionGateError,
)


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeSession:
    """Returns the most-recent matching attestation row for the given user."""

    def __init__(self, rows):
        self.rows = list(rows)

    def execute(self, stmt):
        # The gate's query targets a single user with order_by created_at desc
        # limit 1. We approximate by sorting our in-memory list and matching
        # on user_id parsed out of the compiled SQL parameters.
        compiled = stmt.compile()
        target = compiled.params.get("user_id_1")
        candidates = [r for r in self.rows if r.user_id == target]
        candidates.sort(key=lambda r: r.created_at, reverse=True)
        return _Result(candidates[0] if candidates else None)


def _make_row(user_id, *, valid_for=DEFAULT_ATTESTATION_TTL, ack=True,
              created_offset=timedelta(0)):
    now = datetime.now(timezone.utc)
    row = PMJurisdictionAttestation(
        user_id=user_id,
        attestation_text_hash="a" * 64,
        acknowledged_geoblock=ack,
        ip_at_attestation="127.0.0.1",
        user_agent="pytest",
        valid_until=now + valid_for,
    )
    # SQLAlchemy default factories don't fire outside a session — set manually.
    row.id = uuid.uuid4()
    row.created_at = now + created_offset
    return row


def test_missing_attestation_is_invalid():
    gate = JurisdictionAttestationGate()
    state = gate.evaluate(FakeSession([]), uuid.uuid4())
    assert state.valid is False
    assert state.reason == "missing"


def test_valid_attestation_passes():
    user_id = uuid.uuid4()
    row = _make_row(user_id)
    gate = JurisdictionAttestationGate()
    state = gate.evaluate(FakeSession([row]), user_id)
    assert state.valid is True
    assert state.reason == "ok"
    assert state.attestation_id == row.id


def test_expired_attestation_fails():
    user_id = uuid.uuid4()
    row = _make_row(user_id, valid_for=timedelta(days=-1))
    gate = JurisdictionAttestationGate()
    state = gate.evaluate(FakeSession([row]), user_id)
    assert state.valid is False
    assert state.reason == "expired"


def test_unacknowledged_attestation_fails():
    user_id = uuid.uuid4()
    row = _make_row(user_id, ack=False)
    gate = JurisdictionAttestationGate()
    state = gate.evaluate(FakeSession([row]), user_id)
    assert state.valid is False
    assert state.reason == "not_acknowledged"


def test_most_recent_row_wins():
    user_id = uuid.uuid4()
    older_expired = _make_row(
        user_id, valid_for=timedelta(days=-1), created_offset=timedelta(days=-10)
    )
    newer_valid = _make_row(user_id)
    gate = JurisdictionAttestationGate()
    state = gate.evaluate(FakeSession([older_expired, newer_valid]), user_id)
    assert state.valid is True


def test_assert_valid_raises_on_invalid():
    gate = JurisdictionAttestationGate()
    with pytest.raises(JurisdictionGateError):
        gate.assert_valid(FakeSession([]), uuid.uuid4())


def test_assert_valid_returns_state_on_success():
    user_id = uuid.uuid4()
    row = _make_row(user_id)
    gate = JurisdictionAttestationGate()
    state = gate.assert_valid(FakeSession([row]), user_id)
    assert isinstance(state, AttestationState)
    assert state.valid is True


def test_now_fn_injection():
    user_id = uuid.uuid4()
    row = _make_row(user_id, valid_for=timedelta(days=1))
    # Pretend "now" is two days from now → the attestation should be expired.
    future = datetime.now(timezone.utc) + timedelta(days=2)
    gate = JurisdictionAttestationGate(now_fn=lambda: future)
    state = gate.evaluate(FakeSession([row]), user_id)
    assert state.valid is False
    assert state.reason == "expired"


def test_naive_valid_until_is_normalized():
    user_id = uuid.uuid4()
    row = _make_row(user_id)
    # Simulate SQLite-style naive datetime returned by some drivers.
    row.valid_until = row.valid_until.replace(tzinfo=None)
    gate = JurisdictionAttestationGate()
    state = gate.evaluate(FakeSession([row]), user_id)
    assert state.valid is True
