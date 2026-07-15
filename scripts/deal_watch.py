#!/usr/bin/env python3
"""Daily M&A / market-activity sweep, one pass per sector.

For every sector in sectors/ (staged ones included - deal awareness
doesn't wait for scraping), runs that sector's deal_watch.queries
against Google News via Serper, dedupes against data/dealwatch.sqlite3,
and prints ONLY the never-seen-before items as JSON grouped by sector.

The daily Deal Watch routine interprets the output: flags acquisitions
of companies already in our sheet, promotes new acquirers into the
sector's buyer screen, and sends the user a digest.

Usage:  python scripts/deal_watch.py [--window w]   (tbs window: d/w/m)
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
import sys
import time

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "dealwatch.sqlite3")
NEWS_URL = "https://google.serper.dev/news"

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    url        TEXT PRIMARY KEY,
    sector     TEXT NOT NULL,
    title      TEXT,
    source     TEXT,
    date       TEXT,
    snippet    TEXT,
    first_seen TEXT NOT NULL
);
"""


def load_env() -> None:
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def news(query: str, key: str, window: str) -> list[dict]:
    try:
        resp = requests.post(
            NEWS_URL,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": 10, "tbs": f"qdr:{window}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("news", [])
    except requests.RequestException as exc:
        print(f"  ! news query failed ({query!r}): {exc}", file=sys.stderr)
        return []


def main() -> int:
    load_env()
    key = os.environ.get("SERPER_API_KEY", "")
    if not key:
        raise SystemExit("SERPER_API_KEY not configured")
    window = "w" if "--window" not in sys.argv else sys.argv[sys.argv.index("--window") + 1]

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    fresh: dict[str, list[dict]] = {}
    for cfg_path in sorted(glob.glob(os.path.join(ROOT, "sectors", "*", "config.yaml"))):
        cfg = yaml.safe_load(open(cfg_path))
        sector = cfg.get("sector", os.path.basename(os.path.dirname(cfg_path)))
        queries = (cfg.get("deal_watch") or {}).get("queries") or [
            f'"{sector}" acquisition',
            f'"{sector}" acquired',
            f'"{sector}" "private equity"',
        ]
        for query in queries:
            for item in news(query, key, window):
                url = item.get("link", "")
                if not url:
                    continue
                try:
                    conn.execute(
                        "INSERT INTO deals VALUES(?,?,?,?,?,?,?)",
                        (url, sector, item.get("title", ""), item.get("source", ""),
                         item.get("date", ""), item.get("snippet", ""),
                         time.strftime("%Y-%m-%d %H:%M:%S")),
                    )
                except sqlite3.IntegrityError:
                    continue  # already seen on a previous sweep
                fresh.setdefault(sector, []).append(
                    {"title": item.get("title", ""), "url": url,
                     "source": item.get("source", ""), "date": item.get("date", ""),
                     "snippet": item.get("snippet", "")}
                )
            time.sleep(1)
    conn.commit()

    print(json.dumps({"new_items": fresh,
                      "total": sum(len(v) for v in fresh.values())}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
