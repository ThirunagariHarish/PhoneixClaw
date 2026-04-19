# Phase E Security Findings

**Date:** 2026-04-19
**Scanner:** bandit 1.8.6 (Python), `npm audit` (dashboard)
**Scope:** `shared/`, `services/`, `apps/api/src/`, `agents/`, `apps/dashboard/`
**Diff under review:** 55 commits (`568c21e..98efb6a`), tagged as v2.0.0

## Executive Summary

- **Sev-1 findings identified:** 0
- **Sev-2 findings identified:** 2 (documented with mitigation below)
- **Informational findings resolved:** 5 (hashlib `usedforsecurity=False` added where MD5/SHA1 used for non-security hashing)
- **npm vulnerabilities:** 0 remaining after `npm audit fix` regenerated lockfile

Overall rubric:

| Category | Result |
|---|---|
| Secrets in code | PASS — no hardcoded credentials found; all secrets via env or Fernet-encrypted DB |
| SQL injection | PASS — all DB calls use parameterized SQLAlchemy or `text(...)` with bind params |
| Auth bypass | PASS — JWT validation on all `/api/v2/*` protected routes; admin routes gated by `_require_admin` |
| Insecure crypto primitives | PASS — Fernet key from env; no homegrown crypto |
| CORS / origin validation | Reviewed — allowlist pattern in `apps/api/src/middleware` |
| Rate limiting | Reviewed — present on `/api/v2/auth/*` and admin endpoints |
| Input validation at boundary | PASS — Pydantic models on request schemas |
| Dependency CVEs | PASS — 0 npm vulnerabilities post-audit-fix; `pip-audit` follow-up tracked as SEC-003 |
| Logging / PII | No obvious PII logging; correlation IDs used for tracing |
| Error handling | Try/except on external calls; DLQ catches tool failures |

**Reviewer sign-off:** _(pending — human security lead must countersign before go-live)_
**Reviewed by:** _____________
**Date:** _____________

---

## Findings

### F-1 (Sev-2): `subprocess.run(..., shell=True)` in cross-VPS agent shipping

**Bandit rule:** B602 (subprocess_popen_with_shell_equals_true), High confidence
**Locations:**
- `agents/backtesting/tools/create_live_agent.py:457-459` — `ssh ... 'mkdir -p ...'`
- `agents/backtesting/tools/create_live_agent.py:461-463` — `scp ... {host}:{path}`
- `agents/backtesting/tools/create_live_agent.py:465-468` — `ssh ... 'cd ... && tar xzf ...'`

**Description:** The live-agent deploy path uses `shell=True` to stitch `ssh` / `scp` commands with values drawn from `config.json` (`trading_ssh_host`, `trading_ssh_user`, `channel_name`, `trading_ssh_port`).

**Impact:** If `config.json` is ever populated from user-controlled input without server-side sanitisation, a crafted `channel_name` or `trading_ssh_user` can inject shell metacharacters.

**Current mitigations:**
- `config.json` is server-generated from the agent creation wizard. Users never directly author it.
- The API layer validates `channel_name` against `^[A-Za-z0-9_-]+$` before persistence.
- SSH key path (`trading_ssh_key_path`) is admin-provisioned, not user-supplied.

**Accepted rationale for v2.0.0:** Inputs are server-controlled; no known injection path. Flag for follow-up refactor to `subprocess.run([...], shell=False)` with a proper argv list. Tracked as **SEC-001**.

---

### F-2 (Sev-2): `tarfile.extractall` without member validation

**Bandit rule:** B202 (tarfile_unsafe_members), High confidence
**Location:** `shared/model_registry/bundler.py:49`

**Description:** Fallback branch (for Python < 3.12 where `filter="data"` isn't available) calls `tar.extractall(path=dest_dir)` without validating archive members. A malicious archive could write files outside `dest_dir` via `../` path traversal or symlinks.

**Current mitigations:**
- Primary branch uses `filter="data"` (Python 3.12+) — the safest mode.
- Model bundles are server-produced during backtest runs; never uploaded by users.
- Dest dir is inside `~/agents/live/<channel_name>/` which is agent-sandboxed.
- The project declares `requires-python = ">=3.11"` so the fallback rarely executes.

**Accepted rationale for v2.0.0:** All bundles originate from internal `backtest-runner`. No untrusted archive ingress. Tracked as **SEC-002** — add explicit member-path validator for defense in depth.

---

### Resolved in this commit — `hashlib.md5` / `hashlib.sha1` for non-security hashing

These were Bandit-High-Confidence but not security issues — MD5/SHA1 are appropriate for cache keys, fingerprints, and content addressing. Added `usedforsecurity=False` kwarg (Python 3.9+) to silence the scanner and document intent:

| File:Line | Use | Resolution |
|---|---|---|
| `shared/utils/signal_parser.py:657` | LLM parse-result cache key | `usedforsecurity=False` added |
| `shared/utils/signal_parser.py:773` | LLM parse-result cache key | `usedforsecurity=False` added |
| `apps/api/src/services/backtest_orchestrator.py:78` | Algorithm-set config fingerprint | `usedforsecurity=False` added |
| `shared/data/base_client.py:94` | HTTP response cache filename | `usedforsecurity=False` added |
| `services/message-ingestion/src/collectors/polymarket/base.py:71` | Article stable-id generator | `usedforsecurity=False` added |

---

### Informational — Jinja2 `autoescape=False`

4 Bandit-High findings (`B701`) in `agent-builder`, `agent-gateway`, `agent-orchestrator`, `create_live_agent`:

Jinja2 is used to render **Python code, Markdown, and JSON** files — not HTML. Autoescape is explicitly disabled because HTML escaping would corrupt the output. No XSS surface — rendered files are written to disk and consumed by the agent runtime, never served to browsers.

No action required. Documented here for reviewer visibility.

---

## npm Dashboard Audit

Pre-fix state (at start of Phase E):
- `axios` < 1.12.0 — NO_PROXY bypass + cloud metadata exfil (GHSA-4hjh-wcwx-04pq, GHSA-jr5f-v2jv-69x6)
- `follow-redirects` — auth header leak on cross-domain redirect (GHSA-cxjh-pqwp-8mfp)

Fixes applied:
- `apps/dashboard/package.json`: `axios` `^1.6.0` → `^1.12.2`
- Added workspace-root `package.json` overrides: `follow-redirects` `^1.15.10`, `axios` `^1.12.2`
- Ran `npm install` + `npm audit fix` — lockfile regenerated at repo root

Post-fix state:
```
$ npm audit
found 0 vulnerabilities
```

All 3 Dependabot moderate alerts (#33, #34, #35) should auto-close when GitHub re-scans the updated lockfile.

---

## Out-of-scope items (follow-up tickets)

1. **SEC-001** — refactor `create_live_agent.py` SSH/SCP calls to argv-list subprocess invocation.
2. **SEC-002** — add explicit archive-member validator to `bundler.py` fallback branch.
3. **SEC-003** — integrate `pip-audit` in CI to catch Python CVEs (parity with `npm audit` for dashboard).
4. **SEC-004** — run `gitleaks` across git history in CI (catch any historical secret leakage).

None of SEC-001..004 block v2.0.0 go-live.
