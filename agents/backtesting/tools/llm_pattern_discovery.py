"""LLM-driven pattern discovery — actually uses Claude to find trading edges.

Unlike analyze_patterns_llm.py (which only narrates existing statistical patterns),
this tool directly asks Claude to discover new patterns by examining samples of
winning and losing trades.

Two-stage pipeline:
  Stage 1 (Sonnet): Generate 15 candidate pattern hypotheses from 80 sampled trades
  Stage 2 (Opus):   Refine the top candidates after validation

Each proposed pattern is a pandas query string that gets validated against the
FULL enriched dataset — only patterns with sample_size >= 10 and |edge| >= 3%
are kept.

Usage:
    python llm_pattern_discovery.py \
        --data output/vN/ \
        --explainability output/vN/explainability.json \
        --output output/vN/llm_discovered_patterns.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path


# P12: default to Opus 4.6 (financial reasoning leader per research benchmark)
# with a Sonnet fallback for the cost-sensitive path.
STAGE1_MODEL = os.getenv("LLM_DISCOVERY_MODEL", "claude-opus-4-6")
STAGE2_MODEL = os.getenv("LLM_REFINEMENT_MODEL", "claude-opus-4-6")
# Back-compat aliases — some callers still import these names
SONNET_MODEL = STAGE1_MODEL
OPUS_MODEL = STAGE2_MODEL

# P12: sample size + edge thresholds
SAMPLES_PER_CLASS = int(os.getenv("LLM_SAMPLES_PER_CLASS", "200"))
MIN_EDGE = float(os.getenv("LLM_MIN_EDGE", "0.02"))
MIN_SAMPLE_SIZE = int(os.getenv("LLM_MIN_SAMPLE_SIZE", "20"))
N_CANDIDATES = int(os.getenv("LLM_N_CANDIDATES", "25"))

# P12: market regimes we stratify sampling over so patterns span the cycle
REGIMES = ["bull_quiet", "bull_volatile", "bear_quiet", "bear_volatile", "choppy"]

# Features that are LEAKY (describe analyst's past behavior, not market conditions).
# We explicitly tell Claude to avoid these.
LEAKY_FEATURES = [
    "analyst_win_rate_10", "analyst_win_rate_20", "analyst_avg_pnl_10",
    "analyst_win_streak", "ticker_win_rate_5", "ticker_win_rate_10",
    "ticker_avg_pnl_5", "ticker_trade_count", "streak_same_ticker",
    "days_since_last_trade", "days_since_last_win",
]

LEAKY_PREFIXES = ("analyst_", "ticker_win_rate", "ticker_avg_pnl",
                  "ticker_trade_count", "streak_", "days_since_last")


def _is_leaky(feature_name: str) -> bool:
    if feature_name in LEAKY_FEATURES:
        return True
    return any(feature_name.startswith(p) for p in LEAKY_PREFIXES)


def _load_explainability(path: Path) -> list[dict]:
    """Load top feature importance from explainability.json."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        top = data.get("top_features", [])
        return [f for f in top if not _is_leaky(f.get("feature", ""))][:30]
    except Exception:
        return []


def _sample_trades(df, n_per_class: int = SAMPLES_PER_CLASS) -> list[dict]:
    """Regime-stratified sample of winners and losers (P12).

    Splits `n_per_class` evenly across detected regimes (when a `market_regime`
    column is available) so patterns aren't dominated by one bull phase. Falls
    back to a global sample when no regime column exists.
    """
    if "is_profitable" not in df.columns:
        return []

    winners = df[df["is_profitable"] == True]
    losers = df[df["is_profitable"] == False]

    regime_col = "market_regime" if "market_regime" in df.columns else None

    if regime_col is None:
        n_w = min(n_per_class, len(winners))
        n_l = min(n_per_class, len(losers))
        win_sample = winners.sample(n=n_w, random_state=42) if n_w > 0 else winners.iloc[0:0]
        lose_sample = losers.sample(n=n_l, random_state=42) if n_l > 0 else losers.iloc[0:0]
        return _format_trades(win_sample, "WIN") + _format_trades(lose_sample, "LOSS")

    per_regime = max(5, n_per_class // max(1, len(REGIMES)))
    win_chunks = []
    lose_chunks = []
    for regime in REGIMES:
        w = winners[winners[regime_col] == regime]
        l = losers[losers[regime_col] == regime]
        if len(w) > 0:
            win_chunks.append(w.sample(n=min(per_regime, len(w)), random_state=42))
        if len(l) > 0:
            lose_chunks.append(l.sample(n=min(per_regime, len(l)), random_state=42))

    import pandas as _pd
    win_sample = _pd.concat(win_chunks) if win_chunks else winners.iloc[0:0]
    lose_sample = _pd.concat(lose_chunks) if lose_chunks else losers.iloc[0:0]

    # Top up with a global sample if regime stratification undershoots
    deficit_w = n_per_class - len(win_sample)
    deficit_l = n_per_class - len(lose_sample)
    if deficit_w > 0 and len(winners) > len(win_sample):
        extra = winners.drop(win_sample.index, errors="ignore")
        if len(extra) > 0:
            win_sample = _pd.concat([win_sample, extra.sample(n=min(deficit_w, len(extra)), random_state=43)])
    if deficit_l > 0 and len(losers) > len(lose_sample):
        extra = losers.drop(lose_sample.index, errors="ignore")
        if len(extra) > 0:
            lose_sample = _pd.concat([lose_sample, extra.sample(n=min(deficit_l, len(extra)), random_state=43)])

    return _format_trades(win_sample, "WIN") + _format_trades(lose_sample, "LOSS")


def _format_trades(df_subset, label: str) -> list[dict]:
    """Format trades as compact dicts with the most informative market features."""
    if len(df_subset) == 0:
        return []

    key_features = [
        "ticker", "hour_of_day", "day_of_week", "month",
        "rsi_14", "macd_histogram", "bb_position", "atr_pct",
        "vix_level", "volume_ratio_20", "sma_20_50_cross", "above_all_sma",
        "return_1d", "return_5d", "return_20d",
        "sentiment_score", "sentiment_bullish",
        "days_to_fomc", "days_to_earnings", "is_opex_week",
        "is_friday", "is_monday", "is_power_hour", "is_first_hour",
        "gex_value", "iv_rank", "options_put_call_ratio",
        "pnl_pct",
    ]
    available = [c for c in key_features if c in df_subset.columns]

    result = []
    for _, row in df_subset.iterrows():
        trade = {"outcome": label}
        for col in available:
            val = row[col]
            try:
                import math
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    continue
                if isinstance(val, (int, bool)):
                    trade[col] = int(val)
                elif isinstance(val, float):
                    trade[col] = round(val, 4)
                else:
                    trade[col] = str(val)
            except Exception:
                pass
        result.append(trade)
    return result


def _build_discovery_prompt(samples: list[dict], feature_importance: list[dict],
                             baseline_wr: float, analyst_name: str) -> str:
    """Build the Stage 1 prompt for Sonnet."""
    samples_text = json.dumps(samples, indent=1)
    features_text = ""
    if feature_importance:
        features_text = "\n## Top Predictive Features (from trained model)\n"
        for f in feature_importance[:20]:
            features_text += f"- {f.get('feature', '?')}: importance={f.get('importance', 0):.4f}\n"

    leaky_list = ", ".join(LEAKY_FEATURES[:6]) + ", ..."

    return f"""You are a quantitative trading analyst. Your job is to discover **market-conditioned trading patterns** from a Discord analyst's backtested trades.

## Context
- Analyst: {analyst_name}
- Baseline win rate: {baseline_wr:.1%}
- I'm giving you {len(samples)} sampled trades (winners labeled "WIN", losers labeled "LOSS")

## Sample Trades
{samples_text}
{features_text}
## Your Task
Find {N_CANDIDATES - 5} to {N_CANDIDATES} candidate trading patterns that distinguish WIN from LOSS outcomes across multiple market regimes.

### Hard Constraints
1. **DO NOT use any "leaky" features** that describe the analyst's past behavior:
   - Avoid: {leaky_list}
   - These are circular (they describe the analyst, not the market)
2. Each pattern must be expressible as a **pandas boolean query string** that can run against the full enriched dataframe
3. Each pattern must reference at least 1 market feature (RSI, VIX, volume, time, event proximity, etc.)
4. Prefer multi-condition patterns (2-3 conditions) with clear thresholds
5. Use the predictive features list above as guidance for what matters

### Good pattern examples (use these as templates):
- `rsi_14 < 35 and vix_level > 20 and is_friday == 1`
- `volume_ratio_20 > 2.0 and macd_histogram > 0 and is_power_hour == 1`
- `days_to_fomc <= 2 and return_5d < -0.02 and above_all_sma == 0`
- `sentiment_bullish == 1 and gex_value > 0 and hour_of_day >= 10 and hour_of_day <= 11`

### Output format (strict JSON array, NO markdown fences, NO commentary)
```
[
  {{
    "name": "short descriptive name",
    "condition": "pandas query string",
    "plain_english": "ONE sentence describing this to a human trader WITHOUT using feature names (e.g., 'Oversold on a Friday with a volatility spike' not 'rsi_14 < 35 and is_friday == 1 and vix > 20')",
    "rationale": "one sentence explaining why this edge might exist",
    "expected_direction": "favors_wins" or "avoids_losses",
    "regime": "bull_quiet | bull_volatile | bear_quiet | bear_volatile | choppy | any"
  }},
  ...
]
```

Respond with ONLY the JSON array."""


def _call_claude(prompt: str, model: str, max_tokens: int = 4096) -> str | None:
    """Call the Claude API and return the raw text response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  [llm_discovery] ANTHROPIC_API_KEY not set, skipping LLM discovery")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return text
    except ImportError:
        try:
            import httpx
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=120,
            )
            if resp.status_code == 200:
                text = resp.json()["content"][0]["text"].strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                return text
        except Exception as exc:
            print(f"  [llm_discovery] HTTP call failed: {exc}")
    except Exception as exc:
        print(f"  [llm_discovery] API call failed: {exc}")
    return None


def _parse_candidates(text: str) -> list[dict]:
    """Parse LLM response into a list of candidate patterns."""
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "patterns" in data:
            return data["patterns"]
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        import re
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return []


def _validate_candidate(candidate: dict, df, baseline_wr: float) -> dict | None:
    """Apply the candidate's pandas query to the full dataset and measure edge.

    Returns the enriched pattern dict if it passes validation, None otherwise.
    """
    query = candidate.get("condition", "")
    if not query:
        return None

    # Safety: reject queries that reference leaky features
    for leaky in LEAKY_FEATURES:
        if leaky in query:
            return None
    for prefix in LEAKY_PREFIXES:
        if prefix in query:
            return None

    try:
        subset = df.query(query)
    except Exception as exc:
        return None

    n = len(subset)
    if n < MIN_SAMPLE_SIZE:
        return None

    if "is_profitable" not in subset.columns:
        return None

    wr = float(subset["is_profitable"].mean())
    edge = wr - baseline_wr
    if abs(edge) < MIN_EDGE:
        return None

    avg_return = 0.0
    if "pnl_pct" in subset.columns:
        avg_return = float(subset["pnl_pct"].mean())

    import numpy as _np
    return {
        "name": candidate.get("name", "LLM Pattern"),
        "condition": query,
        "conditions": [query],
        "plain_english": candidate.get("plain_english", ""),
        "rationale": candidate.get("rationale", ""),
        "expected_direction": candidate.get("expected_direction", ""),
        "regime": candidate.get("regime", "any"),
        "win_rate": round(wr, 4),
        "edge_vs_baseline": round(edge, 4),
        "sample_size": int(n),
        "avg_return": round(avg_return, 4),
        "source": "llm_discovery",
        "strategy_type": "llm_hypothesis",
        "score": round(abs(edge) * float(_np.log1p(n)), 4),
    }


def _build_refinement_prompt(validated: list[dict], baseline_wr: float) -> str:
    """Stage 2 prompt: ask Opus to refine the top candidates."""
    candidates_text = json.dumps(validated, indent=2)
    return f"""You previously proposed trading pattern candidates. I've now validated them against the full dataset.

## Baseline win rate
{baseline_wr:.1%}

## Validated Candidates (all passed sample_size >= 10 and |edge| >= 3%)
{candidates_text}

## Your Task
Pick the **5-8 strongest patterns** and refine them. For each:
1. Improve the name (make it catchy and descriptive)
2. Keep the condition string EXACTLY as validated (don't change thresholds — they're proven)
3. Write a 2-sentence rationale explaining the market mechanism behind the edge
4. Add a "risk_note" field describing when this pattern might fail
5. Rewrite `plain_english` so a non-technical trader would instantly understand it (NO feature names, NO numbers with underscores)

### Output format (strict JSON array, NO markdown fences)
```
[
  {{
    "name": "improved name",
    "condition": "same condition as input",
    "plain_english": "human-friendly sentence",
    "rationale": "2 sentences on the market mechanism",
    "risk_note": "when this pattern fails",
    "win_rate": <from input>,
    "edge_vs_baseline": <from input>,
    "sample_size": <from input>
  }}
]
```

Respond with ONLY the JSON array."""


def discover(data_dir: Path, explainability_path: Path | None, output_path: Path) -> dict:
    """Main discovery pipeline."""
    result_summary = {
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "stage_1_model": SONNET_MODEL,
        "stage_2_model": OPUS_MODEL,
        "candidates_generated": 0,
        "candidates_validated": 0,
        "refined": 0,
        "errors": [],
    }

    # Load enriched data
    enriched_path = data_dir / "enriched.parquet"
    if not enriched_path.exists():
        enriched_path = data_dir.parent / "enriched.parquet"
    if not enriched_path.exists():
        result_summary["errors"].append("enriched.parquet not found")
        output_path.write_text(json.dumps([], indent=2))
        return result_summary

    try:
        import pandas as pd
        df = pd.read_parquet(enriched_path)
    except Exception as exc:
        result_summary["errors"].append(f"Failed to load enriched: {exc}")
        output_path.write_text(json.dumps([], indent=2))
        return result_summary

    if len(df) < 20 or "is_profitable" not in df.columns:
        result_summary["errors"].append(f"Insufficient data: {len(df)} rows")
        output_path.write_text(json.dumps([], indent=2))
        return result_summary

    baseline_wr = float(df["is_profitable"].mean())
    result_summary["baseline_win_rate"] = round(baseline_wr, 4)
    result_summary["total_trades"] = len(df)

    # Load config for analyst name
    analyst_name = "Unknown Analyst"
    config_candidates = [data_dir / "config.json", data_dir.parent / "config.json"]
    for cfg_path in config_candidates:
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                analyst_name = cfg.get("analyst_name") or cfg.get("channel_name", analyst_name)
                break
            except Exception:
                pass

    # Load feature importance
    feature_importance = []
    if explainability_path and explainability_path.exists():
        feature_importance = _load_explainability(explainability_path)
    result_summary["features_loaded"] = len(feature_importance)

    # Sample trades (regime-stratified)
    samples = _sample_trades(df, n_per_class=SAMPLES_PER_CLASS)
    result_summary["samples_drawn"] = len(samples)
    if len(samples) < 20:
        result_summary["errors"].append("Not enough samples for LLM discovery")
        output_path.write_text(json.dumps([], indent=2))
        return result_summary

    # Stage 1: Sonnet generates candidates
    print(f"  [llm_discovery] Stage 1: {SONNET_MODEL} generating candidates...")
    prompt = _build_discovery_prompt(samples, feature_importance, baseline_wr, analyst_name)
    stage1_response = _call_claude(prompt, SONNET_MODEL, max_tokens=4096)
    if not stage1_response:
        result_summary["errors"].append("Stage 1 API call failed")
        output_path.write_text(json.dumps([], indent=2))
        return result_summary

    candidates = _parse_candidates(stage1_response)
    result_summary["candidates_generated"] = len(candidates)
    print(f"  [llm_discovery] Got {len(candidates)} candidates")

    # Validate each candidate
    validated = []
    for c in candidates:
        v = _validate_candidate(c, df, baseline_wr)
        if v is not None:
            validated.append(v)
    result_summary["candidates_validated"] = len(validated)
    print(f"  [llm_discovery] {len(validated)}/{len(candidates)} candidates passed validation")

    final_patterns = validated

    # Stage 2: Opus refinement (only if we have enough candidates)
    if len(validated) >= 5:
        print(f"  [llm_discovery] Stage 2: {OPUS_MODEL} refining top patterns...")
        refine_prompt = _build_refinement_prompt(validated, baseline_wr)
        stage2_response = _call_claude(refine_prompt, OPUS_MODEL, max_tokens=3000)
        refined = _parse_candidates(stage2_response) if stage2_response else []

        if refined:
            # Merge refined metadata (rationale, risk_note) with validated stats
            refined_map = {r.get("condition", ""): r for r in refined}
            for v in validated:
                cond = v.get("condition", "")
                if cond in refined_map:
                    r = refined_map[cond]
                    v["name"] = r.get("name", v["name"])
                    v["plain_english"] = r.get("plain_english", v.get("plain_english", ""))
                    v["rationale"] = r.get("rationale", v.get("rationale", ""))
                    v["risk_note"] = r.get("risk_note", "")
                    v["refined"] = True
            result_summary["refined"] = sum(1 for v in validated if v.get("refined"))
    else:
        print(f"  [llm_discovery] Skipping Stage 2 — only {len(validated)} validated (need >= 5)")

    # Sort by score
    final_patterns.sort(key=lambda p: p.get("score", 0), reverse=True)

    # Write output
    output_path.write_text(json.dumps(final_patterns, indent=2, default=str))
    result_summary["output_path"] = str(output_path)
    result_summary["final_pattern_count"] = len(final_patterns)

    print(f"  [llm_discovery] Wrote {len(final_patterns)} patterns to {output_path}")

    # Report to Phoenix
    try:
        from report_to_phoenix import report_progress
        report_progress(
            "llm_pattern_discovery",
            f"LLM discovered {len(final_patterns)} patterns",
            -1,
            {"llm_patterns": final_patterns[:10], "summary": result_summary},
        )
    except Exception:
        pass

    return result_summary


def main():
    parser = argparse.ArgumentParser(description="LLM-driven pattern discovery")
    parser.add_argument("--data", required=True, help="Path to backtest output dir")
    parser.add_argument("--explainability", default=None, help="Path to explainability.json")
    parser.add_argument("--output", required=True, help="Path to write llm_discovered_patterns.json")
    args = parser.parse_args()

    data_dir = Path(args.data)
    expl_path = Path(args.explainability) if args.explainability else None
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary = discover(data_dir, expl_path, output_path)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
