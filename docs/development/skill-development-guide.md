# Phoenix v2 Skill Development Guide

This guide explains how to create, test, and publish skills for OpenClaw agents in Phoenix v2.

---

## Skill File Format (SKILL.md Template)

Each skill lives in a directory with a `SKILL.md` file. Use this template:

```markdown
# Skill Name

Brief description of what the skill does.

## When to Use

Use this skill when the agent needs to [specific scenario].

## Inputs

- `input_name` (type): Description

## Outputs

- `output_name` (type): Description

## Example

\`\`\`
Example usage or prompt snippet
\`\`\`

## Dependencies

- Other skills or tools required
```

---

## Skill Categories and Naming Conventions

Skills are organized by category under `openclaw/skills/`:

| Category | Purpose | Example |
|----------|---------|---------|
| `analysis` | Technical/fundamental analysis | Technical Analysis, Sentiment |
| `data` | Data fetching and processing | Data Fetcher, OHLCV |
| `execution` | Order execution | Order Execution, Limit/Market |
| `risk` | Risk management | Risk Manager, Position Sizing |
| `strategy` | Strategy logic | Mean Reversion, Momentum |
| `utility` | General utilities | Logging, Notifications |

**Naming**: Use kebab-case for directories (e.g. `technical-analysis`), PascalCase for display names.

---

## Testing Skills with Agents

1. **Local development** — Add the skill directory to `openclaw/skills/<category>/<skill-name>/SKILL.md`.
2. **Assign to agent** — In the dashboard, go to **Skills** → **Agent Configuration** and attach the skill to an agent.
3. **Run agent** — Start the agent on an OpenClaw instance and verify the skill is invoked correctly in logs.
4. **Unit tests** — Add tests in `tests/` that mock agent context and assert skill behavior.

---

## Publishing Skills to the Catalog

1. **Upload to MinIO** — Skills are synced from the `phoenix-skills` MinIO bucket:
   ```bash
   mc cp -r openclaw/skills/analysis/technical-analysis phoenix/phoenix-skills/analysis/
   ```

2. **Skill Sync Service** — The `phoenix-skill-sync` service mirrors `phoenix-skills` to bridge nodes. Ensure it runs and has `MINIO_ENDPOINT`, `BRIDGE_URL`, `BRIDGE_TOKEN` configured.

3. **Manual sync** (for local nodes):
   ```bash
   ./infra/scripts/sync-skills.sh
   ```

---

## Skill Versioning and Rollback

- **Versioning** — Use directory names with version suffix if needed (e.g. `technical-analysis-v2`). Prefer updating in place and documenting changes in `SKILL.md`.
- **Rollback** — Replace the skill directory in MinIO with the previous version and re-run sync. Agents will pick up the updated skill on next load.
