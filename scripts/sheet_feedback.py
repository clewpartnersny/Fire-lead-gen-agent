#!/usr/bin/env python3
"""Pull a sheet tab back through the Apps Script webhook (doGet) so the
trainer can compare what humans changed against what the agent wrote.

Usage:  python scripts/sheet_feedback.py "Sheet1" [out.json]
Requires SHEETS_WEBHOOK_URL / SHEETS_WEBHOOK_SECRET in .env and the
Apps Script version that includes doGet.
"""

from __future__ import annotations

import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env() -> None:
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def fetch(worksheet: str) -> dict:
    load_env()
    url = os.environ.get("SHEETS_WEBHOOK_URL", "")
    secret = os.environ.get("SHEETS_WEBHOOK_SECRET", "")
    if not url:
        raise SystemExit("SHEETS_WEBHOOK_URL not configured")
    resp = requests.get(
        url, params={"secret": secret, "worksheet": worksheet}, timeout=90
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise SystemExit(f"webhook error: {data.get('error')} "
                         "(is the doGet version of the Apps Script deployed?)")
    return data


def main() -> int:
    worksheet = sys.argv[1] if len(sys.argv) > 1 else "Sheet1"
    out_path = sys.argv[2] if len(sys.argv) > 2 else ""
    data = fetch(worksheet)
    payload = json.dumps(data, indent=1)
    if out_path:
        open(out_path, "w").write(payload)
        print(f"wrote {out_path}: {len(data.get('rows', []))} rows")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
