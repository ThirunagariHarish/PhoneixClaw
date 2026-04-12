"""Company Events feature client with disk caching.

Aggregates earnings, dividends, splits, insider transactions, institutional
holdings, analyst recommendations, and biotech/FDA features primarily from
yfinance.  Every public method returns NaN-safe dicts; no exception escapes.

Singleton via ``get_company_events_client()``.  Disk cache in
``/tmp/phoenix_events_cache/`` with a 12-hour TTL (configurable).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(os.getenv("EVENTS_CACHE_DIR", "/tmp/phoenix_events_cache"))
_CACHE_TTL_HOURS = 12


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_cache_dir() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(namespace: str, ticker: str) -> Path:
    return _CACHE_DIR / f"{namespace}_{ticker}.json"


def _is_cache_fresh(path: Path, ttl_hours: int = _CACHE_TTL_HOURS) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    return age < ttl_hours * 3600


def _read_cache(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_cache(path: Path, data: Any) -> None:
    try:
        path.write_text(json.dumps(data, default=str))
    except Exception:
        pass


def _safe_float(val: Any) -> float:
    """Convert *val* to a Python float, returning NaN on failure."""
    if val is None:
        return np.nan
    try:
        f = float(val)
        if np.isfinite(f):
            return f
        return np.nan
    except (TypeError, ValueError):
        return np.nan


def _to_date(val: Any) -> date | None:
    """Best-effort conversion of timestamps / strings to ``date``."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, pd.Timestamp):
        return val.date()
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# yfinance Ticker wrapper (cached)
# ---------------------------------------------------------------------------

def _get_yf_ticker(ticker: str):  # noqa: ANN202
    """Return a ``yf.Ticker`` object (import is deferred)."""
    import yfinance as yf
    return yf.Ticker(ticker)


def _get_ticker_info(ticker: str) -> dict:
    """Fetch ``Ticker.info`` with disk cache (12 h)."""
    cp = _cache_path("info", ticker)
    if _is_cache_fresh(cp):
        cached = _read_cache(cp)
        if cached is not None:
            return cached
    try:
        info = _get_yf_ticker(ticker).info or {}
        _write_cache(cp, info)
        return info
    except Exception as exc:
        logger.debug("yfinance info fetch failed for %s: %s", ticker, exc)
        return {}


# ---------------------------------------------------------------------------
# Feature sub-sections
# ---------------------------------------------------------------------------

def _earnings_features(ticker: str, as_of_date: date) -> dict[str, float]:
    """Earnings dates, surprise, drift features."""
    feats: dict[str, float] = {
        "days_to_earnings": np.nan,
        "days_since_earnings": np.nan,
        "earnings_surprise_last": np.nan,
        "earnings_surprise_avg_4q": np.nan,
        "earnings_beat_rate_4q": np.nan,
        "earnings_surprise_std_4q": np.nan,
        "pre_earnings_run_5d": np.nan,
        "post_earnings_drift_1d": np.nan,
        "post_earnings_drift_5d": np.nan,
    }
    try:
        tk = _get_yf_ticker(ticker)

        # --- Earnings dates ---
        try:
            ed = tk.earnings_dates
            if ed is not None and not ed.empty:
                # Index is typically a DatetimeIndex
                all_dates = [_to_date(d) for d in ed.index]
                all_dates = [d for d in all_dates if d is not None]
                past = sorted([d for d in all_dates if d < as_of_date])
                future = sorted([d for d in all_dates if d >= as_of_date])
                if future:
                    feats["days_to_earnings"] = float((future[0] - as_of_date).days)
                if past:
                    feats["days_since_earnings"] = float((as_of_date - past[-1]).days)
        except Exception:
            pass

        # --- Quarterly earnings for surprise data ---
        try:
            qe = tk.quarterly_earnings
            if qe is not None and not qe.empty:
                # Columns may be 'Revenue', 'Earnings' or 'Actual', 'Estimate'
                # Attempt to find actual / estimate columns
                actual_col = None
                estimate_col = None
                for c in qe.columns:
                    cl = str(c).lower()
                    if "actual" in cl or cl == "earnings":
                        actual_col = c
                    if "estimate" in cl or "expected" in cl:
                        estimate_col = c

                if actual_col is not None and estimate_col is not None:
                    # Filter by date if index is date-like
                    try:
                        qe_filtered = qe[pd.to_datetime(qe.index).date < as_of_date]  # type: ignore[union-attr]
                    except Exception:
                        qe_filtered = qe  # cannot filter; use all

                    if not qe_filtered.empty:
                        surprises: list[float] = []
                        for _, r in qe_filtered.iterrows():
                            act = _safe_float(r.get(actual_col))
                            est = _safe_float(r.get(estimate_col))
                            if np.isfinite(act) and np.isfinite(est) and abs(est) > 1e-9:
                                surprises.append((act - est) / abs(est))

                        if surprises:
                            feats["earnings_surprise_last"] = round(surprises[0], 6)
                        last4 = surprises[:4]
                        if last4:
                            feats["earnings_surprise_avg_4q"] = round(float(np.mean(last4)), 6)
                            feats["earnings_beat_rate_4q"] = round(
                                sum(1 for s in last4 if s > 0) / len(last4), 4
                            )
                            if len(last4) >= 2:
                                feats["earnings_surprise_std_4q"] = round(float(np.std(last4, ddof=0)), 6)
        except Exception:
            pass

        # --- Pre / post earnings drift from price data ---
        try:
            past_earn = feats.get("days_since_earnings", np.nan)
            if np.isfinite(past_earn) and past_earn < 365:
                import yfinance as yf
                hist = yf.download(
                    ticker,
                    start=str(as_of_date - timedelta(days=int(past_earn) + 30)),
                    end=str(as_of_date),
                    progress=False,
                    auto_adjust=True,
                )
                if hist is not None and not hist.empty:
                    close = hist["Close"]
                    if hasattr(close, "columns"):
                        close = close.iloc[:, 0]
                    earn_dt = as_of_date - timedelta(days=int(past_earn))
                    # Find closest index
                    idx_dates = close.index.date if hasattr(close.index, "date") else [_to_date(d) for d in close.index]
                    pre_mask = [d <= earn_dt for d in idx_dates]
                    post_mask = [d > earn_dt for d in idx_dates]
                    pre_close = close[pre_mask]
                    post_close = close[post_mask]

                    if len(pre_close) >= 6:
                        feats["pre_earnings_run_5d"] = round(
                            float((pre_close.iloc[-1] - pre_close.iloc[-6]) / pre_close.iloc[-6]), 6
                        )
                    if len(post_close) >= 1 and len(pre_close) >= 1:
                        feats["post_earnings_drift_1d"] = round(
                            float((post_close.iloc[0] - pre_close.iloc[-1]) / pre_close.iloc[-1]), 6
                        )
                    if len(post_close) >= 5 and len(pre_close) >= 1:
                        feats["post_earnings_drift_5d"] = round(
                            float((post_close.iloc[4] - pre_close.iloc[-1]) / pre_close.iloc[-1]), 6
                        )
        except Exception:
            pass

    except Exception as exc:
        logger.debug("Earnings features failed for %s: %s", ticker, exc)

    return feats


def _dividend_features(ticker: str, as_of_date: date) -> dict[str, float]:
    """Dividend dates, yield, streaks."""
    feats: dict[str, float] = {
        "days_to_ex_div": np.nan,
        "days_since_ex_div": np.nan,
        "dividend_yield": np.nan,
        "dividend_amount_last": np.nan,
        "div_change_pct": np.nan,
        "div_increase_streak": np.nan,
        "has_dividend": 0.0,
    }
    try:
        tk = _get_yf_ticker(ticker)
        divs = tk.dividends
        if divs is None or divs.empty:
            return feats

        feats["has_dividend"] = 1.0

        # Convert index to dates
        div_dates = [_to_date(d) for d in divs.index]
        div_amounts = divs.values.tolist()

        # Filter to as_of_date
        past_pairs = [(d, a) for d, a in zip(div_dates, div_amounts) if d is not None and d < as_of_date]
        future_pairs = [(d, a) for d, a in zip(div_dates, div_amounts) if d is not None and d >= as_of_date]

        if future_pairs:
            feats["days_to_ex_div"] = float((future_pairs[0][0] - as_of_date).days)

        if past_pairs:
            last_div_date, last_div_amt = past_pairs[-1]
            feats["days_since_ex_div"] = float((as_of_date - last_div_date).days)
            feats["dividend_amount_last"] = _safe_float(last_div_amt)

            # Dividend yield: annualize last 4 dividends / current price
            last_4_amts = [_safe_float(a) for _, a in past_pairs[-4:]]
            last_4_amts = [a for a in last_4_amts if np.isfinite(a)]
            if last_4_amts:
                annual_div = sum(last_4_amts) * (4 / len(last_4_amts))  # annualize
                info = _get_ticker_info(ticker)
                price = _safe_float(info.get("previousClose") or info.get("regularMarketPrice"))
                if np.isfinite(price) and price > 0:
                    feats["dividend_yield"] = round(annual_div / price, 6)

            # Div change %
            if len(past_pairs) >= 2:
                prev_amt = _safe_float(past_pairs[-2][1])
                curr_amt = _safe_float(past_pairs[-1][1])
                if np.isfinite(prev_amt) and np.isfinite(curr_amt) and abs(prev_amt) > 1e-9:
                    feats["div_change_pct"] = round((curr_amt - prev_amt) / abs(prev_amt), 6)

            # Div increase streak
            streak = 0
            for i in range(len(past_pairs) - 1, 0, -1):
                curr_a = _safe_float(past_pairs[i][1])
                prev_a = _safe_float(past_pairs[i - 1][1])
                if np.isfinite(curr_a) and np.isfinite(prev_a) and curr_a > prev_a:
                    streak += 1
                else:
                    break
            feats["div_increase_streak"] = float(streak)

    except Exception as exc:
        logger.debug("Dividend features failed for %s: %s", ticker, exc)

    return feats


def _split_features(ticker: str, as_of_date: date) -> dict[str, float]:
    """Stock split features."""
    feats: dict[str, float] = {
        "days_since_split": np.nan,
        "split_ratio_last": np.nan,
        "had_recent_split_90d": 0.0,
    }
    try:
        tk = _get_yf_ticker(ticker)
        splits = tk.splits
        if splits is None or splits.empty:
            return feats

        split_dates = [_to_date(d) for d in splits.index]
        split_ratios = splits.values.tolist()

        past = [
            (d, r) for d, r in zip(split_dates, split_ratios)
            if d is not None and d < as_of_date
        ]
        if not past:
            return feats

        last_split_date, last_split_ratio = past[-1]
        days_since = (as_of_date - last_split_date).days
        feats["days_since_split"] = float(days_since)
        feats["split_ratio_last"] = _safe_float(last_split_ratio)
        feats["had_recent_split_90d"] = 1.0 if days_since <= 90 else 0.0

    except Exception as exc:
        logger.debug("Split features failed for %s: %s", ticker, exc)

    return feats


def _insider_features(ticker: str, as_of_date: date) -> dict[str, float]:
    """Insider transaction features from yfinance."""
    feats: dict[str, float] = {
        "insider_buy_count_90d": np.nan,
        "insider_sell_count_90d": np.nan,
        "insider_net_shares_90d": np.nan,
        "insider_buy_sell_ratio": np.nan,
        "insider_total_value_90d": np.nan,
    }
    try:
        tk = _get_yf_ticker(ticker)
        txns = tk.insider_transactions
        if txns is None or txns.empty:
            return feats

        # Normalize column names to lowercase
        txns.columns = [str(c).lower().strip() for c in txns.columns]

        # Determine date column
        date_col = None
        for c in txns.columns:
            if "date" in c or "start" in c:
                date_col = c
                break
        if date_col is None and txns.index.name and "date" in str(txns.index.name).lower():
            txns = txns.reset_index()
            date_col = txns.columns[0]

        if date_col is None:
            return feats

        cutoff = as_of_date - timedelta(days=90)
        txns["_date"] = txns[date_col].apply(_to_date)
        recent = txns[(txns["_date"].notna()) & (txns["_date"] >= cutoff) & (txns["_date"] < as_of_date)]

        if recent.empty:
            feats["insider_buy_count_90d"] = 0.0
            feats["insider_sell_count_90d"] = 0.0
            feats["insider_net_shares_90d"] = 0.0
            feats["insider_total_value_90d"] = 0.0
            return feats

        # Determine transaction type column
        type_col = None
        for c in recent.columns:
            if "transaction" in c or "type" in c or "text" in c:
                type_col = c
                break

        shares_col = None
        for c in recent.columns:
            if "shares" in c or "amount" in c:
                shares_col = c
                break

        value_col = None
        for c in recent.columns:
            if "value" in c:
                value_col = c
                break

        buys = 0
        sells = 0
        net_shares = 0.0
        total_value = 0.0

        for _, row in recent.iterrows():
            tx_type = str(row.get(type_col, "")).lower() if type_col else ""
            is_buy = any(kw in tx_type for kw in ["purchase", "buy", "acquisition"])
            is_sell = any(kw in tx_type for kw in ["sale", "sell", "disposition"])

            sh = _safe_float(row.get(shares_col)) if shares_col else 0.0
            if not np.isfinite(sh):
                sh = 0.0
            val = _safe_float(row.get(value_col)) if value_col else 0.0
            if not np.isfinite(val):
                val = 0.0

            if is_buy:
                buys += 1
                net_shares += abs(sh)
                total_value += abs(val)
            elif is_sell:
                sells += 1
                net_shares -= abs(sh)
                total_value += abs(val)

        feats["insider_buy_count_90d"] = float(buys)
        feats["insider_sell_count_90d"] = float(sells)
        feats["insider_net_shares_90d"] = round(net_shares, 2)
        feats["insider_total_value_90d"] = round(total_value, 2)
        total = buys + sells
        if total > 0:
            feats["insider_buy_sell_ratio"] = round(buys / total, 4)

    except Exception as exc:
        logger.debug("Insider features failed for %s: %s", ticker, exc)

    return feats


def _institutional_features(ticker: str) -> dict[str, float]:
    """Institutional holder features from yfinance."""
    feats: dict[str, float] = {
        "institutional_holders_count": np.nan,
        "institutional_pct_held": np.nan,
        "top_holder_pct": np.nan,
    }
    try:
        tk = _get_yf_ticker(ticker)
        holders = tk.institutional_holders
        if holders is None or holders.empty:
            return feats

        feats["institutional_holders_count"] = float(len(holders))

        # Normalize columns
        holders.columns = [str(c).lower().strip() for c in holders.columns]

        pct_col = None
        for c in holders.columns:
            if "pct" in c or "%" in c or "percent" in c or "held" in c:
                pct_col = c
                break

        if pct_col is not None:
            pcts = holders[pct_col].apply(_safe_float)
            total = pcts.sum()
            if np.isfinite(total):
                feats["institutional_pct_held"] = round(total, 6)
            top = pcts.iloc[0] if len(pcts) > 0 else np.nan
            if np.isfinite(top):
                feats["top_holder_pct"] = round(top, 6)
        else:
            # Try info dict as fallback
            info = _get_ticker_info(ticker)
            inst_pct = _safe_float(info.get("heldPercentInstitutions"))
            if np.isfinite(inst_pct):
                feats["institutional_pct_held"] = round(inst_pct, 6)

    except Exception as exc:
        logger.debug("Institutional features failed for %s: %s", ticker, exc)

    return feats


def _analyst_features(ticker: str, as_of_date: date) -> dict[str, float]:
    """Analyst recommendation and price target features."""
    feats: dict[str, float] = {
        "analyst_count": np.nan,
        "analyst_mean_target": np.nan,
        "analyst_target_vs_price": np.nan,
        "analyst_high_target": np.nan,
        "analyst_low_target": np.nan,
        "analyst_buy_pct": np.nan,
        "analyst_sell_pct": np.nan,
        "analyst_upgrades_90d": np.nan,
        "analyst_downgrades_90d": np.nan,
        "analyst_revision_momentum": np.nan,
    }
    try:
        tk = _get_yf_ticker(ticker)

        # --- Price targets ---
        try:
            targets = tk.analyst_price_targets
            if targets is not None:
                if isinstance(targets, dict):
                    feats["analyst_mean_target"] = _safe_float(targets.get("mean") or targets.get("current"))
                    feats["analyst_high_target"] = _safe_float(targets.get("high"))
                    feats["analyst_low_target"] = _safe_float(targets.get("low"))
                    count = _safe_float(targets.get("numberOfAnalysts") or targets.get("number"))
                    if np.isfinite(count):
                        feats["analyst_count"] = count
                elif isinstance(targets, pd.DataFrame) and not targets.empty:
                    for col in targets.columns:
                        cl = str(col).lower()
                        if "mean" in cl or "current" in cl:
                            feats["analyst_mean_target"] = _safe_float(targets[col].iloc[0])
                        elif "high" in cl:
                            feats["analyst_high_target"] = _safe_float(targets[col].iloc[0])
                        elif "low" in cl:
                            feats["analyst_low_target"] = _safe_float(targets[col].iloc[0])

            # target vs price
            info = _get_ticker_info(ticker)
            price = _safe_float(info.get("previousClose") or info.get("regularMarketPrice"))
            mean_t = feats["analyst_mean_target"]
            if np.isfinite(mean_t) and np.isfinite(price) and price > 0:
                feats["analyst_target_vs_price"] = round((mean_t - price) / price, 6)
        except Exception:
            pass

        # --- Recommendations ---
        try:
            recs = tk.recommendations
            if recs is not None and not recs.empty:
                recs.columns = [str(c).lower().strip() for c in recs.columns]

                # Filter to as_of_date
                try:
                    if recs.index.dtype in ("datetime64[ns]", "datetime64[ns, UTC]"):
                        rec_dates = recs.index.date
                    else:
                        rec_dates = pd.to_datetime(recs.index).date
                    recs = recs[[d < as_of_date for d in rec_dates]]
                except Exception:
                    pass

                if not recs.empty:
                    # Try to extract grade/action info
                    grade_col = None
                    action_col = None
                    for c in recs.columns:
                        cl = str(c).lower()
                        if "to grade" in cl or "tograde" in cl or cl == "to_grade":
                            grade_col = c
                        elif "grade" in cl:
                            grade_col = grade_col or c
                        if "action" in cl:
                            action_col = c

                    # Buy/sell percentages from grade column
                    if grade_col:
                        grades = recs[grade_col].dropna().astype(str).str.lower()
                        if len(grades) > 0:
                            if np.isnan(feats["analyst_count"]):
                                feats["analyst_count"] = float(len(grades))
                            buy_kw = ["buy", "overweight", "outperform", "strong buy", "positive"]
                            sell_kw = ["sell", "underweight", "underperform", "strong sell", "negative"]
                            n = len(grades)
                            buy_ct = sum(1 for g in grades if any(k in g for k in buy_kw))
                            sell_ct = sum(1 for g in grades if any(k in g for k in sell_kw))
                            feats["analyst_buy_pct"] = round(buy_ct / n, 4)
                            feats["analyst_sell_pct"] = round(sell_ct / n, 4)

                    # Upgrades / downgrades in 90d
                    if action_col:
                        cutoff_90 = as_of_date - timedelta(days=90)
                        try:
                            if recs.index.dtype in ("datetime64[ns]", "datetime64[ns, UTC]"):
                                recent_dates = recs.index.date
                            else:
                                recent_dates = pd.to_datetime(recs.index).date
                            recent = recs[[d >= cutoff_90 for d in recent_dates]]
                        except Exception:
                            recent = recs.tail(10)

                        if not recent.empty:
                            actions = recent[action_col].astype(str).str.lower()
                            ups = sum(1 for a in actions if "up" in a or "upgrade" in a or "init" in a)
                            downs = sum(1 for a in actions if "down" in a or "downgrade" in a)
                            feats["analyst_upgrades_90d"] = float(ups)
                            feats["analyst_downgrades_90d"] = float(downs)
                            total = ups + downs
                            if total > 0:
                                feats["analyst_revision_momentum"] = round((ups - downs) / total, 4)
        except Exception:
            pass

    except Exception as exc:
        logger.debug("Analyst features failed for %s: %s", ticker, exc)

    return feats


def _biotech_features(ticker: str) -> dict[str, float]:
    """Biotech / FDA catalyst features."""
    feats: dict[str, float] = {
        "is_biotech": 0.0,
        "days_to_fda_date": np.nan,
    }
    try:
        info = _get_ticker_info(ticker)
        sector = str(info.get("sector", "")).lower()
        industry = str(info.get("industry", "")).lower()

        if sector == "healthcare" and ("biotech" in industry or "pharma" in industry):
            feats["is_biotech"] = 1.0
            # days_to_fda_date is a placeholder for future FDA calendar integration
    except Exception as exc:
        logger.debug("Biotech features failed for %s: %s", ticker, exc)

    return feats


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class CompanyEventsClient:
    """Aggregates company event features from yfinance."""

    def __init__(self) -> None:
        _ensure_cache_dir()

    def get_event_features(self, ticker: str, as_of_date: date | str) -> dict[str, float]:
        """Return 40-50 company event features for *ticker* as of *as_of_date*.

        Every value is a finite float or ``np.nan``.  The method never raises.
        """
        if isinstance(as_of_date, str):
            as_of_date = date.fromisoformat(as_of_date)

        features: dict[str, float] = {}

        # Check disk cache first
        cp = _cache_path("events", f"{ticker}_{as_of_date.isoformat()}")
        if _is_cache_fresh(cp):
            cached = _read_cache(cp)
            if cached is not None:
                # Restore None -> NaN for consistency
                return {k: (np.nan if v is None else v) for k, v in cached.items()}

        # Collect from each sub-section (each is NaN-safe)
        features.update(_earnings_features(ticker, as_of_date))
        features.update(_dividend_features(ticker, as_of_date))
        features.update(_split_features(ticker, as_of_date))
        features.update(_insider_features(ticker, as_of_date))
        features.update(_institutional_features(ticker))
        features.update(_analyst_features(ticker, as_of_date))
        features.update(_biotech_features(ticker))

        # Persist to disk cache
        # Convert NaN to None for JSON, then back on read
        serializable = {k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in features.items()}
        _write_cache(cp, serializable)

        return features


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client_instance: CompanyEventsClient | None = None


def get_company_events_client() -> CompanyEventsClient:
    """Return module-level singleton ``CompanyEventsClient``."""
    global _client_instance
    if _client_instance is None:
        _client_instance = CompanyEventsClient()
    return _client_instance
