"""PolymarketBroker connector package (Phase 2, Polymarket v1.0).

See docs/architecture/polymarket-tab.md section 9, Phase 2.
"""

from .adapter import PolymarketBroker
from .clob_client import ClobClient
from .gamma_client import GammaClient
from .rtds_ws import BackoffPolicy, RtdsWebSocketClient
from .sequence_gap import (
    BookSnapshot,
    BookStateError,
    OrderBookState,
    PriceLevel,
    SequenceGapError,
)

__all__ = [
    "BackoffPolicy",
    "BookSnapshot",
    "BookStateError",
    "ClobClient",
    "GammaClient",
    "OrderBookState",
    "PolymarketBroker",
    "PriceLevel",
    "RtdsWebSocketClient",
    "SequenceGapError",
]
