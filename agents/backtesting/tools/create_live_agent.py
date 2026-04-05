"""Create a live trading agent from backtesting output.

Builds a manifest from backtest artifacts (patterns, models, explainability,
analyst profile), renders the agent from the live-trader-v1 template, copies
model artifacts, and writes everything to the output directory.

Usage:
    python tools/create_live_agent.py \
        --config config.json \
        --models output/models/ \
        --output ~/agents/live/spx-alerts/
"""

import argparse
import json
import math
import shutil
from datetime import datetime
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "live-trader-v1"
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
LEGACY_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "live-template"


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _detect_character(profile: dict) -> str:
    avg_hold = profile.get("avg_hold_hours", 4)
    win_rate = profile.get("win_rate", 0.5)
    is_swing = profile.get("is_swing_trader", False)

    if is_swing or avg_hold >= 24:
        return "conservative-swing"
    if avg_hold <= 2 and win_rate >= 0.65:
        return "aggressive-momentum"
    return "balanced-intraday"


def _build_analyst_profile(enriched_path: Path) -> dict:
    """Derive analyst profile from enriched trade data."""
    profile = {
        "avg_hold_hours": 4,
        "win_rate": 0.5,
        "best_tickers": [],
        "best_hours": [],
        "avg_trades_per_day": 0,
        "is_swing_trader": False,
    }

    try:
        import pandas as pd

        if not enriched_path.exists():
            return profile

        df = pd.read_parquet(enriched_path)

        if "is_profitable" in df.columns:
            profile["win_rate"] = float(df["is_profitable"].mean())

        if "hold_hours" in df.columns:
            profile["avg_hold_hours"] = float(df["hold_hours"].mean())
            profile["is_swing_trader"] = float(df["hold_hours"].median()) > 24

        if "ticker" in df.columns and "is_profitable" in df.columns:
            ticker_wr = df.groupby("ticker")["is_profitable"].agg(["mean", "count"])
            ticker_wr = ticker_wr[ticker_wr["count"] >= 5].sort_values("mean", ascending=False)
            profile["best_tickers"] = ticker_wr.head(5).index.tolist()

        if "hour_of_day" in df.columns and "is_profitable" in df.columns:
            hour_wr = df.groupby("hour_of_day")["is_profitable"].agg(["mean", "count"])
            hour_wr = hour_wr[hour_wr["count"] >= 5].sort_values("mean", ascending=False)
            profile["best_hours"] = [int(h) for h in hour_wr.head(3).index.tolist()]

        if "entry_time" in df.columns:
            days = (df["entry_time"].max() - df["entry_time"].min()).days or 1
            profile["avg_trades_per_day"] = round(len(df) / days, 1)

    except Exception:
        pass

    return profile


def _load_patterns(models_dir: Path) -> list[dict]:
    patterns_path = models_dir / "patterns.json"
    if not patterns_path.exists():
        return []
    with open(patterns_path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("patterns", data.get("rules", []))


def _load_explainability(models_dir: Path) -> dict:
    path = models_dir / "explainability.json"
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    top_features = []
    for item in data.get("feature_importance", data.get("top_features", []))[:20]:
        if isinstance(item, dict):
            top_features.append(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            top_features.append({"name": item[0], "importance": item[1]})
    return {"top_features": top_features}


def create_live_agent(config_path: str, models_dir: str, output_dir: str):
    config = _load_json(Path(config_path))
    models = Path(models_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    best_model = _load_json(models / "best_model.json")
    patterns = _load_patterns(models)
    explainability = _load_explainability(models)
    enriched_path = Path(config_path).parent / "output" / "enriched.parquet"
    analyst_profile = _build_analyst_profile(enriched_path)

    channel_name = config.get("channel_name", "unknown")
    analyst_name = config.get("analyst_name", "")
    character = _detect_character(analyst_profile)
    characters = _load_json(SCHEMA_DIR / "characters.json")
    char_def = characters.get(character, characters.get("balanced-intraday", {}))

    rules = []
    for p in patterns:
        rules.append({
            "name": p.get("name", ""),
            "condition": p.get("condition", ""),
            "weight": round(p.get("weight", 0), 3),
            "source": "backtesting",
            "enabled": True,
            "description": p.get("description", ""),
        })

    manifest = {
        "version": "1.0",
        "template": "live-trader-v1",
        "identity": {
            "name": f"{channel_name.replace('-', ' ').title()} Agent",
            "channel": channel_name,
            "channel_id": config.get("channel_id", ""),
            "server_id": config.get("server_id", ""),
            "analyst": analyst_name,
            "character": character,
        },
        "rules": rules,
        "modes": char_def.get("mode_overrides", {
            "aggressive": {"confidence_threshold": 0.60, "max_concurrent": 5, "stop_loss_pct": 25, "daily_pnl_cap": 500, "daily_loss_limit": 200},
            "conservative": {"confidence_threshold": 0.80, "max_concurrent": 2, "stop_loss_pct": 15, "daily_pnl_cap": 200, "daily_loss_limit": 100},
        }),
        "risk": config.get("risk_params", {
            "max_position_size_pct": 5.0,
            "max_daily_loss_pct": 3.0,
            "max_concurrent_positions": 3,
            "require_pattern_match": True,
            "min_pattern_matches": 2,
        }),
        "models": {
            "primary": best_model.get("best_model", best_model.get("model_type", "unknown")),
            "accuracy": best_model.get("best_score", best_model.get("accuracy", 0)),
            "auc_roc": best_model.get("auc_roc", 0),
            "version": datetime.now().strftime("%Y-%m-%d"),
            "training_trades": best_model.get("training_trades", 0),
            "all_models": best_model.get("all_models", []),
        },
        "tools": [
            "discord_listener", "inference", "enrich_single", "risk_check",
            "robinhood_mcp", "technical_analysis", "portfolio_tracker",
            "position_monitor", "pre_market_analyzer", "decision_engine",
            "report_to_phoenix",
        ],
        "skills": [
            "discord_monitor.md", "trade_execution.md", "risk_management.md",
            "position_monitoring.md", "daily_report.md", "swing_trade.md",
            "pre_market.md",
        ],
        "knowledge": {
            "top_features": explainability.get("top_features", []),
            "analyst_profile": analyst_profile,
            "channel_summary": f"Agent for {analyst_name} on #{channel_name}. "
                               f"Win rate: {analyst_profile['win_rate']:.0%}, "
                               f"Avg hold: {analyst_profile['avg_hold_hours']:.1f}h, "
                               f"Character: {character}.",
        },
        "credentials": {
            "discord_token": config.get("discord_token", ""),
            "phoenix_api_url": config.get("phoenix_api_url", ""),
            "phoenix_api_key": config.get("phoenix_api_key", ""),
            "robinhood_username": config.get("robinhood_username", ""),
            "robinhood_password": config.get("robinhood_password", ""),
            "robinhood_totp_secret": config.get("robinhood_totp_secret", ""),
        },
    }

    with open(output / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    template_tools = TEMPLATE_DIR / "tools"
    if not template_tools.exists():
        template_tools = LEGACY_TEMPLATE_DIR / "tools"
    out_tools = output / "tools"
    if template_tools.exists():
        shutil.copytree(template_tools, out_tools, dirs_exist_ok=True)

    skills_src = TEMPLATE_DIR / "skills"
    if skills_src.exists():
        shutil.copytree(skills_src, output / "skills", dirs_exist_ok=True)

    out_models = output / "models"
    out_models.mkdir(exist_ok=True)
    for artifact in models.glob("*"):
        if artifact.is_file():
            shutil.copy2(artifact, out_models / artifact.name)

    _render_claude_md(manifest, output)
    _write_config(manifest, output)
    (output / "trades.log").write_text("")

    print(f"Live agent created at {output}")
    print(f"  Channel: {channel_name}")
    print(f"  Analyst: {analyst_name}")
    print(f"  Character: {character}")
    print(f"  Model: {manifest['models']['primary']} (acc={manifest['models']['accuracy']:.2f})")
    print(f"  Rules: {len(rules)}")
    print(f"  Tools: {len(list(out_tools.glob('*.py')))} scripts")
    print(f"  Skills: {len(list((output / 'skills').glob('*.md')))} files")
    print(f"  Models: {len(list(out_models.glob('*')))} artifacts")

    return str(output)


def _render_claude_md(manifest: dict, output: Path):
    """Render CLAUDE.md from Jinja2 template or fall back to simple substitution."""
    jinja_template = TEMPLATE_DIR / "CLAUDE.md.jinja2"
    if jinja_template.exists():
        try:
            from jinja2 import Environment, FileSystemLoader

            characters = _load_json(SCHEMA_DIR / "characters.json")
            char_name = manifest.get("identity", {}).get("character", "balanced-intraday")
            char_def = characters.get(char_name, {})

            env = Environment(
                loader=FileSystemLoader(str(TEMPLATE_DIR)),
                keep_trailing_newline=True,
                trim_blocks=True,
                lstrip_blocks=True,
            )
            template = env.get_template("CLAUDE.md.jinja2")
            rendered = template.render(
                **manifest,
                character_description=char_def.get("description", "Balanced trading agent."),
                current_mode=char_def.get("default_mode", "conservative"),
            )
            (output / "CLAUDE.md").write_text(rendered)
            return
        except ImportError:
            pass

    legacy = LEGACY_TEMPLATE_DIR / "CLAUDE.md"
    if legacy.exists():
        text = legacy.read_text()
        identity = manifest.get("identity", {})
        text = text.replace("{{channel_name}}", identity.get("channel", ""))
        text = text.replace("{{analyst_name}}", identity.get("analyst", ""))
        (output / "CLAUDE.md").write_text(text)


def _write_config(manifest: dict, output: Path):
    identity = manifest.get("identity", {})
    risk = manifest.get("risk", {})
    models = manifest.get("models", {})
    creds = manifest.get("credentials", {})

    config = {
        "agent_name": identity.get("name", ""),
        "channel_name": identity.get("channel", ""),
        "channel_id": identity.get("channel_id", ""),
        "server_id": identity.get("server_id", ""),
        "analyst_name": identity.get("analyst", ""),
        "current_mode": manifest.get("modes", {}).get("default_mode", "conservative"),
        "discord_token": creds.get("discord_token", ""),
        "phoenix_api_url": creds.get("phoenix_api_url", ""),
        "phoenix_api_key": creds.get("phoenix_api_key", ""),
        "agent_id": "",
        "risk_params": {
            "max_position_size_pct": risk.get("max_position_size_pct", 5.0),
            "max_daily_loss_pct": risk.get("max_daily_loss_pct", 3.0),
            "max_concurrent_positions": risk.get("max_concurrent_positions", 3),
            "confidence_threshold": 0.65,
            "require_pattern_match": risk.get("require_pattern_match", True),
            "min_pattern_matches": risk.get("min_pattern_matches", 2),
        },
        "modes": manifest.get("modes", {}),
        "model_info": {
            "model_type": models.get("primary", "unknown"),
            "accuracy": models.get("accuracy", 0),
            "version": models.get("version", ""),
        },
    }
    with open(output / "config.json", "w") as f:
        json.dump(config, f, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    create_live_agent(args.config, args.models, args.output)


if __name__ == "__main__":
    main()
