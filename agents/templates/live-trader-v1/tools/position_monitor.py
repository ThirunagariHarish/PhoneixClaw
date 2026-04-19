"""Daemon that monitors open positions with TA-based hold/close decisions."""

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("position_monitor")

PARTIAL_EXIT_LADDER = [
    {"threshold_pct": 20.0, "close_pct": 30.0},
    {"threshold_pct": 30.0, "close_pct": 50.0},
]
TRAILING_STOP_ACTIVATION_PCT = 10.0
TRAILING_STOP_TRAIL_RATIO = 0.70

TICK_FAST = 60
TICK_TA = 300
TICK_CONVICTION = 900

# T4: cadence override by predicted exit bucket. Short-hold trades poll fast;
# swing trades poll slower to save CPU and API quota.
EXIT_BUCKET_CADENCE = {
    "lt_5m":   {"fast": 10,  "ta": 60,   "conviction": 180},
    "5_30m":   {"fast": 30,  "ta": 180,  "conviction": 600},
    "30m_2h":  {"fast": 60,  "ta": 300,  "conviction": 900},
    "2h_eod":  {"fast": 120, "ta": 600,  "conviction": 1800},
    "next_day":{"fast": 300, "ta": 1200, "conviction": 3600},
}


def cadence_for_bucket(bucket: str | None) -> tuple[int, int, int]:
    cfg = EXIT_BUCKET_CADENCE.get(bucket or "30m_2h", EXIT_BUCKET_CADENCE["30m_2h"])
    return cfg["fast"], cfg["ta"], cfg["conviction"]


def _now_et() -> datetime:
    """Return current time in US/Eastern (offset-aware)."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York"))


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------

def fetch_price(ticker: str) -> Optional[float]:
    """Get the latest price for *ticker* via yfinance."""
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        hist = t.history(period="1d", interval="1m")
        if hist.empty:
            hist = t.history(period="5d", interval="5m")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as exc:
        log.warning("price fetch failed for %s: %s", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# Technical analysis helpers
# ---------------------------------------------------------------------------

def _ta_indicators(ticker: str, period: str = "5d", interval: str = "5m") -> Optional[dict]:
    """Compute RSI, MACD, Bollinger Bands, and volume analysis."""
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if hist.empty or len(hist) < 26:
            return None

        close = hist["Close"].values.astype(float)
        volume = hist["Volume"].values.astype(float)

        # RSI-14
        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])
        rs = avg_gain / avg_loss if avg_loss != 0 else 100.0
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # MACD (12/26/9)
        ema12 = _ema(close, 12)
        ema26 = _ema(close, 26)
        macd_line = ema12 - ema26
        signal_line = _ema_from_series(macd_line, 9)
        macd_histogram = macd_line[-1] - signal_line[-1]
        macd_bullish = macd_line[-1] > signal_line[-1]

        # Bollinger Bands (20, 2σ)
        window = min(20, len(close))
        sma20 = np.mean(close[-window:])
        std20 = np.std(close[-window:])
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        bb_pct = (close[-1] - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5

        # Volume vs 20-bar average
        vol_avg = np.mean(volume[-window:]) if len(volume) >= window else np.mean(volume)
        vol_ratio = volume[-1] / vol_avg if vol_avg > 0 else 1.0

        return {
            "rsi": round(float(rsi), 2),
            "macd_line": round(float(macd_line[-1]), 4),
            "macd_signal": round(float(signal_line[-1]), 4),
            "macd_histogram": round(float(macd_histogram), 4),
            "macd_bullish": bool(macd_bullish),
            "bb_upper": round(float(bb_upper), 2),
            "bb_lower": round(float(bb_lower), 2),
            "bb_pct": round(float(bb_pct), 4),
            "volume_ratio": round(float(vol_ratio), 2),
            "last_close": round(float(close[-1]), 2),
        }
    except Exception as exc:
        log.warning("TA computation failed for %s: %s", ticker, exc)
        return None


def _ema(data: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    out = np.empty_like(data, dtype=float)
    out[0] = data[0]
    for i in range(1, len(data)):
        out[i] = alpha * data[i] + (1 - alpha) * out[i - 1]
    return out


def _ema_from_series(data: np.ndarray, span: int) -> np.ndarray:
    return _ema(data, span)


# ---------------------------------------------------------------------------
# Position state management
# ---------------------------------------------------------------------------

class PositionState:
    """Runtime state tracked per open position."""

    def __init__(self, pos: dict):
        self.ticker: str = pos["ticker"]
        self.direction: str = pos.get("direction", "long")
        self.entry_price: float = float(pos["entry_price"])
        self.quantity: float = float(pos["quantity"])
        self.original_quantity: float = float(pos.get("original_quantity", pos["quantity"]))
        self.entry_time: str = pos.get("entry_time", datetime.utcnow().isoformat())
        self.is_0dte: bool = pos.get("is_0dte", False)

        self.max_price: float = float(pos.get("max_price", self.entry_price))
        self.trailing_stop: Optional[float] = pos.get("trailing_stop")
        self.partial_exits_done: list[float] = pos.get("partial_exits_done", [])
        self.last_ta: Optional[dict] = None
        self.conviction: str = pos.get("conviction", "medium")

    def pnl_pct(self, current_price: float) -> float:
        if self.direction == "long":
            return ((current_price - self.entry_price) / self.entry_price) * 100
        return ((self.entry_price - current_price) / self.entry_price) * 100

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "original_quantity": self.original_quantity,
            "entry_time": self.entry_time,
            "is_0dte": self.is_0dte,
            "max_price": self.max_price,
            "trailing_stop": self.trailing_stop,
            "partial_exits_done": self.partial_exits_done,
            "conviction": self.conviction,
        }


# ---------------------------------------------------------------------------
# Core monitoring logic
# ---------------------------------------------------------------------------

class PositionMonitor:
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.base_dir = self.config_path.parent
        self.config: dict = {}
        self.positions: list[PositionState] = []
        self._shutdown = False
        self._closed_today: list[dict] = []

    def reload_config(self) -> None:
        self.config = _load_json(self.config_path)

    @property
    def is_swing(self) -> bool:
        return self.config.get("is_swing_trader", False)

    def _portfolio_path(self) -> Path:
        return self.base_dir / "portfolio.json"

    def _signals_path(self) -> Path:
        return self.base_dir / "pending_signals.json"

    def load_positions(self) -> None:
        data = _load_json(self._portfolio_path())
        raw = data.get("positions", [])
        self.positions = [PositionState(p) for p in raw]
        log.info("loaded %d open positions", len(self.positions))

    def save_positions(self) -> None:
        data = _load_json(self._portfolio_path())
        data["positions"] = [p.to_dict() for p in self.positions]
        data["last_updated"] = datetime.utcnow().isoformat()
        _save_json(self._portfolio_path(), data)

    # -- fast tick (60s) ---------------------------------------------------

    def tick_fast(self) -> None:
        for pos in list(self.positions):
            price = fetch_price(pos.ticker)
            if price is None:
                continue

            pnl = pos.pnl_pct(price)
            log.debug("%s  price=%.2f  pnl=%.1f%%", pos.ticker, price, pnl)

            if pos.direction == "long":
                pos.max_price = max(pos.max_price, price)
            else:
                pos.max_price = min(pos.max_price, price)

            self._update_trailing_stop(pos, price, pnl)

            if self._check_trailing_stop_hit(pos, price):
                self._close_position(pos, price, "trailing_stop")
                continue

            self._check_partial_exits(pos, price, pnl)

        self.save_positions()

    def _update_trailing_stop(self, pos: PositionState, price: float, pnl: float) -> None:
        if pnl < TRAILING_STOP_ACTIVATION_PCT:
            return

        max_profit = pos.pnl_pct(pos.max_price)
        trail_pnl = max_profit * TRAILING_STOP_TRAIL_RATIO

        if pos.direction == "long":
            new_stop = pos.entry_price * (1 + trail_pnl / 100)
        else:
            new_stop = pos.entry_price * (1 - trail_pnl / 100)

        if pos.trailing_stop is None:
            pos.trailing_stop = new_stop
            log.info("%s trailing stop activated at %.2f", pos.ticker, new_stop)
        elif pos.direction == "long" and new_stop > pos.trailing_stop:
            pos.trailing_stop = new_stop
        elif pos.direction == "short" and new_stop < pos.trailing_stop:
            pos.trailing_stop = new_stop

    def _check_trailing_stop_hit(self, pos: PositionState, price: float) -> bool:
        if pos.trailing_stop is None:
            return False
        if pos.direction == "long" and price <= pos.trailing_stop:
            return True
        if pos.direction == "short" and price >= pos.trailing_stop:
            return True
        return False

    def _check_partial_exits(self, pos: PositionState, price: float, pnl: float) -> None:
        for level in PARTIAL_EXIT_LADDER:
            thr = level["threshold_pct"]
            if thr in pos.partial_exits_done:
                continue
            if pnl >= thr:
                close_frac = level["close_pct"] / 100.0
                close_qty = pos.original_quantity * close_frac
                close_qty = min(close_qty, pos.quantity)
                if close_qty <= 0:
                    continue
                pos.partial_exits_done.append(thr)
                pos.quantity -= close_qty
                log.info(
                    "%s partial exit %.0f%% at pnl=%.1f%% — closed %.2f shares, %.2f remaining",
                    pos.ticker, level["close_pct"], pnl, close_qty, pos.quantity,
                )
                self._record_close(pos, price, f"partial_{int(thr)}pct", close_qty)

                if pos.quantity <= 0:
                    self._remove_position(pos)

    # -- TA tick (5 min) ---------------------------------------------------

    def tick_ta(self) -> None:
        for pos in list(self.positions):
            ta = _ta_indicators(pos.ticker)
            if ta is None:
                continue
            pos.last_ta = ta
            log.info(
                "%s TA: RSI=%.1f MACD_bull=%s BB%%=%.2f Vol=%.1fx",
                pos.ticker, ta["rsi"], ta["macd_bullish"], ta["bb_pct"], ta["volume_ratio"],
            )
            self._ta_hold_or_close(pos, ta)

    def _ta_hold_or_close(self, pos: PositionState, ta: dict) -> None:
        """When approaching profit target, decide HOLD vs CLOSE."""
        price = ta["last_close"]
        pnl = pos.pnl_pct(price)

        if pnl < 15.0:
            return

        rsi_ok = ta["rsi"] < 70
        macd_ok = ta["macd_bullish"]

        if rsi_ok and macd_ok:
            log.info("%s TA says HOLD (RSI=%.1f < 70, MACD bullish)", pos.ticker, ta["rsi"])
        else:
            reasons = []
            if not rsi_ok:
                reasons.append(f"RSI={ta['rsi']:.1f}>=70")
            if not macd_ok:
                reasons.append("MACD bearish")
            log.info("%s TA says CLOSE — %s", pos.ticker, ", ".join(reasons))
            self._close_position(pos, price, f"ta_exit({', '.join(reasons)})")

    # -- conviction tick (15 min) ------------------------------------------

    def tick_conviction(self) -> None:
        for pos in self.positions:
            ta = pos.last_ta or _ta_indicators(pos.ticker)
            if ta is None:
                continue

            price = ta["last_close"]
            pnl = pos.pnl_pct(price)

            if ta["rsi"] > 75 and not ta["macd_bullish"]:
                pos.conviction = "low"
            elif ta["rsi"] < 50 and ta["macd_bullish"] and pnl > 0:
                pos.conviction = "high"
            else:
                pos.conviction = "medium"

            log.info("%s conviction=%s (pnl=%.1f%%)", pos.ticker, pos.conviction, pnl)

    # -- analyst action monitoring -----------------------------------------

    def check_pending_signals(self) -> None:
        signals = _load_json(self._signals_path())
        if not signals:
            return

        actions = signals.get("actions", [])
        remaining = []
        for action in actions:
            action_type = action.get("action", "").lower()
            ticker = action.get("ticker", "").upper()
            if action_type in ("sell", "trim", "close"):
                pos = next((p for p in self.positions if p.ticker == ticker), None)
                if pos:
                    price = fetch_price(ticker)
                    if price is not None:
                        label = f"analyst_{action_type}"
                        if action_type == "trim":
                            trim_qty = min(pos.quantity * 0.5, pos.quantity)
                            pos.quantity -= trim_qty
                            self._record_close(pos, price, label, trim_qty)
                            log.info("%s analyst TRIM — closed %.2f", ticker, trim_qty)
                            if pos.quantity <= 0:
                                self._remove_position(pos)
                        else:
                            self._close_position(pos, price, label)
                    continue
            remaining.append(action)

        signals["actions"] = remaining
        _save_json(self._signals_path(), signals)

    # -- EOD auto-close ----------------------------------------------------

    def check_eod_close(self) -> None:
        if self.is_swing:
            return

        now = _now_et()
        cutoff = now.replace(hour=15, minute=55, second=0, microsecond=0)
        if now < cutoff:
            return

        for pos in list(self.positions):
            if not pos.is_0dte:
                continue
            price = fetch_price(pos.ticker)
            if price is not None:
                log.info("%s EOD auto-close (0DTE, 3:55 PM ET)", pos.ticker)
                self._close_position(pos, price, "eod_auto_close")

    # -- helpers -----------------------------------------------------------

    def _close_position(self, pos: PositionState, price: float, reason: str) -> None:
        self._record_close(pos, price, reason, pos.quantity)
        self._remove_position(pos)

    def _remove_position(self, pos: PositionState) -> None:
        self.positions = [p for p in self.positions if p.ticker != pos.ticker]

    def _record_close(self, pos: PositionState, price: float, reason: str, qty: float) -> None:
        pnl = pos.pnl_pct(price)
        record = {
            "ticker": pos.ticker,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": price,
            "quantity": qty,
            "pnl_pct": round(pnl, 2),
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._closed_today.append(record)
        log.info(
            "CLOSED %s %.2f shares @ %.2f  pnl=%.1f%%  reason=%s",
            pos.ticker, qty, price, pnl, reason,
        )
        self._report_close(record)

    def _report_close(self, record: dict) -> None:
        try:
            from tools.report_to_phoenix import report_trade

            asyncio.get_event_loop().run_until_complete(report_trade(self.config, record))
        except Exception as exc:
            log.warning("failed to report close to Phoenix: %s", exc)

    def report_heartbeat(self) -> None:
        try:
            from tools.report_to_phoenix import report_heartbeat

            status = {
                "status": "monitoring",
                "open_positions": len(self.positions),
                "trades_today": len(self._closed_today),
            }
            asyncio.get_event_loop().run_until_complete(report_heartbeat(self.config, status))
        except Exception as exc:
            log.debug("heartbeat report failed: %s", exc)


# ---------------------------------------------------------------------------
# Main daemon loop
# ---------------------------------------------------------------------------

def run(config_path: str) -> None:
    monitor = PositionMonitor(config_path)
    monitor.reload_config()
    monitor.load_positions()

    def _handle_signal(signum, _frame):
        log.info("received signal %s — shutting down", signum)
        monitor._shutdown = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    last_ta = 0.0
    last_conviction = 0.0

    log.info("position monitor started — %d positions", len(monitor.positions))

    while not monitor._shutdown:
        try:
            now = time.monotonic()

            monitor.reload_config()
            monitor.load_positions()

            monitor.tick_fast()
            monitor.report_heartbeat()

            if now - last_ta >= TICK_TA:
                monitor.tick_ta()
                monitor.check_pending_signals()
                last_ta = now

            if now - last_conviction >= TICK_CONVICTION:
                monitor.tick_conviction()
                last_conviction = now

            monitor.check_eod_close()

        except Exception:
            log.exception("error in monitoring loop — continuing")

        sleep_remaining = TICK_FAST
        while sleep_remaining > 0 and not monitor._shutdown:
            time.sleep(min(sleep_remaining, 1))
            sleep_remaining -= 1

    monitor.save_positions()
    log.info("position monitor stopped")


def main():
    parser = argparse.ArgumentParser(description="Monitor open positions with TA-based hold/close decisions")
    parser.add_argument("--config", required=True, help="Path to config.json")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    run(args.config)


if __name__ == "__main__":
    main()
