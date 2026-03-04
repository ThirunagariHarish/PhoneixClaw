#!/usr/bin/env python3
"""
Register the remote OpenClaw instance with the Phoenix API.
Usage:
  OPENCLAW_HOST=187.124.77.249 OPENCLAW_PORT=18800 python scripts/register_openclaw_instance.py
  # Or Bridge on same port as UI:
  OPENCLAW_HOST=187.124.77.249 OPENCLAW_PORT=41100 python scripts/register_openclaw_instance.py

Requires: API running, valid JWT. Get JWT via login first, then:
  export PHOENIX_TOKEN="<access_token>"
  python scripts/register_openclaw_instance.py
"""
import os
import sys

import httpx

API_BASE = os.getenv("API_BASE", "http://localhost:8011")
OPENCLAW_HOST = os.getenv("OPENCLAW_HOST", "187.124.77.249")
OPENCLAW_PORT = int(os.getenv("OPENCLAW_PORT", "18800"))
INSTANCE_NAME = os.getenv("OPENCLAW_INSTANCE_NAME", "OpenClaw-Remote")
TOKEN = os.getenv("PHOENIX_TOKEN", "")


def main():
    payload = {
        "name": INSTANCE_NAME,
        "host": OPENCLAW_HOST,
        "port": OPENCLAW_PORT,
        "role": "general",
        "node_type": "vps",
        "capabilities": {},
    }
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        r = httpx.post(f"{API_BASE}/api/v2/instances", json=payload, headers=headers, timeout=10.0)
        if r.status_code == 201:
            data = r.json()
            print(f"Registered instance: {data.get('name')} id={data.get('id')} at {OPENCLAW_HOST}:{OPENCLAW_PORT}")
            return 0
        if r.status_code == 409:
            print("Instance with this name already exists. Use a different OPENCLAW_INSTANCE_NAME or delete the existing one.")
            return 1
        print(f"Error {r.status_code}: {r.text}")
        return 1
    except Exception as e:
        print(f"Request failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
