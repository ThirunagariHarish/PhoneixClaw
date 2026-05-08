"""Create a live trading agent from backtesting output.

Builds a manifest from backtest artifacts (patterns, models, explainability,
analyst profile), renders the agent from the live-trader-v1 template, copies
model artifacts, writes .claude/settings.json for sandboxing, and handles
cross-VPS shipping when the trading VPS differs from the backtesting VPS.

Usage:
    python tools/create_live_agent.py \
        --config config.json \
        --models output/models/ \
        --output ~/agents/live/spx-alerts/
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "live-trader-v1"
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
LEGACY_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "live-template"

CLAUDE_SETTINGS = {
    "permissions": {
        "allow": [
            "Bash(python *)", "Bash(python3 *)", "Bash(pip *)", "Bash(pip3 *)", "Bash(curl *)",
            "Read", "Write", "Edit", "Grep", "Glob",
        ],
        "deny": [
            "Bash(rm -rf /)", "Bash(rm -rf ~)", "Bash(git push --force *)",
            "Bash(shutdown *)", "Bash(reboot *)",
        ],
    },
    "hooks": {
        "SessionStart": [{
            "hooks": [{"type": "command", "command": "python3 tools/report_to_phoenix.py --event session_start 2>/dev/null || true"}],
        }],
        "Stop": [{
            "hooks": [{"type": "command", "command": "python3 tools/report_to_phoenix.py --event session_stop 2>/dev/null || true"}],
        }],
    },
}


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
    # discover_patterns.py writes patterns.json to the work-dir root (cwd), not
    # inside models/.  Check the canonical location first, then fall back to the
    # legacy models/ sub-path so both invocation styles work.
    candidates = [
        Path("patterns.json"),          # work-dir root (orchestrator default)
        models_dir / "patterns.json",   # legacy / manual invocation
        models_dir.parent / "patterns.json",
    ]
    for patterns_path in candidates:
        if patterns_path.exists():
            with open(patterns_path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return data.get("patterns", data.get("rules", []))
    return []


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


def _build_final_metrics(
    config_path: str,
    models_dir: Path,
    patterns: list[dict],
    explainability: dict,
    analyst_profile: dict,
    manifest: dict,
    channel_name: str,
    character: str,
    rules_count: int,
) -> dict:
    """Aggregate all backtesting outputs into a comprehensive metrics dict.

    The backtest-progress endpoint merges this into bt.metrics, and then
    uses specific keys (win_rate, sharpe_ratio, etc.) to populate typed
    columns on the backtest and agent records.
    """
    config_dir = Path(config_path).parent
    output_dir = config_dir / "output"

    def _find(*candidates: Path) -> Path | None:
        for c in candidates:
            if c.exists():
                return c
        return None

    # --- Feature names from preprocessor meta.json ---
    feature_names = []
    preprocessing_summary = {}
    meta_path = _find(
        config_dir / "preprocessed" / "meta.json",
        config_dir / "meta.json",
        output_dir / "meta.json",
        output_dir / "preprocessed" / "meta.json",
    )
    if meta_path:
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            feature_names = meta.get("feature_columns", [])
            preprocessing_summary = {
                "total_rows": meta.get("total_rows", 0),
                "train_rows": meta.get("train_rows", 0),
                "val_rows": meta.get("val_rows", 0),
                "test_rows": meta.get("test_rows", 0),
                "feature_count": len(feature_names),
            }
        except Exception:
            pass

    # --- All model results from best_model.json ---
    all_model_results = []
    best_model_info = _load_json(models_dir / "best_model.json")
    all_model_results = best_model_info.get("all_results", [])

    # --- Backtest-level summary from enriched data ---
    total_trades = 0
    win_rate = analyst_profile.get("win_rate", 0)
    total_return = 0.0
    enriched_df = None
    try:
        import pandas as pd
        enriched_path = _find(
            config_dir / "enriched.parquet",
            output_dir / "enriched.parquet",
        )
        if enriched_path:
            enriched_df = pd.read_parquet(enriched_path)
            total_trades = len(enriched_df)
            if "is_profitable" in enriched_df.columns:
                win_rate = float(enriched_df["is_profitable"].mean())
            if "pnl_pct" in enriched_df.columns:
                # pnl_pct is already a fraction (0.05 = 5%), NOT percentage points
                returns = enriched_df["pnl_pct"].fillna(0)
                total_return = round(float(((1 + returns).prod() - 1) * 100.0), 4)
    except Exception:
        pass

    # --- Best model's sharpe and max_drawdown ---
    sharpe_ratio = 0.0
    max_drawdown = 0.0
    best_name = best_model_info.get("best_model", "")
    for r in all_model_results:
        if r.get("model_name") == best_name:
            sharpe_ratio = r.get("sharpe_ratio", 0.0)
            max_drawdown = r.get("max_drawdown_pct", 0.0)
            break

    # Fallback: compute from equity curve of all trades if model-level values are zero
    if (sharpe_ratio == 0.0 or max_drawdown == 0.0) and enriched_df is not None:
        try:
            import numpy as _np
            returns = enriched_df["pnl_pct"].fillna(0).values
            if len(returns) > 1 and returns.std() > 0:
                if sharpe_ratio == 0.0:
                    # Annualized assuming ~252 trading days
                    sharpe_ratio = float(returns.mean() / returns.std() * (252 ** 0.5))
                equity = (1 + returns).cumprod()
                peak = _np.maximum.accumulate(equity)
                drawdown = (equity - peak) / peak
                if max_drawdown == 0.0:
                    max_drawdown = float(drawdown.min() * 100.0)
        except Exception:
            pass

    return {
        "channel": channel_name,
        "model": manifest["models"]["primary"],
        "best_model": manifest["models"]["primary"],
        "accuracy": manifest["models"].get("accuracy", 0),
        "rules": rules_count,
        "character": character,
        "total_trades": total_trades,
        "win_rate": round(win_rate, 4),
        "sharpe_ratio": round(sharpe_ratio, 4),
        "max_drawdown": round(max_drawdown, 4),
        "total_return": round(total_return, 4),
        "patterns": patterns,
        "pattern_count": len(patterns),
        "feature_names": feature_names,
        "feature_count": len(feature_names),
        "all_model_results": all_model_results,
        "model_count": len(all_model_results),
        "preprocessing_summary": preprocessing_summary,
        "explainability": explainability,
        "analyst_profile": analyst_profile,
        "auto_create_analyst": True,
    }


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
            "discord_redis_consumer", "inference", "enrich_single", "risk_check",
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

    # Copy report_to_phoenix.py from backtesting tools if not in template
    backtesting_report = Path(__file__).parent / "report_to_phoenix.py"
    if backtesting_report.exists() and not (out_tools / "report_to_phoenix.py").exists():
        out_tools.mkdir(exist_ok=True)
        shutil.copy2(backtesting_report, out_tools / "report_to_phoenix.py")

    skills_src = TEMPLATE_DIR / "skills"
    if skills_src.exists():
        shutil.copytree(skills_src, output / "skills", dirs_exist_ok=True)

    out_models = output / "models"
    out_models.mkdir(exist_ok=True)
    for artifact in models.glob("*"):
        if artifact.is_file():
            dest = out_models / artifact.name
            # Skip if src and dest resolve to the same path (e.g. when
            # output == backtest sandbox and models == sandbox/models).
            if artifact.resolve() == dest.resolve():
                continue
            shutil.copy2(artifact, dest)

    _render_claude_md(manifest, output)
    _write_config(manifest, config, output)
    _write_claude_settings(output)
    _copy_commands(output)
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

    _handle_cross_vps_shipping(config, channel_name, output)

    try:
        from report_to_phoenix import report_progress

        final_metrics = _build_final_metrics(
            config_path=config_path,
            models_dir=models,
            patterns=patterns,
            explainability=explainability,
            analyst_profile=analyst_profile,
            manifest=manifest,
            channel_name=channel_name,
            character=character,
            rules_count=len(rules),
        )

        report_progress(
            "create_live_agent",
            f"Live agent created for #{channel_name}",
            100,
            final_metrics,
            status="COMPLETED",
        )
    except Exception as e:
        print(f"  Warning: could not report completion to Phoenix: {e}")

    return str(output)


def _handle_cross_vps_shipping(config: dict, channel_name: str, output: Path):
    """If trading_instance_id differs from current VPS, SCP the bundle."""
    trading_instance_id = config.get("trading_instance_id", "")
    trading_ssh_host = config.get("trading_ssh_host", "")
    trading_ssh_user = config.get("trading_ssh_user", "root")
    trading_ssh_port = config.get("trading_ssh_port", 22)
    trading_ssh_key_path = config.get("trading_ssh_key_path", "")

    if not trading_ssh_host:
        return

    print(f"  Cross-VPS shipping to {trading_ssh_host}...")

    tar_path = Path(tempfile.mktemp(suffix=".tar.gz"))
    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(str(output), arcname=channel_name)

        remote_path = f"~/agents/live/"
        ssh_opts = f"-o StrictHostKeyChecking=no -o ConnectTimeout=30 -p {trading_ssh_port}"
        if trading_ssh_key_path:
            ssh_opts += f" -i {trading_ssh_key_path}"

        subprocess.run(
            f"ssh {ssh_opts} {trading_ssh_user}@{trading_ssh_host} 'mkdir -p {remote_path}'",
            shell=True, check=True, timeout=60,
        )
        subprocess.run(
            f"scp {ssh_opts} {tar_path} {trading_ssh_user}@{trading_ssh_host}:{remote_path}",
            shell=True, check=True, timeout=300,
        )
        subprocess.run(
            f"ssh {ssh_opts} {trading_ssh_user}@{trading_ssh_host} "
            f"'cd {remote_path} && tar xzf {channel_name}.tar.gz && rm {channel_name}.tar.gz'",
            shell=True, check=True, timeout=120,
        )
        print(f"  Shipped to {trading_ssh_host}:{remote_path}{channel_name}/")
    except Exception as e:
        print(f"  Warning: cross-VPS shipping failed: {e}")
    finally:
        tar_path.unlink(missing_ok=True)


def _write_claude_settings(output: Path):
    """Write .claude/settings.json for agent sandboxing and hooks."""
    claude_dir = output / ".claude"
    claude_dir.mkdir(exist_ok=True)
    with open(claude_dir / "settings.json", "w") as f:
        json.dump(CLAUDE_SETTINGS, f, indent=2)


def _copy_commands(output: Path):
    """Copy slash commands from the live-trader template into the agent bundle."""
    commands_src = TEMPLATE_DIR / ".claude" / "commands"
    if commands_src.exists() and commands_src.is_dir():
        commands_dst = output / ".claude" / "commands"
        shutil.copytree(commands_src, commands_dst, dirs_exist_ok=True)
        print(f"Copied {len(list(commands_dst.glob('*.md')))} slash commands to {commands_dst}")


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
        except Exception:
            # ImportError (jinja2 not installed) or any template render error —
            # fall through to the legacy string-substitution template below.
            pass

    legacy = LEGACY_TEMPLATE_DIR / "CLAUDE.md"
    if legacy.exists():
        text = legacy.read_text()
        identity = manifest.get("identity", {})
        text = text.replace("{{channel_name}}", identity.get("channel", ""))
        text = text.replace("{{analyst_name}}", identity.get("analyst", ""))
        (output / "CLAUDE.md").write_text(text)


def _write_config(manifest: dict, original_config: dict, output: Path):
    identity = manifest.get("identity", {})
    risk = manifest.get("risk", {})
    models = manifest.get("models", {})
    creds = manifest.get("credentials", {})

    config = {
        "agent_id": original_config.get("agent_id", ""),
        "agent_name": identity.get("name", ""),
        "channel_name": identity.get("channel", ""),
        "channel_id": identity.get("channel_id", ""),
        "server_id": identity.get("server_id", ""),
        "analyst_name": identity.get("analyst", ""),
        "current_mode": manifest.get("modes", {}).get("default_mode", "conservative"),
        "discord_token": creds.get("discord_token", ""),
        "phoenix_api_url": creds.get("phoenix_api_url", ""),
        "phoenix_api_key": creds.get("phoenix_api_key", ""),
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
