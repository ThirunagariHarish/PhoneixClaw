"""LLM-powered trading strategy analyzer.

Takes statistically-mined patterns from discover_patterns.py and uses Claude
to generate real trading strategy narratives, entry/exit rules, and an
overall analyst profile.
"""

import argparse
import json
import os
from pathlib import Path

import pandas as pd


def _build_prompt(analyst_name: str, channel_name: str, patterns: list, summary: dict,
                  feature_importances: list | None, model_results: list | None) -> str:
    top_patterns = patterns[:20]
    patterns_text = json.dumps(top_patterns, indent=2)

    model_text = ""
    if model_results:
        model_text = "\n## Model Performance\n"
        for m in model_results:
            model_text += f"- {m.get('model_name', '?')}: AUC={m.get('auc_roc', 0):.3f}, Acc={m.get('accuracy', 0):.1%}\n"

    features_text = ""
    if feature_importances:
        features_text = "\n## Top Predictive Features\n"
        for f in feature_importances[:15]:
            features_text += f"- {f.get('feature', '?')}: importance={f.get('importance', 0):.4f}\n"

    return f"""You are a quantitative trading analyst. Analyze the following backtesting results for **{analyst_name}** from the **{channel_name}** Discord trading channel.

## Trade Summary
- Total trades: {summary.get('total_trades', 0)}
- Overall win rate: {summary.get('win_rate', 0):.1%}
- Average return per trade: {summary.get('avg_return', 0):.2%}
- Most traded tickers: {summary.get('top_tickers', 'N/A')}
- Date range: {summary.get('date_range', 'N/A')}
{model_text}
{features_text}
## Discovered Statistical Patterns
{patterns_text}

## Your Task

Based on the above data, produce a JSON response with these fields:

1. **"analyst_profile"**: A 2-3 sentence description of {analyst_name}'s trading style (e.g. "Vinod is a momentum-driven intraday trader who favors SPX options during high-volume sessions with a strong edge in power hour entries.")

2. **"strategies"**: An array of the top 5-8 most actionable trading strategies. For each:
   - **"name"**: A catchy strategy name (e.g. "The FOMC Breakout Play", "Friday Power Hour Scalp")
   - **"description"**: 2-3 sentences describing the strategy in plain English
   - **"entry_rules"**: Specific conditions for entering the trade
   - **"exit_rules"**: How the analyst typically exits
   - **"edge"**: Why this strategy works (the statistical edge)
   - **"risk_notes"**: When to avoid or be cautious
   - **"win_rate"**: The win rate for this strategy
   - **"sample_size"**: How many trades match this pattern

3. **"regime_insights"**: How {analyst_name}'s performance varies by market regime (bull/bear/choppy, high/low VIX)

4. **"temporal_insights"**: Time-based patterns (best days, best hours, event-driven edges)

5. **"risk_factors"**: Key risks and blind spots in this trading approach

Respond with ONLY the JSON object, no markdown fences or explanation."""


def _call_claude(prompt: str) -> dict | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)
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
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=120,
            )
            if resp.status_code == 200:
                text = resp.json()["content"][0]["text"].strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                return json.loads(text)
        except Exception as e:
            print(f"LLM API call failed: {e}")
    except Exception as e:
        print(f"LLM analysis failed: {e}")

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Data directory with enriched.parquet and patterns.json")
    parser.add_argument("--output", required=True, help="Output path for llm_patterns.json")
    parser.add_argument("--config", help="Path to config.json for analyst/channel info")
    args = parser.parse_args()

    data_dir = Path(args.data)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    patterns_file = data_dir / "patterns.json"
    if not patterns_file.exists():
        patterns_file = data_dir / "models" / "patterns.json"
    patterns = json.loads(patterns_file.read_text()) if patterns_file.exists() else []

    analyst_name = "the analyst"
    channel_name = "trading channel"
    if args.config and Path(args.config).exists():
        cfg = json.loads(Path(args.config).read_text())
        analyst_name = cfg.get("analyst_name", analyst_name)
        channel_name = cfg.get("channel_name", channel_name)

    summary = {"total_trades": 0, "win_rate": 0, "avg_return": 0, "top_tickers": "N/A", "date_range": "N/A"}
    enriched_path = data_dir / "enriched.parquet"
    if enriched_path.exists():
        df = pd.read_parquet(enriched_path)
        summary["total_trades"] = len(df)
        if "is_profitable" in df.columns:
            summary["win_rate"] = float(df["is_profitable"].mean())
        if "pnl_pct" in df.columns:
            summary["avg_return"] = float(df["pnl_pct"].mean())
        if "ticker" in df.columns:
            top = df["ticker"].value_counts().head(5)
            summary["top_tickers"] = ", ".join(f"{t}({c})" for t, c in top.items())
        if "entry_time" in df.columns:
            try:
                dates = pd.to_datetime(df["entry_time"])
                summary["date_range"] = f"{dates.min().date()} to {dates.max().date()}"
            except Exception:
                pass

    feature_importances = None
    explain_file = data_dir / "models" / "explainability.json"
    if not explain_file.exists():
        explain_file = data_dir / "explainability.json"
    if explain_file.exists():
        try:
            explain = json.loads(explain_file.read_text())
            feature_importances = explain.get("top_features", [])
        except Exception:
            pass

    model_results = None
    for candidate in [data_dir / "models" / "best_model.json", data_dir / "best_model.json"]:
        if candidate.exists():
            try:
                best = json.loads(candidate.read_text())
                model_results = best.get("all_results", [])
            except Exception:
                pass
            break

    if not patterns:
        print("No patterns to analyze — writing empty LLM patterns")
        output_path.write_text(json.dumps({"strategies": [], "analyst_profile": "", "note": "No patterns discovered"}, indent=2))
        return

    prompt = _build_prompt(analyst_name, channel_name, patterns, summary, feature_importances, model_results)
    print(f"Sending {len(patterns)} patterns to Claude for strategy analysis...")

    llm_result = _call_claude(prompt)

    if llm_result:
        llm_result["statistical_patterns"] = patterns
        output_path.write_text(json.dumps(llm_result, indent=2))
        n_strategies = len(llm_result.get("strategies", []))
        print(f"LLM generated {n_strategies} trading strategies + analyst profile")
        if llm_result.get("analyst_profile"):
            print(f"  Profile: {llm_result['analyst_profile'][:200]}")
        for s in llm_result.get("strategies", [])[:5]:
            print(f"  Strategy: {s.get('name', '?')} — WR={s.get('win_rate', '?')}, n={s.get('sample_size', '?')}")
    else:
        print("LLM analysis unavailable — using statistical patterns only")
        fallback = {
            "analyst_profile": f"{analyst_name} trades in {channel_name} with {summary['win_rate']:.0%} win rate across {summary['total_trades']} trades.",
            "strategies": [
                {
                    "name": p.get("name", "Pattern"),
                    "description": p.get("condition", ""),
                    "win_rate": p.get("win_rate", 0),
                    "sample_size": p.get("sample_size", 0),
                    "edge": f"{p.get('edge_vs_baseline', 0):+.1%} vs baseline",
                }
                for p in patterns[:8]
            ],
            "statistical_patterns": patterns,
        }
        output_path.write_text(json.dumps(fallback, indent=2))

    try:
        from report_to_phoenix import report_progress
        report_progress("llm_patterns", "LLM strategy analysis complete", 82, {
            "llm_analysis": True if llm_result else False,
            "strategy_count": len((llm_result or {}).get("strategies", patterns[:8])),
        })
    except Exception:
        pass


if __name__ == "__main__":
    main()
