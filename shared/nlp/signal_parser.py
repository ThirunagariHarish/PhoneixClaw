"""
Signal parser — extracts buy/sell/close signals from trading messages.
Pairs entry signals with corresponding exit signals to form complete trades.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from shared.nlp.ticker_extractor import TickerExtractor

_extractor = TickerExtractor()

# ── Signal patterns ──────────────────────────────────────────────────────────

BUY_PATTERNS = [
    re.compile(r"\b(?:buy|bought|buying|long|entered|entry|going long|opening)\b", re.I),
    re.compile(r"\b(?:call|calls)\b.*\b(?:buy|bought|picked up|opened)\b", re.I),
    re.compile(r"\b(?:buy|bought|picked up|opened)\b.*\b(?:call|calls)\b", re.I),
    re.compile(r"BTO\b", re.I),  # Buy to Open
]

SELL_PATTERNS = [
    re.compile(r"\b(?:sell|sold|selling|short|exited|exit|closing|closed|going short)\b", re.I),
    re.compile(r"\b(?:put|puts)\b.*\b(?:buy|bought|picked up|opened)\b", re.I),
    re.compile(r"\b(?:buy|bought|picked up|opened)\b.*\b(?:put|puts)\b", re.I),
    re.compile(r"STC\b", re.I),  # Sell to Close
    re.compile(r"STO\b", re.I),  # Sell to Open
]

CLOSE_PATTERNS = [
    re.compile(r"\b(?:closed|out of|exited|took profit|stopped out|cut loss|trimmed)\b", re.I),
    re.compile(r"\b(?:target hit|target reached|SL hit|stop loss hit)\b", re.I),
]

PRICE_PATTERN = re.compile(
    r"(?:\$|@|at\s+)\s*(\d+(?:\.\d{1,2})?)"
)

OPTION_PATTERN = re.compile(
    r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2})\s*"
    r"(\d+(?:\.\d+)?)\s*([CcPp])",
)

PROFIT_PATTERN = re.compile(
    r"[+\-]?\s*\$?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*%?"
    r"|\b(\d+(?:\.\d{1,2})?)\s*%"
)


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
    """Parse a single message and classify its signal type."""
    tickers = _extractor.extract(content)
    primary = tickers[0] if tickers else None

    price = None
    pm = PRICE_PATTERN.search(content)
    if pm:
        try:
            price = float(pm.group(1))
        except (ValueError, TypeError):
            pass

    option_strike = None
    option_type = None
    option_expiry = None
    om = OPTION_PATTERN.search(content)
    if om:
        option_expiry = om.group(1)
        try:
            option_strike = float(om.group(2))
        except ValueError:
            pass
        option_type = om.group(3).upper()

    # Classify signal type with confidence scoring
    buy_score = sum(1 for p in BUY_PATTERNS if p.search(content))
    sell_score = sum(1 for p in SELL_PATTERNS if p.search(content))
    close_score = sum(1 for p in CLOSE_PATTERNS if p.search(content))

    if close_score > 0 and close_score >= buy_score:
        signal_type = "close_signal"
        confidence = min(0.9, 0.4 + close_score * 0.2)
    elif buy_score > sell_score:
        signal_type = "buy_signal"
        confidence = min(0.9, 0.3 + buy_score * 0.2)
    elif sell_score > buy_score:
        signal_type = "sell_signal"
        confidence = min(0.9, 0.3 + sell_score * 0.2)
    elif tickers:
        signal_type = "info"
        confidence = 0.3
    else:
        signal_type = "noise"
        confidence = 0.1

    if tickers:
        confidence += 0.1
    if price:
        confidence += 0.1

    return ParsedSignal(
        signal_type=signal_type,
        tickers=tickers,
        primary_ticker=primary,
        price=price,
        option_strike=option_strike,
        option_type=option_type,
        option_expiry=option_expiry,
        confidence=min(1.0, confidence),
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
