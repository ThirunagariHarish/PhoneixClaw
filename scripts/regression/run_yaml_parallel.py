#!/usr/bin/env python3
"""
Run all journeys from tests/regression/user_journeys.yaml against a live dashboard.

- Uses up to 10 parallel worker *processes* (each owns a Playwright browser).
- Tasks that must run logged-out are executed in a short pre-phase.
- Remaining routes run after login, sharded across workers.
- Batch 11 (api) uses urllib against PHOENIX_API_BASE_URL when set.

Environment:
  PHOENIX_E2E_BASE_URL   Dashboard origin (required), e.g. https://app.example.com
  PHOENIX_E2E_EMAIL / PHOENIX_E2E_PASSWORD
  PHOENIX_API_BASE_URL   API origin for T093–T107, e.g. https://api.example.com or http://localhost:8011
                         If unset, derived from base URL: same host, port 8011 for localhost else
                         tries same origin /api is NOT used — you should set explicitly for prod.

Usage:
  PHOENIX_E2E_BASE_URL=https://... PHOENIX_API_BASE_URL=https://... \\
    python3 scripts/regression/run_yaml_parallel.py

  WORKERS=10 python3 scripts/regression/run_yaml_parallel.py
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = REPO_ROOT / "tests" / "regression" / "user_journeys.yaml"

# Tasks that must run without session cookie (login/register/gate/error).
ANON_TASK_IDS = frozenset({"T001", "T002", "T003", "T007", "T008"})

WORKERS = max(1, min(10, int(os.environ.get("WORKERS", "10"))))


def _load_yaml() -> dict[str, Any]:
    try:
        import yaml
    except ImportError as e:
        raise SystemExit("Install PyYAML: pip install pyyaml") from e
    return yaml.safe_load(YAML_PATH.read_text())


def _flatten_tasks(data: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for batch in data.get("batches", []):
        for t in batch.get("tasks", []):
            t["batch_id"] = batch.get("batch_id")
            out.append(t)
    return out


def _api_base() -> str | None:
    explicit = os.environ.get("PHOENIX_API_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    dash = os.environ.get("PHOENIX_E2E_BASE_URL", "").strip().rstrip("/")
    if "localhost:3000" in dash or "127.0.0.1:3000" in dash:
        return dash.replace(":3000", ":8011")
    return None


def _run_api_tasks(tasks: list[dict]) -> list[dict[str, Any]]:
    base = _api_base()
    results: list[dict[str, Any]] = []
    if not base:
        for t in tasks:
            results.append(
                {
                    "id": t["id"],
                    "status": "SKIP",
                    "detail": "Set PHOENIX_API_BASE_URL (or use localhost:3000 → 8011 derivation)",
                }
            )
        return results

    def get(path: str, headers: dict | None = None) -> tuple[int, str]:
        url = f"{base}{path}"
        req = Request(url, headers=headers or {})
        try:
            with urlopen(req, timeout=15) as resp:
                return resp.status, ""
        except HTTPError as e:
            return e.code, str(e)
        except URLError as e:
            return -1, str(e.reason)

    for t in tasks:
        tid = t["id"]
        title = t.get("title", "")
        try:
            if tid == "T093":
                code, _ = get("/health/lite")
                ok = code == 200
            elif tid == "T094":
                code, _ = get("/health")
                ok = code == 200
            elif tid == "T095":
                code, _ = get("/api/v2/agents")
                ok = code in (401, 403)
            elif tid == "T096":
                code, _ = get("/api/v2/connectors")
                ok = code in (200, 401, 403)
            elif tid == "T097":
                code, _ = get("/api/v2/system-logs")
                ok = code in (200, 401, 403)
            else:
                results.append({"id": tid, "status": "SKIP", "detail": "manual/ops — " + title})
                continue
            results.append({"id": tid, "status": "PASS" if ok else "FAIL", "detail": f"HTTP {code}"})
        except Exception as e:
            results.append({"id": tid, "status": "FAIL", "detail": str(e)})
    return results


def _run_anon_browser(tasks: list[dict], base_url: str, email: str) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    results: list[dict[str, Any]] = []
    # Sort so /login flows come before /trades gate
    order = ["T001", "T002", "T007", "T008", "T003"]
    tasks_sorted = sorted(tasks, key=lambda x: order.index(x["id"]) if x["id"] in order else 99)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for t in tasks_sorted:
            rid = t["id"]
            route = t.get("route", "")
            context = browser.new_context()
            page = context.new_page()
            try:
                url = f"{base_url.rstrip('/')}{route}"
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                if rid == "T003":
                    u = page.url
                    ok = "login" in u or "trades" in u
                elif rid == "T007":
                    page.get_by_role("button", name="Sign in").click()
                    ok = page.get_by_label("Email").count() > 0
                elif rid == "T008":
                    page.get_by_label("Email").fill(email)
                    page.get_by_label("Password").fill("definitely-wrong-password-xyz")
                    page.get_by_role("button", name="Sign in").click()
                    ok = page.get_by_label("Email").count() > 0
                else:
                    ok = _page_ok(page)
                results.append({"id": rid, "status": "PASS" if ok else "FAIL", "detail": page.url[:120]})
            except Exception as e:
                results.append({"id": rid, "status": "FAIL", "detail": str(e)[:200]})
            finally:
                context.close()
        browser.close()
    return results


def _page_ok(page) -> bool:
    if page.locator("text=Unexpected Application Error").count() > 0:
        return False
    if page.locator("text=Something went wrong").count() > 0:
        return False
    return True


def _worker_shard(shard_index: int, tasks: list[dict], base_url: str, email: str, password: str) -> list[dict]:
    """Run in child process. Never raises — each task is PASS/FAIL."""
    from playwright.sync_api import sync_playwright

    results: list[dict[str, Any]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto(f"{base_url.rstrip('/')}/login", wait_until="domcontentloaded", timeout=60000)
                page.get_by_label("Email").fill(email)
                page.get_by_label("Password").fill(password)
                page.get_by_role("button", name="Sign in").click()
                page.wait_for_url("**/trades**", timeout=120000)
            except Exception as e:
                for t in tasks:
                    results.append(
                        {
                            "id": t["id"],
                            "status": "FAIL",
                            "detail": f"login: {str(e)[:180]}",
                        }
                    )
                browser.close()
                return results

            for t in tasks:
                rid = t["id"]
                route = str(t.get("route", "/"))
                try:
                    url = f"{base_url.rstrip('/')}{route}"
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    ok = _page_ok(page)
                    results.append({"id": rid, "status": "PASS" if ok else "FAIL", "detail": page.url[:120]})
                except Exception as e:
                    results.append({"id": rid, "status": "FAIL", "detail": str(e)[:200]})
            browser.close()
    except Exception as e:
        for t in tasks:
            if not any(r.get("id") == t["id"] for r in results):
                results.append({"id": t["id"], "status": "FAIL", "detail": str(e)[:200]})
    return results


def main() -> int:
    base_url = os.environ.get("PHOENIX_E2E_BASE_URL", "").strip()
    if not base_url:
        print("ERROR: Set PHOENIX_E2E_BASE_URL to your dashboard URL.", file=sys.stderr)
        return 1

    email = os.environ.get("PHOENIX_E2E_EMAIL", "test@phoenix.io")
    password = os.environ.get("PHOENIX_E2E_PASSWORD", "testpassword123")

    data = _load_yaml()
    all_tasks = _flatten_tasks(data)

    api_tasks = [t for t in all_tasks if str(t.get("route")) == "(api)"]
    browser_tasks = [t for t in all_tasks if str(t.get("route", "")).startswith("/")]

    anon = [t for t in browser_tasks if t["id"] in ANON_TASK_IDS]
    authed = [t for t in browser_tasks if t["id"] not in ANON_TASK_IDS]

    print(f"YAML: {len(all_tasks)} tasks | browser: {len(browser_tasks)} | api: {len(api_tasks)} | workers: {WORKERS}")
    print(f"Base URL: {base_url}")
    all_results: list[dict[str, Any]] = []

    print("Phase 0: API checks (main process)…")
    all_results.extend(_run_api_tasks(api_tasks))

    print("Phase 1: Anonymous browser tasks…")
    all_results.extend(_run_anon_browser(anon, base_url, email))

    # Shard authed tasks across WORKERS
    n = len(authed)
    if n == 0:
        pass
    else:
        shards: list[list[dict]] = [[] for _ in range(WORKERS)]
        for i, t in enumerate(authed):
            shards[i % WORKERS].append(t)
        print(f"Phase 2: Authenticated parallel shards ({sum(len(s) for s in shards)} tasks across {WORKERS} workers)…")
        futures = []
        with ProcessPoolExecutor(max_workers=WORKERS) as ex:
            for i, shard in enumerate(shards):
                if not shard:
                    continue
                futures.append(ex.submit(_worker_shard, i, shard, base_url, email, password))
            for fut in as_completed(futures):
                all_results.extend(fut.result())

    passed = sum(1 for r in all_results if r.get("status") == "PASS")
    failed = sum(1 for r in all_results if r.get("status") == "FAIL")
    skipped = sum(1 for r in all_results if r.get("status") == "SKIP")
    report = {
        "base_url": base_url,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "results": sorted(all_results, key=lambda x: x["id"]),
    }
    out_path = REPO_ROOT / "tests" / "regression" / "last_run_report.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nDone. PASS={passed} FAIL={failed} SKIP={skipped}")
    print(f"Report: {out_path}")
    if failed:
        for r in report["results"]:
            if r.get("status") == "FAIL":
                print(f"  FAIL {r['id']}: {r.get('detail', '')[:100]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
