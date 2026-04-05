"""Options analytics: IV, Greeks (Black-Scholes), max pain, probability ITM.

Usage:
    python options_analysis.py --ticker SPX --expiry 2026-04-04 --strike 5900 --type call --output options_result.json
"""

import argparse
import json
import logging
import math
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

try:
    import pandas as pd
except ImportError:
    print("pandas is required: pip install pandas", file=sys.stderr)
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from scipy.stats import norm
    from scipy.optimize import brentq
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [options] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

TICKER_MAP = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "DJI": "^DJI",
    "VIX": "^VIX",
    "RUT": "^RUT",
}

RISK_FREE_RATE = 0.043


# ---------------------------------------------------------------------------
# Normal CDF fallback (when scipy unavailable)
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erfc for environments without scipy."""
    if HAS_SCIPY:
        return float(norm.cdf(x))
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _norm_pdf(x: float) -> float:
    if HAS_SCIPY:
        return float(norm.pdf(x))
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


# ---------------------------------------------------------------------------
# Black-Scholes
# ---------------------------------------------------------------------------

def _bs_d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def _bs_d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return _bs_d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def bs_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0:
        return max(S - K, 0)
    d1 = _bs_d1(S, K, T, r, sigma)
    d2 = _bs_d2(S, K, T, r, sigma)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bs_put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0:
        return max(K - S, 0)
    d1 = _bs_d1(S, K, T, r, sigma)
    d2 = _bs_d2(S, K, T, r, sigma)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float,
              option_type: str = "call") -> dict:
    """Compute Black-Scholes Greeks."""
    if T <= 1e-10 or sigma <= 1e-10:
        intrinsic = max(S - K, 0) if option_type == "call" else max(K - S, 0)
        return {
            "delta": 1.0 if (option_type == "call" and S > K) else (-1.0 if option_type == "put" and S < K else 0.0),
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
            "theoretical_price": intrinsic,
        }

    d1 = _bs_d1(S, K, T, r, sigma)
    d2 = _bs_d2(S, K, T, r, sigma)
    sqrt_T = math.sqrt(T)

    if option_type == "call":
        delta = _norm_cdf(d1)
        price = bs_call_price(S, K, T, r, sigma)
        rho = K * T * math.exp(-r * T) * _norm_cdf(d2) / 100
    else:
        delta = _norm_cdf(d1) - 1
        price = bs_put_price(S, K, T, r, sigma)
        rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2) / 100

    gamma = _norm_pdf(d1) / (S * sigma * sqrt_T)
    theta_component = -(S * _norm_pdf(d1) * sigma) / (2 * sqrt_T)
    if option_type == "call":
        theta = (theta_component - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
    else:
        theta = (theta_component + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365
    vega = S * _norm_pdf(d1) * sqrt_T / 100

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
        "theoretical_price": round(price, 4),
    }


# ---------------------------------------------------------------------------
# Implied Volatility
# ---------------------------------------------------------------------------

def implied_volatility(market_price: float, S: float, K: float, T: float,
                       r: float, option_type: str = "call") -> float | None:
    """Solve for IV using Brent's method (scipy) or bisection fallback."""
    if T <= 0 or market_price <= 0:
        return None

    price_func = bs_call_price if option_type == "call" else bs_put_price

    def objective(sigma):
        return price_func(S, K, T, r, sigma) - market_price

    if HAS_SCIPY:
        try:
            return float(brentq(objective, 0.001, 10.0, xtol=1e-6, maxiter=200))
        except (ValueError, RuntimeError):
            return None
    else:
        lo, hi = 0.001, 10.0
        for _ in range(200):
            mid = (lo + hi) / 2
            val = objective(mid)
            if abs(val) < 1e-6:
                return mid
            if val > 0:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2 if abs(objective((lo + hi) / 2)) < 0.5 else None


# ---------------------------------------------------------------------------
# Historical Volatility
# ---------------------------------------------------------------------------

def historical_volatility(close: pd.Series, window: int = 30) -> float | None:
    if len(close) < window + 1:
        return None
    log_returns = np.log(close / close.shift(1)).dropna()
    if len(log_returns) < window:
        return None
    return float(log_returns.iloc[-window:].std() * np.sqrt(252))


# ---------------------------------------------------------------------------
# Max Pain
# ---------------------------------------------------------------------------

def compute_max_pain(options_chain_calls: pd.DataFrame,
                     options_chain_puts: pd.DataFrame) -> dict | None:
    """Estimate max pain from options chain open interest."""
    all_strikes = sorted(set(
        list(options_chain_calls["strike"].values) +
        list(options_chain_puts["strike"].values)
    ))

    if not all_strikes:
        return None

    call_oi = dict(zip(options_chain_calls["strike"], options_chain_calls["openInterest"].fillna(0)))
    put_oi = dict(zip(options_chain_puts["strike"], options_chain_puts["openInterest"].fillna(0)))

    pain = {}
    for settle_price in all_strikes:
        total_pain = 0.0
        for strike in all_strikes:
            c_oi = call_oi.get(strike, 0)
            p_oi = put_oi.get(strike, 0)
            call_itm = max(settle_price - strike, 0) * c_oi
            put_itm = max(strike - settle_price, 0) * p_oi
            total_pain += call_itm + put_itm
        pain[settle_price] = total_pain

    max_pain_strike = min(pain, key=pain.get)
    return {
        "max_pain_strike": round(max_pain_strike, 2),
        "total_pain_at_max_pain": round(pain[max_pain_strike], 2),
        "strikes_analyzed": len(all_strikes),
    }


# ---------------------------------------------------------------------------
# Open interest analysis
# ---------------------------------------------------------------------------

def analyze_open_interest(calls: pd.DataFrame, puts: pd.DataFrame,
                          current_price: float) -> dict:
    total_call_oi = int(calls["openInterest"].fillna(0).sum())
    total_put_oi = int(puts["openInterest"].fillna(0).sum())
    pcr = total_put_oi / total_call_oi if total_call_oi > 0 else None

    itm_calls = calls[calls["strike"] < current_price]
    otm_calls = calls[calls["strike"] >= current_price]
    itm_puts = puts[puts["strike"] > current_price]
    otm_puts = puts[puts["strike"] <= current_price]

    highest_call_oi = None
    if not calls.empty:
        max_row = calls.loc[calls["openInterest"].fillna(0).idxmax()]
        highest_call_oi = {"strike": float(max_row["strike"]),
                           "openInterest": int(max_row["openInterest"])}

    highest_put_oi = None
    if not puts.empty:
        max_row = puts.loc[puts["openInterest"].fillna(0).idxmax()]
        highest_put_oi = {"strike": float(max_row["strike"]),
                          "openInterest": int(max_row["openInterest"])}

    total_call_volume = int(calls["volume"].fillna(0).sum())
    total_put_volume = int(puts["volume"].fillna(0).sum())

    return {
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "put_call_ratio_oi": round(pcr, 3) if pcr else None,
        "total_call_volume": total_call_volume,
        "total_put_volume": total_put_volume,
        "put_call_ratio_volume": round(total_put_volume / total_call_volume, 3) if total_call_volume > 0 else None,
        "itm_call_oi": int(itm_calls["openInterest"].fillna(0).sum()),
        "otm_call_oi": int(otm_calls["openInterest"].fillna(0).sum()),
        "itm_put_oi": int(itm_puts["openInterest"].fillna(0).sum()),
        "otm_put_oi": int(otm_puts["openInterest"].fillna(0).sum()),
        "highest_call_oi_strike": highest_call_oi,
        "highest_put_oi_strike": highest_put_oi,
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_options_analysis(ticker: str, expiry: str, strike: float,
                         option_type: str) -> dict:
    """Full options analysis for a single contract."""
    yf_ticker = TICKER_MAP.get(ticker.upper(), ticker)
    log.info("Analyzing %s %s %s %.2f", ticker, expiry, option_type, strike)

    tk = yf.Ticker(yf_ticker)

    # Current price
    hist = tk.history(period="5d")
    if hist.empty:
        return {"error": f"Cannot fetch price data for {yf_ticker}"}
    current_price = float(hist["Close"].iloc[-1])
    log.info("Current price: %.2f", current_price)

    # Historical volatility
    hist_long = tk.history(period="1y")
    hv_30 = historical_volatility(hist_long["Close"], 30) if not hist_long.empty else None
    hv_60 = historical_volatility(hist_long["Close"], 60) if not hist_long.empty else None

    # Time to expiry
    expiry_dt = datetime.strptime(expiry, "%Y-%m-%d")
    now = datetime.now()
    dte = (expiry_dt - now).days
    T = max(dte / 365.0, 1e-10)
    log.info("DTE: %d, T: %.4f", dte, T)

    # Options chain
    try:
        chain = tk.option_chain(expiry)
        calls = chain.calls
        puts = chain.puts
    except Exception as exc:
        log.warning("Failed to get options chain for %s exp %s: %s", yf_ticker, expiry, exc)
        calls = pd.DataFrame()
        puts = pd.DataFrame()

    # Find the specific contract
    contract_data = {}
    iv_from_market = None
    chain_df = calls if option_type == "call" else puts

    if not chain_df.empty:
        match = chain_df[chain_df["strike"] == strike]
        if match.empty:
            closest_idx = (chain_df["strike"] - strike).abs().idxmin()
            match = chain_df.loc[[closest_idx]]
            log.info("Exact strike %.2f not found, using closest: %.2f",
                     strike, float(match["strike"].iloc[0]))

        if not match.empty:
            row = match.iloc[0]
            contract_data = {
                "strike": float(row["strike"]),
                "lastPrice": float(row.get("lastPrice", 0)),
                "bid": float(row.get("bid", 0)),
                "ask": float(row.get("ask", 0)),
                "volume": int(row.get("volume", 0)) if pd.notna(row.get("volume")) else 0,
                "openInterest": int(row.get("openInterest", 0)) if pd.notna(row.get("openInterest")) else 0,
                "impliedVolatility": float(row.get("impliedVolatility", 0)),
                "inTheMoney": bool(row.get("inTheMoney", False)),
            }
            mid_price = (contract_data["bid"] + contract_data["ask"]) / 2
            if mid_price > 0:
                iv_from_market = implied_volatility(mid_price, current_price, strike, T,
                                                    RISK_FREE_RATE, option_type)
            if iv_from_market is None and contract_data["impliedVolatility"] > 0:
                iv_from_market = contract_data["impliedVolatility"]

    # Greeks
    sigma = iv_from_market if iv_from_market else (hv_30 if hv_30 else 0.25)
    greeks = bs_greeks(current_price, strike, T, RISK_FREE_RATE, sigma, option_type)

    # Probability ITM
    if sigma > 0 and T > 0:
        d2 = _bs_d2(current_price, strike, T, RISK_FREE_RATE, sigma)
        prob_itm = _norm_cdf(d2) if option_type == "call" else _norm_cdf(-d2)
    else:
        prob_itm = 1.0 if (option_type == "call" and current_price > strike) or \
                          (option_type == "put" and current_price < strike) else 0.0

    # Probability of profit (accounting for premium)
    premium = contract_data.get("lastPrice", greeks["theoretical_price"])
    if option_type == "call":
        breakeven = strike + premium
        d2_be = _bs_d2(current_price, breakeven, T, RISK_FREE_RATE, sigma) if sigma > 0 and T > 0 else 0
        prob_profit = _norm_cdf(d2_be) if sigma > 0 and T > 0 else (1.0 if current_price > breakeven else 0.0)
    else:
        breakeven = strike - premium
        d2_be = _bs_d2(current_price, breakeven, T, RISK_FREE_RATE, sigma) if sigma > 0 and T > 0 else 0
        prob_profit = _norm_cdf(-d2_be) if sigma > 0 and T > 0 else (1.0 if current_price < breakeven else 0.0)

    # IV vs HV comparison
    iv_hv_analysis = {}
    if iv_from_market and hv_30:
        iv_hv_analysis["iv"] = round(iv_from_market, 4)
        iv_hv_analysis["hv_30"] = round(hv_30, 4)
        iv_hv_analysis["hv_60"] = round(hv_60, 4) if hv_60 else None
        iv_hv_analysis["iv_premium"] = round(iv_from_market - hv_30, 4)
        iv_hv_analysis["iv_hv_ratio"] = round(iv_from_market / hv_30, 3) if hv_30 > 0 else None
        if iv_from_market > hv_30 * 1.2:
            iv_hv_analysis["assessment"] = "IV_elevated"
        elif iv_from_market < hv_30 * 0.8:
            iv_hv_analysis["assessment"] = "IV_depressed"
        else:
            iv_hv_analysis["assessment"] = "IV_fair"

    # Max pain
    max_pain = None
    if not calls.empty and not puts.empty:
        max_pain = compute_max_pain(calls, puts)

    # OI analysis
    oi_analysis = None
    if not calls.empty and not puts.empty:
        oi_analysis = analyze_open_interest(calls, puts, current_price)

    return {
        "ticker": ticker,
        "yfinance_ticker": yf_ticker,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "current_price": round(current_price, 2),
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry,
        "dte": dte,
        "contract": contract_data,
        "greeks": greeks,
        "implied_volatility": round(iv_from_market, 4) if iv_from_market else None,
        "historical_volatility_30d": round(hv_30, 4) if hv_30 else None,
        "historical_volatility_60d": round(hv_60, 4) if hv_60 else None,
        "iv_vs_hv": iv_hv_analysis,
        "probability_itm": round(prob_itm, 4),
        "probability_profit": round(prob_profit, 4),
        "breakeven": round(breakeven, 2),
        "max_pain": max_pain,
        "open_interest_analysis": oi_analysis,
        "risk_free_rate": RISK_FREE_RATE,
    }


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return None if np.isnan(obj) else round(float(obj), 6)
    if isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


def main():
    parser = argparse.ArgumentParser(description="Options analytics engine")
    parser.add_argument("--ticker", required=True, help="Underlying ticker (e.g. SPX, AAPL)")
    parser.add_argument("--expiry", required=True, help="Expiration date YYYY-MM-DD")
    parser.add_argument("--strike", required=True, type=float, help="Strike price")
    parser.add_argument("--type", required=True, choices=["call", "put"], help="Option type")
    parser.add_argument("--output", default="options_result.json", help="Output JSON path")
    args = parser.parse_args()

    if yf is None:
        log.error("yfinance is required: pip install yfinance")
        sys.exit(1)

    result = run_options_analysis(args.ticker, args.expiry, args.strike, args.type)
    result = _json_safe(result)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, default=str)

    summary = {
        "status": "ok",
        "ticker": args.ticker,
        "strike": args.strike,
        "type": args.type,
        "expiry": args.expiry,
        "prob_itm": result.get("probability_itm"),
        "prob_profit": result.get("probability_profit"),
        "delta": result.get("greeks", {}).get("delta"),
        "iv": result.get("implied_volatility"),
        "output": args.output,
    }
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
