# OpenClaw Bridge Service

Sidecar for each OpenClaw instance: agent CRUD, heartbeat, skill sync. M1.7.

**Endpoints:**
- `GET /health` — no auth
- `GET /heartbeat` — returns agent list and count (X-Bridge-Token)
- `GET/POST/PUT/DELETE /agents` — agent workspace CRUD
- `POST /agents/{id}/pause`, `POST /agents/{id}/resume`
- `POST /agents/{id}/message` — send message to agent
- `POST /skills/sync` — pull skills from MinIO
- `GET /metrics` — Prometheus

**Run:**
```bash
cd openclaw/bridge && PYTHONPATH=. uvicorn src.main:app --host 0.0.0.0 --port 18800
```
Set `BRIDGE_TOKEN` and optionally `AGENTS_ROOT`, MinIO vars.

**Tests:**
```bash
cd openclaw/bridge && PYTHONPATH=. pytest tests/ -v
```

Reference: newdocs/ImplementationPlan.md Section 2, M1.7.
