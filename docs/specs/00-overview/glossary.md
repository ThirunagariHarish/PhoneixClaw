# Glossary

## Core Concepts

| Term | Definition |
|------|-----------|
| **Agent** | An autonomous Claude Code project on a VPS that monitors a Discord channel and trades based on trained models |
| **Backtesting Agent** | A special agent that orchestrates the full ETL → enrichment → training pipeline; creates live agents as output |
| **Live Agent** | An agent created by the backtesting agent that actively monitors Discord and trades |
| **VPS** | Virtual Private Server running Claude Code CLI — the compute node for agents |
| **Agent Gateway** | Module in Phoenix API that communicates with VPS instances via SSH |
| **Instance** | A registered VPS in the Network tab (replaces "OpenClaw Instance") |

## Pipeline Terms

| Term | Definition |
|------|-----------|
| **Transformation** | Step 1 of backtesting — raw Discord messages → clean feature rows with ticker, price, targets, partial exits, profit/loss labels |
| **Enrichment** | Step 2 of backtesting — adds ~200 market attributes (technical indicators, sentiment, events, macro) to each trade row |
| **Training** | Step 3 of backtesting — trains 5-6 ML models in parallel, selects best, builds explainability model and discovers patterns |
| **Sub-Agent** | A Claude Code task spawned by the backtesting agent for a specific training job (e.g., "train XGBoost classifier") |
| **Partial Exit** | When an analyst sells a position in multiple chunks (50% at $X, 30% at $Y, 20% at $Z) |
| **Profit Label** | Binary label — trade is "profitable" if >50% of position closed with positive return |

## Model Outputs

| Term | Definition |
|------|-----------|
| **Trade Classifier** | ML model that predicts yes/no on whether to take a trade — the primary inference model |
| **Explainability Model** | Multi-class model that explains WHY a trade was taken based on which features contributed most |
| **Pattern Set** | Top 50-60 recurring patterns discovered from training data (e.g., "RSI oversold + VIX spike + morning session") |

## Infrastructure

| Term | Definition |
|------|-----------|
| **MCP Server** | Model Context Protocol server — a tool interface Claude Code can call (e.g., Robinhood MCP for trade execution) |
| **CLAUDE.md** | Instructions file that Claude Code reads to understand what an agent should do |
| **Token Budget** | Monthly Claude API token allocation; monitored via dashboard widget |
| **Model Routing** | Using cheaper models (Haiku) for routine tasks and expensive models (Sonnet) for complex analysis |
