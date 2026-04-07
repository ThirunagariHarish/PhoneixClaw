"""End-to-end verification script for the Agents tab.

Walks every Agents tab feature against a real (or seeded) agent and reports
PASS/FAIL with actionable error messages. Run this before tomorrow's session
to confirm the dashboard backend is healthy.

Usage:
    python scripts/verify_agents_e2e.py [--api-url http://localhost:8011] [--agent-id <uuid>]

If --agent-id is omitted, the script uses the most recent agent in the DB.
Returns exit code 0 on full pass, 1 on any failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
GRAY = "\033[90m"
RESET = "\033[0m"


class TestRunner:
    def __init__(self, api_url: str, agent_id: str | None = None):
        self.api_url = api_url.rstrip("/")
        self.agent_id = agent_id
        self.results: list[dict] = []
        self.session = None

    def _client(self):
        if self.session is None:
            try:
                import httpx
                self.session = httpx.Client(timeout=15.0)
            except ImportError:
                print(f"{RED}httpx not installed. Run: pip install httpx{RESET}")
                sys.exit(1)
        return self.session

    def _record(self, name: str, status: str, detail: str = "", duration_ms: int = 0):
        self.results.append({
            "name": name,
            "status": status,
            "detail": detail,
            "duration_ms": duration_ms,
        })
        icon = (
            f"{GREEN}✓{RESET}" if status == "PASS"
            else f"{RED}✗{RESET}" if status == "FAIL"
            else f"{YELLOW}⊘{RESET}"
        )
        suffix = f" {GRAY}({duration_ms}ms){RESET}" if duration_ms else ""
        print(f"  {icon} {name}{suffix}")
        if detail and status != "PASS":
            print(f"    {GRAY}{detail}{RESET}")

    def run_check(self, name: str, fn):
        t0 = time.time()
        try:
            result = fn()
            duration = int((time.time() - t0) * 1000)
            if result is True or result is None:
                self._record(name, "PASS", "", duration)
                return True
            elif isinstance(result, str):
                self._record(name, "FAIL", result, duration)
                return False
            elif isinstance(result, dict) and result.get("ok"):
                self._record(name, "PASS", result.get("note", ""), duration)
                return True
            else:
                self._record(name, "FAIL", str(result), duration)
                return False
        except Exception as exc:
            duration = int((time.time() - t0) * 1000)
            self._record(name, "FAIL", str(exc)[:300], duration)
            return False

    def get(self, path: str) -> Any:
        c = self._client()
        r = c.get(f"{self.api_url}{path}")
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def post(self, path: str, body: dict | None = None) -> Any:
        c = self._client()
        r = c.post(f"{self.api_url}{path}", json=body or {})
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json() if r.text else {}

    def discover_agent_id(self) -> str | None:
        """Pick the latest agent from the API if no ID was provided."""
        try:
            agents = self.get("/api/v2/agents")
            if not isinstance(agents, list) or not agents:
                return None
            return agents[0].get("id")
        except Exception:
            return None

    def run(self) -> bool:
        print(f"\n{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
        print(f"{CYAN}Phoenix Agents E2E Verification{RESET}")
        print(f"{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
        print(f"API: {self.api_url}")
        print()

        # ── 1. API health ──
        print(f"{CYAN}1. API Health{RESET}")
        self.run_check("Health endpoint reachable", lambda: self._check_health())
        self.run_check("Scheduler running", lambda: self._check_scheduler())

        # ── 2. Agent discovery ──
        print(f"\n{CYAN}2. Agent Discovery{RESET}")
        if not self.agent_id:
            self.agent_id = self.discover_agent_id()
            if self.agent_id:
                self._record("Found agent", "PASS", f"id={self.agent_id[:8]}...", 0)
            else:
                self._record("No agents in DB", "SKIP", "Create an agent first", 0)
                self._summary()
                return False
        else:
            self._record("Using agent from CLI", "PASS", self.agent_id, 0)

        # ── 3. Per-agent endpoints ──
        print(f"\n{CYAN}3. Per-Agent Endpoints{RESET}")
        endpoints = [
            ("GET /agents/{id}", lambda: self.get(f"/api/v2/agents/{self.agent_id}")),
            ("GET /agents/{id}/positions", lambda: self.get(f"/api/v2/agents/{self.agent_id}/positions")),
            ("GET /agents/{id}/live-trades", lambda: self.get(f"/api/v2/agents/{self.agent_id}/live-trades")),
            ("GET /agents/{id}/logs", lambda: self.get(f"/api/v2/agents/{self.agent_id}/logs?limit=10")),
            ("GET /agents/{id}/runtime-info", lambda: self.get(f"/api/v2/agents/{self.agent_id}/runtime-info")),
            ("GET /agents/{id}/paper-portfolio", lambda: self.get(f"/api/v2/agents/{self.agent_id}/paper-portfolio")),
            ("GET /agents/{id}/activity-feed", lambda: self.get(f"/api/v2/agents/{self.agent_id}/activity-feed?limit=20")),
            ("GET /agents/{id}/position-agents", lambda: self.get(f"/api/v2/agents/{self.agent_id}/position-agents")),
            ("GET /agents/{id}/pending-improvements", lambda: self.get(f"/api/v2/agents/{self.agent_id}/pending-improvements")),
        ]
        for name, fn in endpoints:
            self.run_check(name, lambda f=fn, n=name: self._check_endpoint(f, n))

        # ── 4. Trade signals ──
        print(f"\n{CYAN}4. Trade Signals (RL feedback){RESET}")
        self.run_check("GET /trade-signals", lambda: self._check_endpoint(
            lambda: self.get(f"/api/v2/trade-signals?agent_id={self.agent_id}&days=7"), "trade-signals"))
        self.run_check("GET /trade-signals/stats", lambda: self._check_endpoint(
            lambda: self.get(f"/api/v2/trade-signals/stats?agent_id={self.agent_id}"), "stats"))

        # ── 5. Cross-cutting features ──
        print(f"\n{CYAN}5. Cross-Cutting Features{RESET}")
        self.run_check("GET /agents/graph", lambda: self._check_endpoint(
            lambda: self.get("/api/v2/agents/graph"), "graph"))
        self.run_check("GET /agents/eod-analysis/latest", lambda: self._check_endpoint(
            lambda: self.get("/api/v2/agents/eod-analysis/latest"), "eod"))
        self.run_check("GET /scheduler/status", lambda: self._check_endpoint(
            lambda: self.get("/api/v2/scheduler/status"), "scheduler"))

        # ── 6. Mutating endpoints (manual triggers, dry-run safe) ──
        print(f"\n{CYAN}6. Manual Triggers{RESET}")
        self.run_check("POST /agents/{id}/instruct", lambda: self._check_instruct())

        # ── 7. Connectors ──
        print(f"\n{CYAN}7. Connectors{RESET}")
        self.run_check("GET /connectors", lambda: self._check_endpoint(
            lambda: self.get("/api/v2/connectors"), "connectors"))

        return self._summary()

    def _check_health(self):
        c = self._client()
        r = c.get(f"{self.api_url}/health")
        if r.status_code != 200:
            return f"Health returned {r.status_code}"
        data = r.json()
        if data.get("status") != "ready":
            return f"Status: {data.get('status')}"
        return True

    def _check_scheduler(self):
        try:
            data = self.get("/api/v2/scheduler/status")
        except Exception as exc:
            return f"Endpoint failed: {exc}"
        if not data.get("running"):
            return f"Scheduler not running: {data.get('reason') or data.get('error', 'unknown')}"
        jobs = data.get("jobs", [])
        if not jobs:
            return "Scheduler running but no jobs registered"
        return True

    def _check_endpoint(self, fn, name):
        try:
            data = fn()
        except Exception as exc:
            return f"Failed: {exc}"
        if data is None:
            return "Returned None"
        # Empty lists/dicts are OK as long as the endpoint responds
        return True

    def _check_instruct(self):
        try:
            result = self.post(f"/api/v2/agents/{self.agent_id}/instruct",
                               {"instruction": "verify_e2e_test"})
            if result.get("agent_id") == self.agent_id:
                return True
            return f"Unexpected response: {result}"
        except Exception as exc:
            return f"Failed: {exc}"

    def _summary(self) -> bool:
        print(f"\n{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        skipped = sum(1 for r in self.results if r["status"] == "SKIP")
        total = len(self.results)

        print(f"Results: {GREEN}{passed} passed{RESET}, "
              f"{RED}{failed} failed{RESET}, "
              f"{YELLOW}{skipped} skipped{RESET} of {total}")

        if failed:
            print(f"\n{RED}FAILURES:{RESET}")
            for r in self.results:
                if r["status"] == "FAIL":
                    print(f"  ✗ {r['name']}")
                    print(f"    {GRAY}{r['detail']}{RESET}")

        # Write JSON report
        report_path = os.environ.get("E2E_REPORT", "verify_agents_report.json")
        with open(report_path, "w") as f:
            json.dump({
                "api_url": self.api_url,
                "agent_id": self.agent_id,
                "timestamp": datetime.now().isoformat(),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "total": total,
                "results": self.results,
            }, f, indent=2)
        print(f"\n{GRAY}Report written to {report_path}{RESET}")

        return failed == 0


def main():
    parser = argparse.ArgumentParser(description="E2E verification for Phoenix Agents tab")
    parser.add_argument("--api-url", default=os.getenv("PHOENIX_API_URL", "http://localhost:8011"))
    parser.add_argument("--agent-id", default=None)
    args = parser.parse_args()

    runner = TestRunner(args.api_url, args.agent_id)
    success = runner.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
