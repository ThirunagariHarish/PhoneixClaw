# ADR 003: OpenClaw Bridge Pattern

## Status

SUPERSEDED (2026-04-18 — replaced by Claude Code SDK runtime; see docs/prd/phase-f-openclaw-removal.md)

## Context

OpenClaw instances run on remote VPS or laptop nodes. The control plane (API, dashboard) must manage agents, sync skills, and receive status without direct SSH or complex agent-side logic.

## Decision

Use a **Bridge Service** sidecar on each OpenClaw node. The bridge:

- Exposes a REST API on port 18800 for agent lifecycle (start, stop, status), skill sync, and config updates
- Authenticates via `BRIDGE_TOKEN` shared with the control plane
- Communicates with the control plane over WireGuard VPN for security

The control plane registers instances by host:port (WireGuard IP) and calls the bridge for all node operations.

## Consequences

- **Positive**: Clean REST API for management, no SSH required, WireGuard provides encrypted overlay network, bridge can be updated independently
- **Negative**: Requires one bridge process per node; bridge must be deployed and maintained on each VPS
- **Mitigation**: Bridge is lightweight; provisioning scripts (`provision-local-node.sh`) automate setup
