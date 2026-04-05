"""Validate an agent manifest against the JSON schema and perform structural checks."""

import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    jsonschema = None

SCHEMA_PATH = Path(__file__).parent / "manifest.schema.json"
CHARACTERS_PATH = Path(__file__).parent / "characters.json"


def load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def load_characters() -> dict:
    with open(CHARACTERS_PATH) as f:
        return json.load(f)


def detect_character(analyst_profile: dict) -> str:
    """Auto-detect agent character from backtesting analyst profile metrics."""
    avg_hold = analyst_profile.get("avg_hold_hours", 4)
    win_rate = analyst_profile.get("win_rate", 0.5)
    is_swing = analyst_profile.get("is_swing_trader", False)

    if is_swing or avg_hold >= 24:
        return "conservative-swing"
    if avg_hold <= 2 and win_rate >= 0.65:
        return "aggressive-momentum"
    return "balanced-intraday"


def apply_character_defaults(manifest: dict) -> dict:
    """Merge character-specific mode overrides into the manifest when modes are absent."""
    characters = load_characters()
    char_name = manifest.get("identity", {}).get("character", "balanced-intraday")
    char_def = characters.get(char_name, characters["balanced-intraday"])

    if "modes" not in manifest or not manifest["modes"]:
        manifest["modes"] = char_def.get("mode_overrides", {})

    if "knowledge" in manifest and "analyst_profile" in manifest["knowledge"]:
        profile = manifest["knowledge"]["analyst_profile"]
        if not manifest["identity"].get("character"):
            manifest["identity"]["character"] = detect_character(profile)

    return manifest


def validate_manifest(manifest: dict, template_dir: Path | None = None) -> list[str]:
    """
    Validate a manifest dict.  Returns a list of error strings (empty = valid).
    Performs JSON Schema validation (if jsonschema is installed) plus structural checks.
    """
    errors: list[str] = []

    if jsonschema is not None:
        schema = load_schema()
        validator = jsonschema.Draft7Validator(schema)
        for err in validator.iter_errors(manifest):
            errors.append(f"Schema: {err.message} at {'/'.join(str(p) for p in err.absolute_path)}")
    else:
        for required in ("version", "template", "identity", "risk", "tools"):
            if required not in manifest:
                errors.append(f"Missing required field: {required}")

    identity = manifest.get("identity", {})
    if not identity.get("name"):
        errors.append("identity.name is required")
    if not identity.get("channel"):
        errors.append("identity.channel is required")
    if not identity.get("analyst"):
        errors.append("identity.analyst is required")

    risk = manifest.get("risk", {})
    if risk.get("max_position_size_pct", 0) <= 0:
        errors.append("risk.max_position_size_pct must be positive")
    if risk.get("max_daily_loss_pct", 0) <= 0:
        errors.append("risk.max_daily_loss_pct must be positive")

    if template_dir:
        tools_dir = template_dir / "tools"
        for tool_name in manifest.get("tools", []):
            tool_file = tools_dir / f"{tool_name}.py"
            if not tool_file.exists():
                errors.append(f"Tool script not found: {tool_file}")

        skills_dir = template_dir / "skills"
        for skill_name in manifest.get("skills", []):
            skill_file = skills_dir / skill_name
            if not skill_file.exists():
                errors.append(f"Skill file not found: {skill_file}")

    for rule in manifest.get("rules", []):
        if not rule.get("name"):
            errors.append("Rule missing 'name'")
        if not rule.get("condition"):
            errors.append(f"Rule '{rule.get('name', '?')}' missing 'condition'")
        if "weight" not in rule:
            errors.append(f"Rule '{rule.get('name', '?')}' missing 'weight'")

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_manifest.py <manifest.json> [template_dir]")
        sys.exit(1)

    manifest_path = Path(sys.argv[1])
    template_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    with open(manifest_path) as f:
        manifest = json.load(f)

    errors = validate_manifest(manifest, template_dir)
    if errors:
        print(f"INVALID — {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("VALID")


if __name__ == "__main__":
    main()
