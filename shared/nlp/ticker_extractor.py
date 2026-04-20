"""
Ticker symbol extraction from unstructured text.

Uses regex patterns and a known-ticker lookup against shared/data/tickers.json
to identify stock/ETF symbols in messages.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_TICKERS_FILE = Path(__file__).resolve().parent.parent / "data" / "tickers.json"

_COMMON_WORDS = frozenset({
    "A", "I", "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN",
    "IS", "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "SO", "TO", "UP",
    "US", "WE", "DD", "CEO", "CFO", "CTO", "COO", "IPO", "ETF", "SEC",
    "GDP", "CPI", "ATH", "RSI", "EPS", "P", "C", "PE", "THE", "FOR",
    "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER", "WAS", "ONE", "OUR",
    "OUT", "DAY", "HAD", "HAS", "HIS", "HOW", "ITS", "LET", "MAY", "NEW",
    "NOW", "OLD", "SEE", "WAY", "WHO", "BOY", "DID", "GET", "HIM", "HIT",
    "HOT", "LOW", "RUN", "TOP", "RED", "BIG", "END", "FAR", "FEW", "GOT",
    "MAN", "RAN", "SAY", "SHE", "TOO", "USE", "SET", "TRY", "ASK",
    "MEN", "PUT", "SAT", "ANY", "YET", "LOT", "JUST", "ALSO", "GOOD",
    "VERY", "BEEN", "CALL", "COME", "LIKE", "LONG", "LOOK", "MAKE",
    "MANY", "MUCH", "MUST", "NEED", "ONLY", "OVER", "SUCH", "TAKE",
    "TELL", "THAN", "THAT", "THEM", "THEN", "THIS", "WANT", "WELL",
    "WILL", "WITH", "WORK", "FROM", "HAVE", "BEEN", "INTO", "JUST",
    "EVEN", "BACK", "SOME", "WHAT", "WHEN", "YOUR", "HERE", "THEY",
    "SAID", "EACH", "TIME", "VERY", "MADE", "FIND", "MORE", "DOWN",
    "SIDE", "HIGH", "NEXT", "OPEN", "BEST", "LAST", "KEEP", "STILL",
    "PART", "REAL", "STOP", "HOLD", "PLAY", "BEAR", "BULL", "LONG",
    "LEAP", "BUY", "SELL", "FILL", "YOLO", "MOON", "GAIN", "LOSS",
    "HOLD", "RISK", "FREE", "EDIT", "LINK", "POST", "CHAT", "LIVE",
    "NEWS", "SAVE", "HELP", "JOIN", "MOVE", "DONE", "NOTE", "INFO",
    "TEST", "PLUS", "GOLD", "CASH", "FUND", "RATE", "BANK", "BOND",
    "OTC", "IMO", "TBH", "FYI", "LOL", "WTF", "OMG", "SMH",
    "FOMO", "HODL", "BTFD", "YOLO", "MOASS", "TLDR", "IMHO",
    "IV", "OI", "GEX", "MAX", "MIN", "AVG", "VOL", "BID", "ASK",
})

_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
_TICKER_TOKEN_RE = re.compile(r"\b([A-Z]{1,5})\b")
_TICKER_WITH_OPTION_RE = re.compile(
    r"\b([A-Z]{1,5})\s+\$?\d+(?:\.\d+)?\s*[CcPp]",
)

_known_tickers: set[str] | None = None


def _load_known_tickers() -> set[str]:
    global _known_tickers
    if _known_tickers is not None:
        return _known_tickers
    try:
        with open(_TICKERS_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            _known_tickers = set(data)
        elif isinstance(data, dict):
            _known_tickers = set(data.get("tickers", data.get("symbols", [])))
        else:
            _known_tickers = set()
        logger.info("Loaded %d known tickers", len(_known_tickers))
    except FileNotFoundError:
        logger.warning("tickers.json not found at %s, using empty set", _TICKERS_FILE)
        _known_tickers = set()
    except Exception as e:
        logger.error("Error loading tickers.json: %s", e)
        _known_tickers = set()
    return _known_tickers


class TickerExtractor:
    """Extract ticker symbols from unstructured text messages."""

    def __init__(self, extra_tickers: set[str] | None = None):
        self.known = _load_known_tickers()
        if extra_tickers:
            self.known = self.known | extra_tickers

    def extract(self, text: str) -> list[str]:
        """Return deduplicated list of ticker symbols found in text, ordered by appearance."""
        found: list[str] = []
        seen: set[str] = set()

        for m in _CASHTAG_RE.finditer(text):
            t = m.group(1)
            if t not in seen and self._is_valid_ticker(t):
                found.append(t)
                seen.add(t)

        for m in _TICKER_WITH_OPTION_RE.finditer(text):
            t = m.group(1)
            if t not in seen and self._is_valid_ticker(t):
                found.append(t)
                seen.add(t)

        upper = text.upper()
        for m in _TICKER_TOKEN_RE.finditer(upper):
            t = m.group(1)
            if t not in seen and t not in _COMMON_WORDS and self._is_valid_ticker(t):
                found.append(t)
                seen.add(t)

        return found

    def extract_primary(self, text: str) -> str | None:
        """Return the single most likely ticker from the text, or None."""
        tickers = self.extract(text)
        return tickers[0] if tickers else None

    def _is_valid_ticker(self, symbol: str) -> bool:
        if symbol in _COMMON_WORDS:
            return False
        if self.known and symbol in self.known:
            return True
        if len(symbol) <= 1:
            return False
        return len(self.known) == 0
