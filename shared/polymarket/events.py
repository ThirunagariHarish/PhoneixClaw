"""Polymarket event-bus topic constants (Phase 3, Polymarket v1.0).

Centralized so producers (RTDS websocket) and consumers (ws-gateway,
strategy agents, monitors) cannot drift on stream names.

Reference: docs/architecture/polymarket-tab.md section 9, Phase 3 and
section "9. Phased Technical Implementation Plan".
"""

from __future__ import annotations

# Redis Streams topics. Prefix `stream:pm:` is reserved for Polymarket
# v1.0 event traffic and intentionally distinct from existing Phoenix
# streams (`stream:trade-intents`, `stream:position-updates`, ...).

# Normalized order-book updates emitted by the RTDS websocket client.
PM_BOOKS_STREAM = "stream:pm:books"

# Discovery scanner output (Phase 4).
PM_MARKETS_STREAM = "stream:pm:markets"

# Per-market resync notifications (sequence-gap recoveries, reconnects).
PM_RESYNC_STREAM = "stream:pm:resync"

# RTDS connection / health events (status, errors, mttr telemetry).
PM_RTDS_STATUS_STREAM = "stream:pm:rtds-status"


__all__ = [
    "PM_BOOKS_STREAM",
    "PM_MARKETS_STREAM",
    "PM_RESYNC_STREAM",
    "PM_RTDS_STATUS_STREAM",
]
