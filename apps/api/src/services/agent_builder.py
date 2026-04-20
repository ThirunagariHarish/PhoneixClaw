"""Agent Builder — manifest-driven agent creation and rendering.

V3: Removed SSH/SCP shipping. The builder now only handles:
  template defaults + backtest output + user config → manifest → render locally
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    Environment = None  # type: ignore[misc,assignment]
    FileSystemLoader = None  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATES_DIR = REPO_ROOT / "agents" / "templates"
SCHEMA_DIR = REPO_ROOT / "agents" / "schema"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


class AgentBuilder:
    """Builds, validates, and renders agents from templates + manifests."""

    def __init__(self, templates_dir: Path | None = None):
        self.templates_dir = templates_dir or TEMPLATES_DIR
        self.characters = _load_json(SCHEMA_DIR / "characters.json")

    # ------------------------------------------------------------------
    # 1. Build manifest
    # ------------------------------------------------------------------

    def build_manifest(
        self,
        template_name: str,
        backtest_output: dict | None = None,
        user_config: dict | None = None,
    ) -> dict:
        """
        Merge three sources in priority order:
          user_config > backtest_output > template defaults
        Returns a complete manifest dict.
        """
        template_dir = self.templates_dir / template_name
        defaults_path = template_dir / "manifest.defaults.json"
        if not defaults_path.exists():
            raise FileNotFoundError(f"Template '{template_name}' not found at {template_dir}")

        manifest = _load_json(defaults_path)

        if backtest_output:
            manifest = self._merge_backtest_output(manifest, backtest_output)

        if user_config:
            manifest = _deep_merge(manifest, user_config)

        manifest = self._apply_character(manifest)

        return manifest

    def _merge_backtest_output(self, manifest: dict, bt: dict) -> dict:
        """Incorporate patterns, model info, explainability, and analyst profile."""
        if "patterns" in bt:
            rules = []
            for p in bt["patterns"]:
                rules.append({
                    "name": p.get("name", ""),
                    "condition": p.get("condition", ""),
                    "weight": p.get("weight", 0),
                    "source": "backtesting",
                    "enabled": True,
                    "description": p.get("description", ""),
                })
            manifest["rules"] = rules

        if "best_model" in bt:
            bm = bt["best_model"]
            manifest["models"] = {
                "primary": bm.get("best_model", bm.get("model_type", "unknown")),
                "accuracy": bm.get("best_score", bm.get("accuracy", 0)),
                "auc_roc": bm.get("auc_roc", 0),
                "version": bm.get("training_date", ""),
                "training_trades": bm.get("training_trades", 0),
                "all_models": bm.get("all_models", []),
            }

        if "explainability" in bt:
            top_features = bt["explainability"].get("top_features", [])
            manifest.setdefault("knowledge", {})["top_features"] = top_features[:20]

        if "analyst_profile" in bt:
            manifest.setdefault("knowledge", {})["analyst_profile"] = bt["analyst_profile"]

        if "channel_summary" in bt:
            manifest.setdefault("knowledge", {})["channel_summary"] = bt["channel_summary"]

        return manifest

    def _apply_character(self, manifest: dict) -> dict:
        """Auto-detect character from analyst profile and apply mode overrides."""
        from agents.schema.validate_manifest import detect_character

        profile = manifest.get("knowledge", {}).get("analyst_profile", {})
        identity = manifest.get("identity", {})

        if not identity.get("character") or identity["character"] == "balanced-intraday":
            detected = detect_character(profile)
            manifest.setdefault("identity", {})["character"] = detected

        char_name = manifest.get("identity", {}).get("character", "balanced-intraday")
        char_def = self.characters.get(char_name, self.characters["balanced-intraday"])

        if not manifest.get("modes") or manifest["modes"] == {}:
            manifest["modes"] = char_def.get("mode_overrides", {})

        return manifest

    # ------------------------------------------------------------------
    # 2. Validate manifest
    # ------------------------------------------------------------------

    def validate_manifest(self, manifest: dict, template_name: str | None = None) -> list[str]:
        """Validate a manifest. Returns list of error strings (empty = valid)."""
        from agents.schema.validate_manifest import validate_manifest as _validate

        template_dir = None
        if template_name:
            template_dir = self.templates_dir / template_name
        return _validate(manifest, template_dir)

    # ------------------------------------------------------------------
    # 3. Render agent bundle locally
    # ------------------------------------------------------------------

    def render_agent(self, manifest: dict) -> Path:
        """
        Render a manifest into a deployable agent directory.
        Returns the path to the temporary directory.
        """
        template_name = manifest.get("template", "live-trader-v1")
        template_dir = self.templates_dir / template_name
        if not template_dir.exists():
            raise FileNotFoundError(f"Template not found: {template_dir}")

        output = Path(tempfile.mkdtemp(prefix="phoenix_agent_"))

        tools_src = template_dir / "tools"
        if tools_src.exists():
            shutil.copytree(tools_src, output / "tools", dirs_exist_ok=True)

        skills_src = template_dir / "skills"
        if skills_src.exists():
            shutil.copytree(skills_src, output / "skills", dirs_exist_ok=True)

        claude_src = template_dir / ".claude"
        if claude_src.exists():
            shutil.copytree(claude_src, output / ".claude", dirs_exist_ok=True)

        self._render_claude_md(manifest, template_dir, output)
        self._write_config(manifest, output)

        with open(output / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2, default=str)

        (output / "trades.log").write_text("")
        (output / "models").mkdir(exist_ok=True)

        return output

    def _render_claude_md(self, manifest: dict, template_dir: Path, output: Path):
        """Render CLAUDE.md from the Jinja2 template, falling back to static copy."""
        jinja_file = template_dir / "CLAUDE.md.jinja2"
        fallback = template_dir / "CLAUDE.md"

        if not jinja_file.exists() or Environment is None:
            if jinja_file.exists() and Environment is None:
                logger.warning("jinja2 not installed — copying static CLAUDE.md instead of rendering template")
            if fallback.exists():
                shutil.copy2(fallback, output / "CLAUDE.md")
            return

        env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template("CLAUDE.md.jinja2")

        char_name = manifest.get("identity", {}).get("character", "balanced-intraday")
        char_def = self.characters.get(char_name, {})
        character_description = char_def.get("description", "Balanced trading agent.")

        rendered = template.render(
            **manifest,
            character_description=character_description,
            current_mode=manifest.get("identity", {}).get("character", "balanced-intraday").split("-")[0],
        )
        (output / "CLAUDE.md").write_text(rendered)

    def _write_config(self, manifest: dict, output: Path):
        """Write config.json from manifest fields."""
        identity = manifest.get("identity", {})
        risk = manifest.get("risk", {})
        models = manifest.get("models", {})
        credentials = manifest.get("credentials", {})

        config = {
            "agent_name": identity.get("name", ""),
            "channel_name": identity.get("channel", ""),
            "channel_id": identity.get("channel_id", ""),
            "server_id": identity.get("server_id", ""),
            "analyst_name": identity.get("analyst", ""),
            "current_mode": "conservative",
            "discord_token": credentials.get("discord_token", ""),
            "phoenix_api_url": credentials.get("phoenix_api_url", ""),
            "phoenix_api_key": credentials.get("phoenix_api_key", ""),
            "robinhood_username": credentials.get("robinhood_username", ""),
            "robinhood_password": credentials.get("robinhood_password", ""),
            "robinhood_totp_secret": credentials.get("robinhood_totp_secret", ""),
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


agent_builder = AgentBuilder()
