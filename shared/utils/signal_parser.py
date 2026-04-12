"""Intelligent multi-layer trade signal parser.

Parses raw Discord trade messages into structured signals using a three-layer approach:
  Layer 1: Structured regex patterns (fast, handles common formats)
  Layer 2: LLM-based parsing via ModelRouter (for complex/ambiguous messages)
  Layer 3: Validation and normalization

Usage:
    from shared.utils.signal_parser import parse_trade_signal, ParsedSignal
    result = parse_trade_signal("BTO AAPL 190c 4/18 @ 3.50")

Or async with LLM fallback:
    result = await parse_trade_signal_async("some complex message")
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ParsedSignal dataclass
# ---------------------------------------------------------------------------

@dataclass
class ParsedSignal:
    """Structured output from signal parsing."""

    ticker: Optional[str] = None
    direction: Optional[str] = None          # BUY or SELL
    asset_type: Optional[str] = None         # stock, call, put
    strike_price: Optional[float] = None
    expiry_date: Optional[str] = None        # YYYY-MM-DD
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    exit_pct: Optional[float] = None         # partial exit fraction 0-1
    confidence: float = 0.0
    parsing_method: str = "regex"            # regex, llm, hybrid
    raw_message: str = ""
    warnings: list[str] = field(default_factory=list)

    # Fields preserved for backward compat with shared/nlp/signal_parser.py
    signal_type: Optional[str] = None        # buy_signal, sell_signal, close_signal, info, noise
    tickers: list[str] = field(default_factory=list)
    primary_ticker: Optional[str] = None
    price: Optional[float] = None            # alias for entry_price
    option_strike: Optional[float] = None    # alias for strike_price
    option_type: Optional[str] = None        # C or P
    option_expiry: Optional[str] = None      # raw expiry string before normalization

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None and v != [] and v != ""}

    @property
    def is_actionable(self) -> bool:
        return self.signal_type in ("buy_signal", "sell_signal", "close_signal")

    @property
    def missing_fields(self) -> list[str]:
        """Return list of important fields that are missing."""
        missing = []
        if not self.ticker:
            missing.append("ticker")
        if not self.direction:
            missing.append("direction")
        if self.asset_type in ("call", "put"):
            if not self.strike_price:
                missing.append("strike_price")
            if not self.expiry_date:
                missing.append("expiry_date")
        if not self.entry_price:
            missing.append("entry_price")
        return missing


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Ticker: $AAPL or bare AAPL followed by option-like context
_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
_TICKER_OPTION_RE = re.compile(
    r"\b([A-Z]{1,5})\s+\$?\d+(?:\.\d+)?\s*[CcPp]",
)
_TICKER_BARE_RE = re.compile(r"\b([A-Z]{2,5})\b")

# Direction patterns
_BUY_RE = re.compile(
    r"\b(?:buy|bought|buying|long|entered|entry|going\s+long|opening|opened|"
    r"picked\s+up|grabbed|added|taking|bto|btc)\b",
    re.IGNORECASE,
)
_SELL_RE = re.compile(
    r"\b(?:sell|sold|selling|short|exited|exit|closing|closed|going\s+short|"
    r"trimmed?|trim|profit|out\s+of|stc|sto)\b",
    re.IGNORECASE,
)
_CLOSE_RE = re.compile(
    r"\b(?:closed|out\s+of|exited|took\s+profit|stopped\s+out|cut\s+loss|"
    r"target\s+hit|target\s+reached|sl\s+hit|stop\s+loss\s+hit)\b",
    re.IGNORECASE,
)

# Option strike+type: "190c", "190C", "$190 call", "190 calls", "$190C", "190.5P"
_STRIKE_TYPE_COMPACT_RE = re.compile(
    r"\$?(\d+(?:\.\d+)?)\s*([CcPp])\b"
)
_STRIKE_TYPE_WORD_RE = re.compile(
    r"\$?(\d+(?:\.\d+)?)\s+(?:calls?|puts?)\b",
    re.IGNORECASE,
)
# "call" / "calls" / "put" / "puts" without preceding strike (direction hint)
_OPTION_WORD_RE = re.compile(r"\b(calls?|puts?)\b", re.IGNORECASE)

# Expiry date patterns (multiple formats)
_EXPIRY_PATTERNS = [
    # "4/18/2025" or "4/18/25" or "4/18"
    re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b"),
    re.compile(r"\b(\d{1,2})[/-](\d{1,2})\b"),
    # "2025-04-18" ISO
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    # "Apr 18", "April 18", "Apr 18 2025", "April 18, 2025"
    re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
        r"(\d{1,2})(?:\s*,?\s*(\d{4}))?\b",
        re.IGNORECASE,
    ),
]

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Entry price patterns (ordered by specificity)
_ENTRY_PRICE_PATTERNS = [
    # "filled at 3.50", "in at 3.50", "entry 3.50", "avg 3.50", "entered at 3.50"
    re.compile(
        r"(?:filled|in\s+at|entry|avg|entered\s+at|got\s+in)\s*\$?([\d]+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    # "@ 3.50" or "@3.50"
    re.compile(r"@\s*\$?([\d]+(?:\.\d+)?)"),
    # "at $3.50" or "at 3.50" (but NOT "at 190" which is likely a strike)
    re.compile(r"\bat\s+\$?([\d]+(?:\.\d+)?)\b", re.IGNORECASE),
    # "for $3.50" or "for 3.50"
    re.compile(r"\bfor\s+\$?([\d]+(?:\.\d+)?)\b", re.IGNORECASE),
    # "price 3.50"
    re.compile(r"\bprice\s+\$?([\d]+(?:\.\d+)?)\b", re.IGNORECASE),
]

# Target / stop loss
_TARGET_RE = re.compile(
    r"(?:target|tp|take[\s.-]?profit|pt)\s*:?\s*\$?([\d]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_STOP_RE = re.compile(
    r"(?:stop|sl|stop[\s.-]?loss)\s*:?\s*\$?([\d]+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Exit percentage: "sold 50%", "trimmed 25%", "closed 75%"
_EXIT_PCT_RE = re.compile(
    r"(?:sold|trim(?:med)?|closed?|out)\s+(\d+)\s*%",
    re.IGNORECASE,
)

# Common words that look like tickers
_COMMON_WORDS = frozenset({
    "A", "I", "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN",
    "IS", "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "SO", "TO", "UP",
    "US", "WE", "DD", "CEO", "CFO", "CTO", "COO", "IPO", "ETF", "SEC",
    "GDP", "CPI", "ATH", "RSI", "EPS", "PE", "THE", "FOR",
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
    "PART", "REAL", "STOP", "HOLD", "PLAY", "BEAR", "BULL",
    "LEAP", "BUY", "SELL", "FILL", "YOLO", "MOON", "GAIN", "LOSS",
    "RISK", "FREE", "EDIT", "LINK", "POST", "CHAT", "LIVE",
    "NEWS", "SAVE", "HELP", "JOIN", "MOVE", "DONE", "NOTE", "INFO",
    "TEST", "PLUS", "GOLD", "CASH", "FUND", "RATE", "BANK", "BOND",
    "OTC", "IMO", "TBH", "FYI", "LOL", "WTF", "OMG", "SMH",
    "FOMO", "HODL", "BTFD", "TLDR", "IMHO",
    "IV", "OI", "GEX", "MAX", "MIN", "AVG", "VOL", "BID", "ASK",
})

# Known tickers loaded lazily
_known_tickers: set[str] | None = None


def _load_known_tickers() -> set[str]:
    """Load known tickers from shared/data/tickers.json (cached)."""
    global _known_tickers
    if _known_tickers is not None:
        return _known_tickers
    try:
        from pathlib import Path
        tickers_file = Path(__file__).resolve().parent.parent / "data" / "tickers.json"
        with open(tickers_file) as f:
            data = json.load(f)
        if isinstance(data, dict):
            _known_tickers = set(data.get("tickers", data.get("symbols", [])))
        elif isinstance(data, list):
            _known_tickers = set(data)
        else:
            _known_tickers = set()
    except Exception:
        _known_tickers = set()
    return _known_tickers


def _is_valid_ticker(symbol: str) -> bool:
    """Check if a symbol looks like a valid ticker.

    Accepts any 2-5 char uppercase alphabetic token that isn't a common English
    word. The known-tickers list is used for confidence scoring, not as a gate.
    """
    if symbol in _COMMON_WORDS:
        return False
    if len(symbol) <= 1 or len(symbol) > 5:
        return False
    if not symbol.isalpha() or not symbol.isupper():
        return False
    return True


# ---------------------------------------------------------------------------
# Layer 1: Regex parsing
# ---------------------------------------------------------------------------

def _extract_tickers(content: str) -> list[str]:
    """Extract ticker symbols from message content, ordered by confidence."""
    found: list[str] = []
    seen: set[str] = set()

    # Priority 1: Cashtags ($AAPL)
    for m in _CASHTAG_RE.finditer(content):
        t = m.group(1).upper()
        if t not in seen and _is_valid_ticker(t):
            found.append(t)
            seen.add(t)

    # Priority 2: Ticker followed by option info (AAPL 190C)
    for m in _TICKER_OPTION_RE.finditer(content):
        t = m.group(1).upper()
        if t not in seen and _is_valid_ticker(t):
            found.append(t)
            seen.add(t)

    # Priority 3: Bare uppercase tokens that are known tickers
    known = _load_known_tickers()
    for m in _TICKER_BARE_RE.finditer(content.upper()):
        t = m.group(1)
        if t not in seen and t not in _COMMON_WORDS and t in known:
            found.append(t)
            seen.add(t)

    return found


def _extract_direction(content: str) -> tuple[Optional[str], Optional[str]]:
    """Return (direction, signal_type) from content.

    direction: BUY or SELL
    signal_type: buy_signal, sell_signal, close_signal, info, noise
    """
    close_match = _CLOSE_RE.search(content)
    buy_match = _BUY_RE.search(content)
    sell_match = _SELL_RE.search(content)

    # Check for option direction keywords (calls = buy, puts can be buy-direction)
    has_call_word = bool(re.search(r"\bcalls?\b", content, re.IGNORECASE))
    has_put_word = bool(re.search(r"\bputs?\b", content, re.IGNORECASE))

    if close_match:
        return "SELL", "close_signal"
    if buy_match and not sell_match:
        return "BUY", "buy_signal"
    if sell_match and not buy_match:
        return "SELL", "sell_signal"
    if buy_match and sell_match:
        # Ambiguous -- lean towards sell (more cautious)
        return "SELL", "sell_signal"
    # If message mentions calls/puts with no explicit direction, infer BUY
    if has_call_word or has_put_word:
        return "BUY", "buy_signal"
    return None, None


def _extract_option_info(content: str) -> tuple[Optional[float], Optional[str], Optional[str]]:
    """Extract (strike, option_type_char, raw_expiry_str) from content.

    Returns option_type_char as 'C' or 'P'.
    """
    strike: Optional[float] = None
    opt_type: Optional[str] = None
    raw_expiry: Optional[str] = None

    # Try compact format: "190c", "190.5P", "$190C"
    m = _STRIKE_TYPE_COMPACT_RE.search(content)
    if m:
        strike = float(m.group(1))
        opt_type = "C" if m.group(2).upper() == "C" else "P"
    else:
        # Try word format: "$190 call", "190 puts"
        m2 = _STRIKE_TYPE_WORD_RE.search(content)
        if m2:
            strike = float(m2.group(1))
            # Determine type from the word following the number
            after = content[m2.end() - 5:m2.end() + 1].lower()
            if "call" in after:
                opt_type = "C"
            elif "put" in after:
                opt_type = "P"
        else:
            # Check for standalone "calls"/"puts" without strike
            wm = _OPTION_WORD_RE.search(content)
            if wm:
                word = wm.group(1).lower()
                if word.startswith("call"):
                    opt_type = "C"
                elif word.startswith("put"):
                    opt_type = "P"

    # Extract expiry date
    raw_expiry = _extract_raw_expiry(content)

    return strike, opt_type, raw_expiry


def _extract_raw_expiry(content: str) -> Optional[str]:
    """Extract raw expiry string from content."""
    # Try text month first: "Apr 18", "April 18 2025"
    text_month_re = re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
        r"(\d{1,2})(?:\s*,?\s*(\d{4}))?\b",
        re.IGNORECASE,
    )
    m = text_month_re.search(content)
    if m:
        return m.group(0)

    # ISO date: "2025-04-18"
    iso_re = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
    m = iso_re.search(content)
    if m:
        return m.group(1)

    # Numeric: "4/18/2025", "4/18/25", "4/18"
    num_re = re.compile(r"\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b")
    m = num_re.search(content)
    if m:
        return m.group(1)

    return None


def _normalize_expiry(raw: str, as_of_date: Optional[date] = None) -> Optional[str]:
    """Normalize raw expiry string to YYYY-MM-DD format."""
    if not raw:
        return None

    ref_year = (as_of_date or date.today()).year

    # ISO: "2025-04-18"
    iso_m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw.strip())
    if iso_m:
        return raw.strip()

    # Text month: "Apr 18", "April 18 2025", "Apr 18, 2025"
    text_m = re.match(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
        r"(\d{1,2})(?:\s*,?\s*(\d{4}))?",
        raw.strip(),
        re.IGNORECASE,
    )
    if text_m:
        month = _MONTH_MAP[text_m.group(1)[:3].lower()]
        day = int(text_m.group(2))
        year = int(text_m.group(3)) if text_m.group(3) else ref_year
        try:
            return f"{year}-{month:02d}-{day:02d}"
        except ValueError:
            return None

    # Numeric: "4/18/2025", "4/18/25", "4-18", "4/18"
    num_m = re.match(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$", raw.strip())
    if num_m:
        month = int(num_m.group(1))
        day = int(num_m.group(2))
        year_str = num_m.group(3)
        if year_str:
            year = int(year_str)
            if year < 100:
                year += 2000
        else:
            year = ref_year
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return f"{year}-{month:02d}-{day:02d}"
            except ValueError:
                return None

    return None


def _extract_entry_price(
    content: str,
    strike: Optional[float] = None,
    target: Optional[float] = None,
    stop: Optional[float] = None,
) -> Optional[float]:
    """Extract entry/fill price, disambiguating from strike/target/stop."""
    for pattern in _ENTRY_PRICE_PATTERNS:
        m = pattern.search(content)
        if m:
            val = float(m.group(1))
            # Disambiguate: skip if this matches the strike, target, or stop
            if strike and abs(val - strike) < 0.01:
                continue
            if target and abs(val - target) < 0.01:
                continue
            if stop and abs(val - stop) < 0.01:
                continue
            return val
    return None


def _extract_target(content: str) -> Optional[float]:
    m = _TARGET_RE.search(content)
    return float(m.group(1)) if m else None


def _extract_stop(content: str) -> Optional[float]:
    m = _STOP_RE.search(content)
    return float(m.group(1)) if m else None


def _extract_exit_pct(content: str) -> Optional[float]:
    m = _EXIT_PCT_RE.search(content)
    if m:
        return int(m.group(1)) / 100.0
    return None


def _compute_confidence(result: ParsedSignal) -> float:
    """Compute confidence score 0.0-1.0 based on how many fields were extracted."""
    score = 0.0

    if result.ticker:
        score += 0.20
    if result.direction:
        score += 0.15
    if result.entry_price:
        score += 0.20
    if result.asset_type in ("call", "put"):
        if result.strike_price:
            score += 0.15
        if result.expiry_date:
            score += 0.15
    elif result.asset_type == "stock" and result.ticker:
        # Stock trades need fewer fields but must have a ticker
        score += 0.15

    if result.stop_loss:
        score += 0.05
    if result.take_profit:
        score += 0.05

    # Bonus for known ticker
    known = _load_known_tickers()
    if result.ticker and known and result.ticker in known:
        score += 0.05

    return min(1.0, round(score, 2))


def parse_trade_signal(
    raw_message: str,
    as_of_date: Optional[date] = None,
) -> ParsedSignal:
    """Parse a raw Discord trade message into a structured signal (regex only, sync).

    This is the main entry point for synchronous parsing. For LLM fallback,
    use parse_trade_signal_async().
    """
    result = ParsedSignal(raw_message=raw_message)

    # --- Tickers ---
    tickers = _extract_tickers(raw_message)
    result.tickers = tickers
    result.primary_ticker = tickers[0] if tickers else None
    result.ticker = result.primary_ticker

    # --- Direction ---
    direction, signal_type = _extract_direction(raw_message)
    result.direction = direction
    result.signal_type = signal_type

    # If no signal type determined but we have tickers, mark as info
    if not result.signal_type:
        result.signal_type = "info" if tickers else "noise"

    # --- Options ---
    strike, opt_type, raw_expiry = _extract_option_info(raw_message)
    result.strike_price = strike
    result.option_strike = strike
    result.option_type = opt_type

    # Determine asset type
    if opt_type == "C":
        result.asset_type = "call"
    elif opt_type == "P":
        result.asset_type = "put"
    elif strike is not None:
        # Has strike but no explicit type -- default call (most common in Discord)
        result.asset_type = "call"
        result.option_type = "C"
    else:
        result.asset_type = "stock"

    # Normalize expiry
    result.option_expiry = raw_expiry
    result.expiry_date = _normalize_expiry(raw_expiry, as_of_date) if raw_expiry else None

    # --- Target & Stop (extract before price for disambiguation) ---
    result.take_profit = _extract_target(raw_message)
    result.stop_loss = _extract_stop(raw_message)

    # --- Entry price ---
    result.entry_price = _extract_entry_price(
        raw_message,
        strike=result.strike_price,
        target=result.take_profit,
        stop=result.stop_loss,
    )
    result.price = result.entry_price

    # --- Exit percentage ---
    result.exit_pct = _extract_exit_pct(raw_message)

    # --- Confidence ---
    result.confidence = _compute_confidence(result)
    result.parsing_method = "regex"

    return result


# ---------------------------------------------------------------------------
# Layer 2: LLM-based parsing (async, for low-confidence parses)
# ---------------------------------------------------------------------------

# Simple in-memory LRU cache for LLM parses
_llm_cache: dict[str, ParsedSignal] = {}
_LLM_CACHE_MAX = 500

_LLM_SYSTEM_PROMPT = """You are a trade signal parser. Extract structured data from Discord trading messages.
Return ONLY valid JSON with these fields (use null for missing values):
{
  "ticker": "AAPL",
  "direction": "BUY or SELL",
  "asset_type": "stock, call, or put",
  "strike_price": 190.0,
  "expiry_date": "2025-04-18",
  "entry_price": 3.50,
  "stop_loss": 3.00,
  "take_profit": 5.00,
  "confidence": 0.85
}
Rules:
- ticker: US equity ticker symbol (uppercase, no $)
- direction: BUY for buy/long/BTO/calls bought, SELL for sell/short/STC/close/trim
- expiry_date: always YYYY-MM-DD format
- entry_price: the fill/entry price, NOT the strike price
- confidence: 0.0-1.0 how confident you are in the parse
- If the message is noise/info (not a trade signal), return {"ticker": null, "direction": null, "confidence": 0.1}
"""


async def _llm_parse(raw_message: str) -> Optional[dict]:
    """Call LLM to parse a signal message. Returns parsed dict or None."""
    cache_key = hashlib.md5(raw_message.encode()).hexdigest()
    if cache_key in _llm_cache:
        return None  # Will use cached ParsedSignal directly

    try:
        from shared.utils.model_router import get_router
        router = get_router()
        resp = await router.complete(
            task_type="data_format",
            prompt=f"Parse this Discord trade signal message:\n\n{raw_message}",
            system=_LLM_SYSTEM_PROMPT,
            temperature=0.0,
            max_tokens=256,
            json_mode=True,
        )
        await router.close()

        text = resp.text.strip()
        # Handle markdown code blocks
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        parsed = json.loads(text)
        return parsed
    except Exception as e:
        logger.warning("LLM signal parsing failed: %s", e)
        return None


def _merge_llm_result(base: ParsedSignal, llm_data: dict) -> ParsedSignal:
    """Merge LLM-parsed fields into base result, filling gaps only."""
    merged = ParsedSignal(**{k: v for k, v in base.__dict__.items()})
    merged.parsing_method = "hybrid"

    # Only fill in missing fields from LLM
    if not merged.ticker and llm_data.get("ticker"):
        merged.ticker = llm_data["ticker"].upper()
        merged.primary_ticker = merged.ticker
        if merged.ticker not in merged.tickers:
            merged.tickers = [merged.ticker] + merged.tickers

    if not merged.direction and llm_data.get("direction"):
        d = llm_data["direction"].upper()
        if d in ("BUY", "SELL"):
            merged.direction = d
            if d == "BUY":
                merged.signal_type = "buy_signal"
            else:
                merged.signal_type = "sell_signal"

    if not merged.asset_type and llm_data.get("asset_type"):
        at = llm_data["asset_type"].lower()
        if at in ("stock", "call", "put"):
            merged.asset_type = at
            if at == "call":
                merged.option_type = "C"
            elif at == "put":
                merged.option_type = "P"

    if not merged.strike_price and llm_data.get("strike_price"):
        try:
            merged.strike_price = float(llm_data["strike_price"])
            merged.option_strike = merged.strike_price
        except (ValueError, TypeError):
            pass

    if not merged.expiry_date and llm_data.get("expiry_date"):
        exp = llm_data["expiry_date"]
        # Validate format
        if re.match(r"^\d{4}-\d{2}-\d{2}$", str(exp)):
            merged.expiry_date = exp
            merged.option_expiry = exp

    if not merged.entry_price and llm_data.get("entry_price"):
        try:
            merged.entry_price = float(llm_data["entry_price"])
            merged.price = merged.entry_price
        except (ValueError, TypeError):
            pass

    if not merged.stop_loss and llm_data.get("stop_loss"):
        try:
            merged.stop_loss = float(llm_data["stop_loss"])
        except (ValueError, TypeError):
            pass

    if not merged.take_profit and llm_data.get("take_profit"):
        try:
            merged.take_profit = float(llm_data["take_profit"])
        except (ValueError, TypeError):
            pass

    # Recompute confidence as max of regex + LLM confidence
    llm_conf = float(llm_data.get("confidence", 0.5))
    merged.confidence = max(merged.confidence, _compute_confidence(merged), llm_conf)

    return merged


async def parse_trade_signal_async(
    raw_message: str,
    as_of_date: Optional[date] = None,
    llm_threshold: float = 0.5,
) -> ParsedSignal:
    """Parse with regex first, then LLM fallback if confidence is below threshold.

    Args:
        raw_message: The raw Discord message text.
        as_of_date: Reference date for expiry year inference.
        llm_threshold: If regex confidence < this, call LLM for help.
    """
    # Layer 1: Regex
    result = parse_trade_signal(raw_message, as_of_date=as_of_date)

    # Check LLM cache first
    cache_key = hashlib.md5(raw_message.encode()).hexdigest()
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    # Layer 2: LLM fallback if regex confidence is low or key fields missing
    needs_llm = (
        result.confidence < llm_threshold
        or (result.is_actionable and len(result.missing_fields) > 0)
    )

    if needs_llm:
        llm_data = await _llm_parse(raw_message)
        if llm_data:
            result = _merge_llm_result(result, llm_data)

            # Cache the result
            if len(_llm_cache) >= _LLM_CACHE_MAX:
                # Evict oldest entry
                oldest = next(iter(_llm_cache))
                del _llm_cache[oldest]
            _llm_cache[cache_key] = result

    return result


# ---------------------------------------------------------------------------
# Backward-compatible wrappers
# ---------------------------------------------------------------------------

def parse_signal_compat(raw_signal: dict) -> dict:
    """Drop-in replacement for live-trader-v1/tools/parse_signal.py::parse().

    Accepts the same raw_signal dict and returns the same output format.
    """
    content = raw_signal.get("content", "")
    parsed = parse_trade_signal(content)

    result: dict = {
        "raw_content": content,
        "author": raw_signal.get("author", "unknown"),
        "timestamp": raw_signal.get("timestamp", datetime.now().isoformat()),
        "message_id": raw_signal.get("message_id"),
        "channel_id": raw_signal.get("channel_id"),
    }

    if parsed.ticker:
        result["ticker"] = parsed.ticker
    else:
        logger.warning("No ticker extracted from: %s", content[:200])
    if parsed.entry_price is not None:
        result["signal_price"] = parsed.entry_price
    if parsed.direction:
        result["direction"] = parsed.direction.lower()
    if parsed.strike_price is not None:
        result["strike"] = parsed.strike_price
    if parsed.option_type:
        result["option_type"] = "call" if parsed.option_type == "C" else "put"
    if parsed.expiry_date:
        result["expiry"] = parsed.expiry_date

    return result


def parse_signal_transform_compat(content: str, posted_at: datetime) -> Optional[dict]:
    """Drop-in replacement for backtesting/tools/transform.py::parse_signal().

    Returns the same dict format used by the transform pipeline.
    """
    parsed = parse_trade_signal(content)

    if not parsed.ticker:
        return None
    if parsed.signal_type not in ("buy_signal", "sell_signal", "close_signal"):
        return None

    signal_type = "buy" if parsed.direction == "BUY" else "sell"
    trade_type = "option" if parsed.asset_type in ("call", "put") else "stock"

    return {
        "ticker": parsed.ticker,
        "signal_type": signal_type,
        "price": parsed.entry_price,
        "option_type": "call" if parsed.option_type == "C" else ("put" if parsed.option_type == "P" else None),
        "strike": parsed.strike_price,
        "expiry": parsed.expiry_date,  # Already normalized to YYYY-MM-DD
        "exit_pct": parsed.exit_pct,
        "target": parsed.take_profit,
        "stop_loss": parsed.stop_loss,
        "trade_type": trade_type,
        "timestamp": posted_at,
        "raw_message": content,
    }
