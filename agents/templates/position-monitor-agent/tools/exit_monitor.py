"""Main monitoring loop for position sub-agent.

Polls exit_decision.py at the configured interval and executes exits when
urgency thresholds are reached. Self-terminates when position is closed.

Usage:
    python exit_monitor.py --position-id POS123
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent


def _check_position_open() -> bool:
    """Check if the position is still open."""
    pos = Path("position.json")
    if not pos.exists():
        return False
    try:
        data = json.loads(pos.read_text())
        return data.get("status", "open") == "open" and data.get("qty", 0) > 0
    except Exception:
        return False


def _terminate_self(position_id: str, config: dict) -> None:
    """Mark this sub-agent as terminated via Phoenix API."""
    try:
        import httpx
        api_url = config.get("phoenix_api_url", "")
        api_key = config.get("phoenix_api_key", "")
        session_id = os.getenv("AGENT_SESSION_ID", config.get("session_id", ""))
        if api_url and session_id:
            httpx.post(
                f"{api_url}/api/v2/agents/{session_id}/terminate",
                headers={"X-Agent-Key": api_key},
                json={"reason": "position_closed", "position_id": position_id},
                timeout=10,
            )
    except Exception as e:
        print(f"  [exit_monitor] Could not self-terminate: {e}", file=sys.stderr)


def _report_exit(decision: dict, config: dict) -> None:
    """Report exit to Phoenix API and broadcast to peer agents."""
    try:
        import httpx
        api_url = config.get("phoenix_api_url", "")
        api_key = config.get("phoenix_api_key", "")
        parent_id = config.get("parent_agent_id", "")
        if api_url and parent_id:
            httpx.post(
                f"{api_url}/api/v2/agents/{parent_id}/live-trades",
                headers={"X-Agent-Key": api_key},
                json={
                    "ticker": decision.get("ticker"),
                    "exit_price": decision.get("current_price"),
                    "pnl_pct": decision.get("pnl_pct"),
                    "exit_reason": decision.get("reasoning"),
                    "decision_status": "exit_executed",
                },
                timeout=10,
            )
    except Exception as e:
        print(f"  [exit_monitor] Report failed: {e}", file=sys.stderr)


def monitor_loop(position_id: str) -> None:
    print(f"[exit_monitor] Starting loop for position {position_id}")

    config = {}
    config_path = Path("config.json")
    if config_path.exists():
        config = json.loads(config_path.read_text())

    started_at = time.time()
    cycle = 0

    while _check_position_open():
        cycle += 1
        elapsed = time.time() - started_at

        # Run exit decision check
        decision_path = Path(f"check_{cycle}.json")
        try:
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / "exit_decision.py"),
                 "--position-id", position_id, "--output", str(decision_path)],
                capture_output=True, text=True, timeout=180,
            )
            if decision_path.exists():
                decision = json.loads(decision_path.read_text())
            else:
                print(f"[exit_monitor] cycle {cycle}: no decision output", file=sys.stderr)
                time.sleep(60)
                continue
        except Exception as e:
            print(f"[exit_monitor] cycle {cycle} error: {e}", file=sys.stderr)
            time.sleep(60)
            continue

        action = decision.get("action", "HOLD")
        urgency = decision.get("urgency", 0)
        print(f"[exit_monitor] cycle {cycle}: {action} (urgency={urgency}) — {decision.get('reasoning', '')[:200]}")

        if action in ("PARTIAL_EXIT", "FULL_EXIT"):
            exit_pct = decision.get("suggested_exit_pct", 100 if action == "FULL_EXIT" else 50)
            try:
                exec_result = subprocess.run(
                    [sys.executable, str(TOOLS_DIR / "exit_decision.py"),
                     "--position-id", position_id, "--execute", "--pct", str(exit_pct),
                     "--output", str(decision_path)],
                    capture_output=True, text=True, timeout=180,
                )
                exec_decision = json.loads(decision_path.read_text())
                _report_exit(exec_decision, config)

                # Update local position.json
                pos_data = json.loads(Path("position.json").read_text())
                if action == "FULL_EXIT":
                    pos_data["status"] = "closed"
                    pos_data["qty"] = 0
                    pos_data["closed_at"] = datetime.now(timezone.utc).isoformat()
                else:
                    pos_data["qty"] = max(0, pos_data.get("qty", 0) - int(pos_data.get("qty", 0) * exit_pct / 100))
                Path("position.json").write_text(json.dumps(pos_data, indent=2))

                if action == "FULL_EXIT":
                    print(f"[exit_monitor] Position fully closed. Self-terminating.")
                    _terminate_self(position_id, config)
                    return
            except Exception as e:
                print(f"[exit_monitor] Execution failed: {e}", file=sys.stderr)

        # Determine next sleep interval
        if elapsed < 300:  # First 5 minutes
            sleep_s = 30
        elif urgency >= 50:
            sleep_s = 30
        else:
            sleep_s = 120

        time.sleep(sleep_s)

    print(f"[exit_monitor] Position no longer open. Terminating.")
    _terminate_self(position_id, config)


def main():
    parser = argparse.ArgumentParser(description="Position monitor loop")
    parser.add_argument("--position-id", required=True)
    args = parser.parse_args()
    monitor_loop(args.position_id)


if __name__ == "__main__":
    main()
