# Agent Development Guide

How to create, test, and deploy new agent types in Phoenix.

## Agent Architecture

Every Phoenix agent is a **Claude Code session** — a real Claude process running in a sandboxed working directory. Agents are not Python daemons or microservices.

Each agent has:
- A **`CLAUDE.md`** instructions file (or `.jinja2` template rendered at runtime)
- A **`tools/`** directory of Python scripts the agent can call
- A **`config.json`** with credentials and parameters
- A **`.claude/settings.json`** locking down permissions

The agent reads its `CLAUDE.md`, decides what to do, and executes Python tools via Bash.

## Creating a New Agent Template

### 1. Create the template directory

```
agents/templates/my-new-agent/
  CLAUDE.md           # Static instructions (or .jinja2 for dynamic)
  tools/
    my_tool.py        # Python tool the agent can call
    report_to_phoenix.py  # Copy from existing template
  config.json         # Default config (optional)
```

### 2. Write the CLAUDE.md

The CLAUDE.md is the most important file. It tells the agent:
- What it is and what it should do
- What tools are available and how to use them
- What loop to follow (startup → processing → shutdown)
- Risk limits and constraints

Best practices:
- Be specific about tool CLI arguments
- Show exact `python tools/...` commands the agent should run
- Include error handling instructions (the agent can fix broken tools)
- Add token optimization guidance

### 3. Write focused Python tools

Each tool should:
- Do **one thing** well
- Accept CLI arguments (`argparse`)
- Read from and write to JSON files
- Be importable as a Python module (`from my_tool import my_function`)
- Print a JSON summary to stdout for the agent to read
- Log to stderr

Example skeleton:

```python
"""My tool — does one specific thing.

Usage:
    python my_tool.py --input data.json --output result.json
"""
import argparse
import json
from pathlib import Path


def do_work(input_data: dict) -> dict:
    # ... actual logic ...
    return {"status": "ok", "result": ...}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="result.json")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text())
    result = do_work(data)
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps({"status": result["status"]}))


if __name__ == "__main__":
    main()
```

### 4. Register in the gateway

Add a creation method to `apps/api/src/services/agent_gateway.py`:

```python
async def create_my_agent(self, agent_id, config):
    work_dir = self._prepare_workspace(
        agent_id=agent_id,
        template="my-new-agent",
        config=config,
    )
    return await self._spawn_agent(agent_id, work_dir, "my_agent")
```

### 5. Add an API route

In `apps/api/src/routes/agents.py`, add an endpoint that calls `gateway.create_my_agent()`.

## Testing Agents

### Unit tests for tools

Test each Python tool independently:

```python
# tests/unit/test_my_tool.py
import sys
from pathlib import Path

TOOLS_DIR = Path("agents/templates/my-new-agent/tools")
sys.path.insert(0, str(TOOLS_DIR))

from my_tool import do_work

def test_basic():
    result = do_work({"input": "test"})
    assert result["status"] == "ok"
```

### Integration tests

Test the full pipeline with mocked external services:

```python
# tests/integration/test_my_agent.py
from unittest.mock import patch, MagicMock

def test_full_pipeline(tmp_path):
    # Set up config, mock Redis/API, run pipeline
    ...
```

### Manual testing

Start the agent locally and interact with it:

```bash
# Prepare workspace
mkdir -p /tmp/test_agent && cp -r agents/templates/my-new-agent/* /tmp/test_agent/
# Write config
echo '{"agent_id": "test"}' > /tmp/test_agent/config.json
# Run as Claude Code session
claude --cwd /tmp/test_agent
```

## Existing Agent Types

| Template | Purpose | Lifecycle |
|----------|---------|-----------|
| `live-trader-v1` | Discord signal trading | Continuous |
| `position-monitor-agent` | Per-position exit monitoring | Until position closes |
| `morning-briefing-agent` | Pre-market research | One-shot daily |
| `supervisor-agent` | Nightly AutoResearch | One-shot daily |
| `daily-summary-agent` | EOD summary | One-shot daily |
| `eod-analysis-agent` | Post-market analysis | One-shot daily |
| `trade-feedback-agent` | Trading bias analysis | One-shot daily |
| `unusual-whales-agent` | Options flow monitoring | Continuous |
| `social-sentiment-agent` | Reddit/Twitter signals | Continuous |
| `strategy-agent` | Rule-based strategies | Continuous |

## Key Tools (shared across templates)

- `report_to_phoenix.py` — Every template should include this for reporting to the dashboard
- `notify.py` — Send WhatsApp/Telegram notifications (in `live-trader-v1/tools/`)
- `robinhood_mcp.py` — Robinhood broker MCP server (in `live-trader-v1/tools/`)
