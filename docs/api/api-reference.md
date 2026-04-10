# Phoenix v2 API Reference

The Phoenix v2 API is a FastAPI application. This document provides an overview; full interactive docs are available at `/docs` (Swagger UI) and `/redoc` (ReDoc).

---

## Overview

- **Base URL**: `http://localhost:8011` (or your deployment URL)
- **OpenAPI docs**: `GET /docs` (Swagger UI)
- **ReDoc**: `GET /redoc`
- **Health**: `GET /health` — returns `{"status":"ready","service":"phoenix-api"}`

---

## Authentication

- **Method**: JWT Bearer token
- **Header**: `Authorization: Bearer <access_token>`
- **Login**: `POST /api/v2/auth/login` with `email` and `password`; returns `access_token` and `refresh_token`
- **Refresh**: `POST /api/v2/auth/refresh` with `refresh_token` to obtain a new access token

---

## Rate Limiting

Rate limiting may be applied per IP or per user. Check response headers for `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After` when limits are exceeded.

---

## Error Codes and Formats

- **401 Unauthorized** — Missing or invalid token
- **403 Forbidden** — Valid token but insufficient permissions
- **404 Not Found** — Resource does not exist
- **422 Unprocessable Entity** — Validation error (e.g. invalid request body)
- **500 Internal Server Error** — Server error

Error responses typically follow:

```json
{"detail": "Error message"}
```

Validation errors include field-level details.

---

## Endpoint Groups

| Group | Prefix | Description |
|-------|--------|-------------|
| Auth | `/api/v2/auth` | Login, refresh, logout |
| Agents | `/api/v2/agents` | Agent CRUD, stats, start/stop |
| Trades | `/api/v2/trades` | Trade history, filters |
| Positions | `/api/v2/positions` | Open positions, P&amp;L |
| Connectors | `/api/v2/connectors` | Broker and data connectors |
| Skills | `/api/v2/skills` | Skill catalog, sync |
| Backtests | `/api/v2/backtests` | Backtest runs, results |
| Execution | `/api/v2/execution` | Order execution, approval |
| Admin | `/api/v2/admin` | Users, API keys, system |
| Network | `/api/v2/network` | Nodes, instances |
| Performance | `/api/v2/performance` | Portfolio metrics |
| Tasks | `/api/v2/tasks` | Task board, automations |
| Automations | `/api/v2/automations` | Automation rules |
| Dev | `/api/v2/dev` | Dev agent, incidents |

For exact paths, request/response schemas, and examples, use the interactive docs at `/docs`.
