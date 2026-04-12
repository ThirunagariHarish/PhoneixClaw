"""
Signal parser — extracts buy/sell/close signals from trading messages.
Pairs entry signals with corresponding exit signals to form complete trades.

NOTE: Signal parsing is now delegated to the shared intelligent parser at
shared.utils.signal_parser. This module maintains the same public API
(ParsedSignal, parse_signal, MessageSignal, TradePair, pair_trades) for
backward compatibility with existing consumers.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Import the intelligent parser
from shared.utils.signal_parser import parse_trade_signal as _parse_trade_signal


@dataclass
class ParsedSignal:
    """A parsed trading signal from a message."""
    signal_type: str  # buy_signal, sell_signal, close_signal, info, noise
    tickers: list[str] = field(default_factory=list)
    primary_ticker: Optional[str] = None
    price: Optional[float] = None
    option_strike: Optional[float] = None
    option_type: Optional[str] = None  # C or P
    option_expiry: Optional[str] = None
    confidence: float = 0.0


@dataclass
class TradePair:
    """A complete trade: entry + exit."""
    ticker: str
    entry_signal: "MessageSignal"
    exit_signal: Optional["MessageSignal"] = None
    side: str = "long"  # long or short


@dataclass
class MessageSignal:
    """Signal with its source message metadata."""
    message_id: str
    author: str
    content: str
    posted_at: datetime
    parsed: ParsedSignal


def parse_signal(content: str) -> ParsedSignal:
    """Parse a single message and classify its signal type.

    Delegates to the shared intelligent parser for robust multi-format
    support including text-month expiry dates, price disambiguation,
    and expanded direction detection.
    """
    result = _parse_trade_signal(content)

    # Map back to this module's ParsedSignal dataclass for compatibility
    return ParsedSignal(
        signal_type=result.signal_type or "noise",
        tickers=result.tickers,
        primary_ticker=result.primary_ticker,
        price=result.entry_price,
        option_strike=result.strike_price,
        option_type=result.option_type,
        option_expiry=result.option_expiry if result.option_expiry else result.expiry_date,
        confidence=result.confidence,
    )


def pair_trades(signals: list[MessageSignal]) -> list[TradePair]:
    """
    Pair buy/sell signals into complete trades.
    Uses a simple FIFO matching: earliest unmatched buy for a ticker
    is paired with the next sell/close for that ticker.
    """
    sorted_signals = sorted(signals, key=lambda s: s.posted_at)

    open_positions: dict[str, list[MessageSignal]] = {}
    trades: list[TradePair] = []

    for sig in sorted_signals:
        ticker = sig.parsed.primary_ticker
        if not ticker:
            continue

        if sig.parsed.signal_type == "buy_signal":
            open_positions.setdefault(ticker, []).append(sig)

        elif sig.parsed.signal_type in ("sell_signal", "close_signal"):
            if ticker in open_positions and open_positions[ticker]:
                entry = open_positions[ticker].pop(0)
                trades.append(TradePair(
                    ticker=ticker,
                    entry_signal=entry,
                    exit_signal=sig,
                    side="long",
                ))
            else:
                open_positions.setdefault(ticker, []).append(sig)

    return trades
