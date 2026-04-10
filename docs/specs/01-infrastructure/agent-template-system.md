# Spec: Agent Template System

## Purpose

Define a manifest-driven framework for creating, validating, rendering, and shipping agents to Claude Code instances on VPS. Every agent — whether backtesting or live — is built from a **versioned template** and described by a **manifest** that captures its identity, rules, character, modes, risk profile, models, tools, and skills.

## Key Concepts

| Term | Definition |
|------|-----------|
| **Manifest** | JSON document describing everything an agent IS — identity, rules, modes, risk, models, tools, skills, knowledge, credentials |
| **Template** | A versioned directory containing a Jinja2 `CLAUDE.md` template, tool scripts, skill markdown, config schema, and manifest defaults |
| **Character** | A personality profile (aggressive-momentum, conservative-swing, balanced-intraday) auto-detected from backtesting metrics |
| **Agent Builder** | Server-side service that merges template defaults + backtesting output + user config into a validated manifest, then renders and ships the agent |

## Manifest Schema

Location: `agents/schema/manifest.schema.json`

Top-level fields:

```
version          — schema version (e.g. "1.0")
template         — template identifier (e.g. "live-trader-v1")
identity         — name, channel, analyst, character
rules[]          — learned and user-defined trading rules with weights
modes            — aggressive / conservative threshold sets
risk             — position sizing and loss limits
models           — primary model, accuracy, all_models list
tools[]          — required tool script names
skills[]         — skill markdown files
knowledge        — backtesting-derived analyst profile, top features, channel summary
credentials      — encrypted credential references
```

## Template Registry

```
agents/templates/
  live-trader-v1/
    CLAUDE.md.jinja2          — Jinja2 template for agent instructions
    config.schema.json        — validation schema for config.json
    manifest.defaults.json    — default manifest values
    tools/                    — all Python tool scripts
    skills/                   — skill markdown files
  backtesting-v1/
    CLAUDE.md.jinja2
    tools/
    manifest.defaults.json
```

### Jinja2 Template Features

The `CLAUDE.md.jinja2` template supports:

- **Conditional sections**: swing trade support is only included if `knowledge.analyst_profile.is_swing_trader` is true
- **Rule embedding**: all rules are rendered directly into agent instructions with weights
- **Mode definitions**: aggressive/conservative thresholds are embedded with actual values
- **Knowledge injection**: top features, analyst profile stats, channel summary become agent "memory"
- **Tool listing**: tools array is iterated to produce the tool documentation section

## Character System

Location: `agents/schema/characters.json`

Three predefined profiles:

| Character | Detection Heuristic | Default Mode | Hold Period |
|-----------|-------------------|--------------|-------------|
| `aggressive-momentum` | avg hold < 2h AND win rate > 65% | aggressive | minutes-to-hours |
| `conservative-swing` | avg hold > 24h OR is_swing_trader | conservative | days |
| `balanced-intraday` | fallback default | conservative | hours |

Each character defines `mode_overrides` that set the confidence thresholds, position limits, stop loss percentages, and P&L caps for both aggressive and conservative modes.

Auto-detection runs during manifest building: the backtesting agent's output includes `analyst_profile` with `avg_hold_hours`, `win_rate`, and `is_swing_trader`, which map to a character via the heuristic rules.

## Agent Builder Service

Location: `apps/api/src/services/agent_builder.py`

### Methods

```python
build_manifest(
    template_name: str,
    backtest_output: dict,   # patterns, models, explainability, analyst_profile
    user_config: dict         # from dashboard wizard
) -> dict
```

Merges three sources in priority order: user_config > backtest_output > template defaults.

```python
validate_manifest(manifest: dict, template_dir: Path) -> list[str]
```

Checks JSON Schema compliance and verifies that all referenced tool scripts and skill files exist in the template directory.

```python
render_agent(manifest: dict) -> Path
```

Renders the Jinja2 `CLAUDE.md`, writes `config.json` and `manifest.json`, assembles the agent bundle into a temporary directory.

```python
ship_agent(manifest: dict, instance_id: UUID) -> SSHResult
```

Packages the rendered agent as a tar.gz, SCPs to the VPS, unpacks at `~/agents/live/{channel}/`, and registers the agent in Postgres.

### Build Flow

```
Backtest Completes
  → load patterns.json, best_model.json, explainability.json
  → detect character from analyst_profile
  → merge with template manifest.defaults.json
  → merge with user config (risk, modes, credentials)
  → validate
  → render CLAUDE.md from Jinja2 template
  → copy model artifacts
  → write manifest.json + config.json
  → package + SCP to VPS
  → register Agent row in Postgres with manifest JSONB
```

## Shipping Pipeline

### From Dashboard

1. User clicks "New Agent" → selects channel, analyst, VPS instance
2. API creates Agent row with status `BACKTESTING`
3. Agent Builder ships backtesting template to VPS
4. Backtesting agent runs the 8-step pipeline
5. On completion: backtesting agent calls `create_live_agent.py` which generates `manifest.json`
6. Agent Builder reads manifest, validates, renders live agent, ships to VPS
7. Agent status updated to `RUNNING`

### From Backtesting Agent (On-VPS)

1. `create_live_agent.py` loads patterns.json + best_model.json + explainability.json
2. Detects character from analyst profile
3. Builds manifest.json with rules, modes, models, knowledge
4. Copies live-trader template tools and skills
5. Renders CLAUDE.md from Jinja2 template using manifest data
6. Writes all files to `~/agents/live/{channel}/`
7. Registers with Phoenix API via `report_to_phoenix.py`

## Manifest Storage

The full manifest is stored in the `agents.manifest` JSONB column. This enables:

- Dashboard can display and edit rules/modes/risk without SSH-ing to VPS
- Rule version tracking via `agents.rules_version` (incremented on each edit)
- Mode tracking via `agents.current_mode`

## Files

| File | Action |
|------|--------|
| `agents/schema/manifest.schema.json` | NEW — JSON Schema |
| `agents/schema/characters.json` | NEW — character profiles |
| `agents/schema/validate_manifest.py` | NEW — validation utility |
| `agents/templates/live-trader-v1/` | NEW — versioned template |
| `apps/api/src/services/agent_builder.py` | NEW — builder service |
| `agents/backtesting/tools/create_live_agent.py` | MODIFY — manifest generation |
| `shared/db/models/agent.py` | MODIFY — add manifest, current_mode, rules_version |
| `shared/db/models/agent_chat.py` | MODIFY — add message_type, metadata |
