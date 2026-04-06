"""Discover trading strategies from enriched backtest data using decision-tree rule extraction.

Mines multi-condition trading edges (e.g. 'RSI > 60 + Friday + power hour = 85% WR')
and generates strategy-style names. Two phases:
  1. Decision-tree rule extraction for multi-condition patterns
  2. Grouped aggregation for ticker/time/regime combinations
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


STRATEGY_TEMPLATES = {
    "rsi": {"oversold": "Oversold Reversal", "overbought": "Overbought Fade", "strong": "Momentum Ride"},
    "vix": {"low": "Low-Vol Grind", "elevated": "Volatility Play", "extreme": "Fear Capitulation"},
    "time": {"morning": "Morning Session", "power_hour": "Power Hour", "close": "EOD Squeeze"},
    "day": {"monday": "Monday Open", "friday": "Friday Setup"},
    "volume": {"high": "Volume Breakout", "extreme": "Volume Climax"},
    "trend": {"bull": "Bull Trend Continuation", "bear": "Bear Market Entry"},
    "event": {"fomc": "FOMC Play", "earnings": "Earnings Drift", "opex": "OPEX Week"},
}

FEATURE_LABELS = {
    "rsi_14": "RSI(14)", "rsi_7": "RSI(7)", "rsi_21": "RSI(21)",
    "vix_level": "VIX", "volume_ratio": "Volume Ratio",
    "is_friday": "Friday", "is_monday": "Monday",
    "is_power_hour": "Power Hour", "is_first_hour": "First Hour", "is_last_hour": "Last Hour",
    "macd_cross_up": "MACD Bullish Cross", "above_all_sma": "Above All MAs",
    "bb_position": "Bollinger Position", "adx_14": "ADX(14)",
    "momentum_composite": "Momentum Score", "momentum_acceleration": "Momentum Accel",
    "market_regime_sma": "Market Regime", "trend_strength": "Trend Strength",
    "days_to_fomc": "Days to FOMC", "days_to_earnings": "Days to Earnings",
    "days_to_opex": "Days to OPEX", "is_opex_week": "OPEX Week",
    "ticker_win_rate_5": "Ticker WR(5)", "ticker_win_rate_10": "Ticker WR(10)",
    "streak_same_ticker": "Ticker Streak", "spy_return_1d": "SPY Return",
    "corr_spy_20d": "SPY Correlation", "return_1d": "1D Return",
    "return_5d": "5D Return", "return_20d": "20D Return",
    "hour_of_day": "Hour", "day_of_week": "Day of Week",
}


def _fmt_condition(feature: str, threshold: float, direction: str) -> str:
    """Human-readable condition string."""
    label = FEATURE_LABELS.get(feature, feature.replace("_", " ").title())
    if direction == "<=":
        return f"{label} <= {threshold:.2f}"
    return f"{label} > {threshold:.2f}"


def _generate_strategy_name(conditions: list[str], win_rate: float, ticker: str | None = None) -> str:
    """Generate a descriptive strategy name from conditions."""
    parts = []
    cond_text = " ".join(conditions).lower()

    if "rsi" in cond_text and "> 70" in cond_text:
        parts.append("Overbought")
    elif "rsi" in cond_text and "<= 30" in cond_text:
        parts.append("Oversold Reversal")
    elif "momentum" in cond_text and "> 0" in cond_text:
        parts.append("Momentum")

    if "power hour" in cond_text or "last hour" in cond_text:
        parts.append("Power Hour")
    elif "first hour" in cond_text:
        parts.append("Opening")
    elif "friday" in cond_text:
        parts.append("Friday")
    elif "monday" in cond_text:
        parts.append("Monday")

    if "vix" in cond_text and "<= 15" in cond_text:
        parts.append("Low-Vol")
    elif "vix" in cond_text and "> 25" in cond_text:
        parts.append("High-Vol")

    if "fomc" in cond_text:
        parts.append("FOMC")
    elif "earnings" in cond_text:
        parts.append("Earnings")
    elif "opex" in cond_text:
        parts.append("OPEX")

    if "volume" in cond_text and "> 1.5" in cond_text:
        parts.append("Volume Surge")
    if "macd" in cond_text and "bullish" in cond_text:
        parts.append("MACD Cross")
    if "above all" in cond_text:
        parts.append("Uptrend")

    if ticker:
        parts.append(ticker)

    if win_rate >= 0.85:
        parts.append("Edge")
    elif win_rate >= 0.75:
        parts.append("Setup")
    else:
        parts.append("Pattern")

    return " ".join(parts) if parts else "Trading Pattern"


def _extract_tree_rules(df: pd.DataFrame, feature_cols: list[str], baseline_wr: float) -> list[dict]:
    """Extract multi-condition trading rules from a shallow decision tree."""
    try:
        from sklearn.tree import DecisionTreeClassifier
    except ImportError:
        return []

    X = df[feature_cols].fillna(0).values
    y = df["is_profitable"].astype(int).values

    if len(np.unique(y)) < 2 or len(X) < 20:
        return []

    tree = DecisionTreeClassifier(
        max_depth=4, min_samples_leaf=max(8, len(X) // 50),
        class_weight="balanced", random_state=42,
    )
    tree.fit(X, y)

    tree_ = tree.tree_
    feature_names = feature_cols
    patterns = []

    def _walk(node_id: int, conditions: list, depth: int):
        if tree_.feature[node_id] == -2:  # leaf
            n_samples = int(tree_.n_node_samples[node_id])
            n_positive = int(tree_.value[node_id][0][1])
            wr = n_positive / n_samples if n_samples > 0 else 0

            if n_samples >= 8 and len(conditions) >= 2:
                edge = wr - baseline_wr
                if abs(edge) >= 0.05:
                    cond_strs = [_fmt_condition(f, t, d) for f, t, d in conditions]
                    name = _generate_strategy_name(cond_strs, wr)
                    patterns.append({
                        "name": name,
                        "strategy_type": "decision_tree_rule",
                        "conditions": cond_strs,
                        "condition": " AND ".join(cond_strs),
                        "win_rate": round(wr, 4),
                        "edge_vs_baseline": round(edge, 4),
                        "sample_size": n_samples,
                        "depth": len(conditions),
                    })
            return

        feat = feature_names[tree_.feature[node_id]]
        threshold = round(float(tree_.threshold[node_id]), 4)

        _walk(tree_.children_left[node_id], conditions + [(feat, threshold, "<=")], depth + 1)
        _walk(tree_.children_right[node_id], conditions + [(feat, threshold, ">")], depth + 1)

    _walk(0, [], 0)
    return patterns


def _mine_grouped_strategies(df: pd.DataFrame, baseline_wr: float) -> list[dict]:
    """Mine profitable patterns from grouped feature combinations."""
    patterns = []
    min_bucket = max(8, len(df) // 50)

    def _add_pattern(name, strategy_type, condition, subset):
        if len(subset) < min_bucket:
            return
        wr = float(subset["is_profitable"].mean())
        edge = wr - baseline_wr
        if abs(edge) < 0.05:
            return
        avg_ret = float(subset["pnl_pct"].mean()) if "pnl_pct" in subset.columns else 0
        patterns.append({
            "name": name,
            "strategy_type": strategy_type,
            "condition": condition,
            "conditions": [condition],
            "win_rate": round(wr, 4),
            "edge_vs_baseline": round(edge, 4),
            "sample_size": int(len(subset)),
            "avg_return": round(avg_ret, 4),
        })

    # Ticker + time-of-day combos
    if "ticker" in df.columns and "hour_of_day" in df.columns:
        for (ticker, hour), grp in df.groupby(["ticker", "hour_of_day"]):
            session = "Morning" if hour < 11 else "Midday" if hour < 14 else "Afternoon"
            _add_pattern(
                f"{ticker} {session} ({hour}:00)",
                "ticker_time", f"ticker == {ticker} AND hour == {hour}", grp,
            )

    # Ticker + day-of-week
    if "ticker" in df.columns and "day_of_week" in df.columns:
        day_names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday"}
        for (ticker, dow), grp in df.groupby(["ticker", "day_of_week"]):
            _add_pattern(
                f"{ticker} {day_names.get(dow, str(dow))} Setup",
                "ticker_day", f"ticker == {ticker} AND day == {day_names.get(dow, str(dow))}", grp,
            )

    # Ticker + market regime
    if "ticker" in df.columns and "market_regime_sma" in df.columns:
        regime_names = {1: "Bull Trend", -1: "Bear Trend", 0: "Choppy Market"}
        for (ticker, regime), grp in df.groupby(["ticker", "market_regime_sma"]):
            _add_pattern(
                f"{ticker} {regime_names.get(regime, 'Mixed')}",
                "ticker_regime", f"ticker == {ticker} AND regime == {regime_names.get(regime, 'mixed')}", grp,
            )

    # Session + momentum
    if "is_power_hour" in df.columns and "momentum_composite" in df.columns:
        ph = df[df["is_power_hour"] == 1] if "is_power_hour" in df.columns else pd.DataFrame()
        if len(ph) >= min_bucket:
            pos_mom = ph[ph["momentum_composite"] > 0]
            _add_pattern("Power Hour Momentum Play", "session_momentum",
                         "is_power_hour AND momentum > 0", pos_mom)
            neg_mom = ph[ph["momentum_composite"] <= 0]
            _add_pattern("Power Hour Reversal", "session_momentum",
                         "is_power_hour AND momentum <= 0", neg_mom)

    # Event proximity patterns
    if "days_to_fomc" in df.columns:
        fomc_near = df[(df["days_to_fomc"].abs() <= 3)]
        _add_pattern("FOMC Week Play", "event_driven", "abs(days_to_fomc) <= 3", fomc_near)
        fomc_day = df[df["days_to_fomc"] == 0]
        _add_pattern("FOMC Day Entry", "event_driven", "days_to_fomc == 0", fomc_day)

    if "days_to_earnings" in df.columns:
        earn_near = df[df["days_to_earnings"].abs() <= 2]
        _add_pattern("Earnings Proximity", "event_driven", "abs(days_to_earnings) <= 2", earn_near)

    if "is_opex_week" in df.columns:
        opex = df[df["is_opex_week"] == 1]
        _add_pattern("OPEX Week", "event_driven", "is_opex_week == 1", opex)

    # RSI + Volume combos
    if "rsi_14" in df.columns and "volume_ratio" in df.columns:
        oversold_vol = df[(df["rsi_14"] < 30) & (df["volume_ratio"] > 1.5)]
        _add_pattern("Oversold + Volume Surge", "technical_combo",
                     "RSI < 30 AND volume_ratio > 1.5", oversold_vol)
        overbought_vol = df[(df["rsi_14"] > 70) & (df["volume_ratio"] > 1.5)]
        _add_pattern("Overbought + Volume Surge", "technical_combo",
                     "RSI > 70 AND volume_ratio > 1.5", overbought_vol)

    # MACD + trend
    if "macd_cross_up" in df.columns and "above_all_sma" in df.columns:
        bull_macd = df[(df["macd_cross_up"] == 1) & (df["above_all_sma"] == 1)]
        _add_pattern("MACD Cross in Uptrend", "technical_combo",
                     "MACD cross up AND above all SMAs", bull_macd)

    # VIX regime patterns
    if "vix_level" in df.columns:
        for lo, hi, label in [(0, 15, "Low VIX Calm"), (15, 25, "Normal VIX"), (25, 40, "Elevated VIX"), (40, 100, "Extreme VIX")]:
            mask = (df["vix_level"] >= lo) & (df["vix_level"] < hi)
            _add_pattern(f"{label} Environment", "regime", f"VIX {lo}-{hi}", df[mask])

    # Ticker-level win rates (high performers)
    if "ticker" in df.columns:
        for ticker, grp in df.groupby("ticker"):
            if len(grp) >= min_bucket:
                wr = float(grp["is_profitable"].mean())
                if wr - baseline_wr >= 0.05:
                    avg_ret = float(grp["pnl_pct"].mean()) if "pnl_pct" in grp.columns else 0
                    patterns.append({
                        "name": f"{ticker} Specialist",
                        "strategy_type": "ticker_edge",
                        "condition": f"ticker == {ticker}",
                        "conditions": [f"ticker == {ticker}"],
                        "win_rate": round(wr, 4),
                        "edge_vs_baseline": round(wr - baseline_wr, 4),
                        "sample_size": int(len(grp)),
                        "avg_return": round(avg_ret, 4),
                    })

    return patterns


def discover_patterns(df: pd.DataFrame, n_patterns: int = 60) -> list[dict]:
    """Mine trading strategies using decision-tree rules and grouped aggregations."""
    if len(df) < 10 or "is_profitable" not in df.columns:
        return []

    baseline_wr = float(df["is_profitable"].mean())
    baseline_ret = float(df["pnl_pct"].mean()) if "pnl_pct" in df.columns else 0

    # Overall stats (always included)
    patterns = [{
        "name": "Baseline Performance",
        "strategy_type": "baseline",
        "condition": "all trades",
        "conditions": ["all trades"],
        "win_rate": round(baseline_wr, 4),
        "edge_vs_baseline": 0.0,
        "sample_size": len(df),
        "avg_return": round(baseline_ret, 4),
        "description": f"Overall performance across {len(df)} trades",
    }]

    # Phase 1: Decision-tree rule extraction
    exclude = {"trade_id", "is_profitable", "entry_message_raw", "exit_messages_raw",
               "entry_time", "exit_time_first", "exit_time_final", "weighted_exit_price",
               "entry_price", "exit_pct_25", "exit_pct_50", "exit_pct_75", "exit_pct_100",
               "pnl_pct", "hold_duration_hours", "analyst", "channel", "ticker", "side",
               "option_type", "expiry", "signal_type"}
    feature_cols = [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]

    if len(feature_cols) >= 5:
        tree_rules = _extract_tree_rules(df, feature_cols, baseline_wr)
        patterns.extend(tree_rules)

    # Phase 2: Grouped strategy mining
    grouped = _mine_grouped_strategies(df, baseline_wr)
    patterns.extend(grouped)

    # Score: edge weighted by log(sample_size)
    for p in patterns:
        edge = abs(p.get("edge_vs_baseline", 0))
        p["score"] = edge * np.log1p(p["sample_size"])

    # Deduplicate by name, keep highest score
    seen = {}
    for p in patterns:
        key = p["name"]
        if key not in seen or p["score"] > seen[key]["score"]:
            seen[key] = p
    patterns = list(seen.values())

    patterns.sort(key=lambda p: p["score"], reverse=True)
    return patterns[:n_patterns]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data)
    df = pd.read_parquet(data_dir / "enriched.parquet")
    if len(df) == 0:
        with open(args.output, "w") as f:
            json.dump([], f, indent=2)
        print("Discovered 0 patterns (empty enriched data)")
        try:
            from report_to_phoenix import report_progress
            report_progress("patterns", "Pattern discovery complete", 80, {"pattern_count": 0})
        except Exception:
            pass
        return

    patterns = discover_patterns(df)

    with open(args.output, "w") as f:
        json.dump(patterns, f, indent=2)

    print(f"Discovered {len(patterns)} trading strategies")
    for p in patterns[:15]:
        edge_str = f"+{p['edge_vs_baseline']:.1%}" if p['edge_vs_baseline'] > 0 else f"{p['edge_vs_baseline']:.1%}"
        print(f"  {p['name']}: WR={p['win_rate']:.1%} ({edge_str} edge), n={p['sample_size']}, type={p['strategy_type']}")

    try:
        from report_to_phoenix import report_progress
        report_progress("patterns", "Pattern discovery complete", 80, {
            "pattern_count": len(patterns),
            "patterns": patterns,
        })
    except Exception:
        pass


if __name__ == "__main__":
    main()
