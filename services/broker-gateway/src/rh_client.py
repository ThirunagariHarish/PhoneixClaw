"""Singleton Robinhood client factory with session refresh loop.

Ported from SelfAgentBot (agents_impl/robinhood/client_factory.py). Replaces
the per-request login pattern with a process-wide singleton that:

* Authenticates once on first call (30 s hard timeout)
* Refreshes session every 15 min via cheap profile load
* Invalidates session pickle on auth failure + exponential backoff
* Audit logs to /app/data/.tokens/audit.jsonl with secret redaction

The session-pooling layer in main.py calls this for actual rh.login/logout.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("broker-gateway.rh_client")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TOKEN_DIR = Path(os.environ.get("TOKEN_DIR", "/app/data/.tokens"))
AUDIT_PATH = TOKEN_DIR / "audit.jsonl"
LOGIN_TIMEOUT_S = 30.0
REFRESH_INTERVAL_S = 15 * 60  # 15 minutes
BACKOFF_SCHEDULE = [5, 10, 20, 40, 60]  # 5 s → 60 s cap

# ---------------------------------------------------------------------------
# Module-level singleton state
# ---------------------------------------------------------------------------
_rh_module: Any = None
_auth_fail_count = 0
_backoff_until = 0.0


def _get_rh() -> Any:
    """Lazy import robin_stocks. Cached module-level."""
    global _rh_module
    if _rh_module is None:
        import robin_stocks.robinhood as rh
        _rh_module = rh
    return _rh_module


# ---------------------------------------------------------------------------
# Secret redaction (minimal inline version — no external deps)
# ---------------------------------------------------------------------------
import re

_SECRET_PATTERNS = [
    # password=..., token=..., etc. in JSON/form-encoded
    (re.compile(
        r'(["\']?(?:password|passwd|secret|token|api[_-]?key|access[_-]?token|'
        r'otp|mfa)["\']?\s*[:=]\s*["\']?)([^"\'&\s,}\)]{4,})',
        re.IGNORECASE
    ), r'\1<REDACTED>'),
    # Query strings ?apikey=..., &token=...
    (re.compile(
        r'([?&](?:apikey|api_key|key|token|secret|otp|mfa)=)([^&\s#]+)',
        re.IGNORECASE
    ), r'\1<REDACTED>'),
    # Bearer tokens
    (re.compile(r'(Bearer\s+)([A-Za-z0-9._\-]{12,})', re.IGNORECASE), r'\1<REDACTED>'),
    # JWTs
    (re.compile(r'eyJ[A-Za-z0-9._\-]{20,}'), '<REDACTED_JWT>'),
]


def _redact(text: str) -> str:
    """Strip common secret patterns from text."""
    if not text:
        return text
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


def _safe_exc(exc: BaseException) -> str:
    """Format exception for audit log: Type: message, redacted + truncated."""
    rendered = f"{type(exc).__name__}: {exc}"
    return _redact(rendered)[:200]


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def _audit(event: str, **fields: Any) -> None:
    """Append JSONL audit record. Best-effort — never crashes trading.

    Every string field is redacted before writing.
    """
    try:
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        cleaned = {k: _redact(v) if isinstance(v, str) else v for k, v in fields.items()}
        record = {"event": event, "ts": time.time(), **cleaned}
        line = json.dumps(record, separators=(',', ':'))
        # Atomic append (no filelock — single writer per pod)
        with open(AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:
        log.debug("audit append failed: %s", exc)


# ---------------------------------------------------------------------------
# Session pickle invalidation
# ---------------------------------------------------------------------------
def invalidate_session_pickle(pickle_name: str | None = None) -> None:
    """Remove persisted robin_stocks session pickle.

    Forces fresh login on next call. If pickle_name is None, scans TOKEN_DIR
    for any phoenix_*.pickle files and removes them all.
    """
    if pickle_name:
        candidates = [TOKEN_DIR / f"{pickle_name}.pickle"]
    else:
        # Fallback: glob all Phoenix pickles
        candidates = list(TOKEN_DIR.glob("phoenix_*.pickle"))

    for p in candidates:
        try:
            if p.exists():
                p.unlink()
                _audit("session_pickle_invalidated", path=str(p))
                log.info("Invalidated session pickle: %s", p)
        except Exception as exc:
            _audit("session_pickle_invalidate_failed", path=str(p), error=_safe_exc(exc))


# ---------------------------------------------------------------------------
# Exponential backoff on auth failure
# ---------------------------------------------------------------------------
def record_auth_fail() -> None:
    """Increment fail counter and arm exponential backoff."""
    global _auth_fail_count, _backoff_until
    _auth_fail_count += 1
    delay_idx = min(_auth_fail_count - 1, len(BACKOFF_SCHEDULE) - 1)
    delay = BACKOFF_SCHEDULE[delay_idx]
    _backoff_until = time.time() + delay
    _audit("backoff_set", fail_count=_auth_fail_count, delay_s=delay)
    log.warning("Auth failure %d — backing off %d s", _auth_fail_count, delay)


def check_backoff() -> None:
    """Raise if currently in backoff period."""
    if time.time() < _backoff_until:
        wait = _backoff_until - time.time()
        raise RuntimeError(f"Robinhood auth in backoff for {wait:.0f}s more")


def reset_auth_fail_count() -> None:
    """Clear fail counter on successful auth."""
    global _auth_fail_count, _backoff_until
    _auth_fail_count = 0
    _backoff_until = 0.0


# ---------------------------------------------------------------------------
# Refresh helper (called by background task + on-demand)
# ---------------------------------------------------------------------------
async def refresh_session_light(username: str, pickle_name: str) -> None:
    """Cheap keep-alive: load user profile (no full login).

    robin_stocks requires an authenticated session. This is the lightest
    API call that exercises the auth path.
    """
    rh = _get_rh()

    def _do_refresh() -> None:
        # SelfAgentBot uses load_user_profile as the cheapest auth-required call
        rh.profiles.load_user_profile()

    await asyncio.to_thread(_do_refresh)
    _audit("refresh_ok", username=username)
