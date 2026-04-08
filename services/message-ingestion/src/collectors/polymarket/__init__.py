"""
Polymarket-specific news collectors (Phase 14).

Brand-new collectors per user decision #7. These are intentionally NOT
reusing the generic twitter/reddit/discord adapters in
``services/message-ingestion/src/`` — they target Polymarket-relevant
breaking news only and publish to a dedicated Redis stream (``pm:news``)
that the future F6 news reactor (v1.2) will consume.

v1.0 is pure ingestion: collectors poll public RSS/JSON endpoints,
normalize items into :class:`PMNewsItem`, deduplicate within a process,
and publish to ``pm:news`` with a per-category sub-key. No LLM scoring,
no order routing, no consumer side.
"""

from .base import BasePMNewsCollector, PMNewsItem
from .crypto import CryptoNewsCollector
from .election import ElectionNewsCollector
from .macro import MacroNewsCollector
from .publisher import PMNewsPublisher
from .sports import SportsNewsCollector

__all__ = [
    "BasePMNewsCollector",
    "PMNewsItem",
    "PMNewsPublisher",
    "ElectionNewsCollector",
    "SportsNewsCollector",
    "MacroNewsCollector",
    "CryptoNewsCollector",
]
