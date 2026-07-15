from __future__ import annotations

import json
import os
import sqlite3

from .models import Company
from .utils import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    domain        TEXT PRIMARY KEY,
    data          TEXT NOT NULL,          -- Company as JSON
    status        TEXT NOT NULL DEFAULT 'new',
    -- new -> extracted -> screened -> enriched -> exported | rejected
    reject_reason TEXT DEFAULT '',
    first_seen    TEXT NOT NULL,
    last_updated  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seen_urls (
    url        TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
"""


class Db:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- state (rotation pointers etc.) ---------------------------------
    def get_state(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO state(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # -- url dedupe ------------------------------------------------------
    def mark_url_seen(self, url: str) -> bool:
        """Return True if the URL was new."""
        try:
            self.conn.execute(
                "INSERT INTO seen_urls(url, first_seen) VALUES(?,?)", (url, now_iso())
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    # -- companies ---------------------------------------------------------
    def has_company(self, domain: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM companies WHERE domain=?", (domain,)
            ).fetchone()
            is not None
        )

    def add_company(self, company: Company, status: str = "new") -> bool:
        if not company.domain or self.has_company(company.domain):
            return False
        ts = now_iso()
        company.first_seen = company.first_seen or ts
        company.last_updated = ts
        self.conn.execute(
            "INSERT INTO companies(domain, data, status, first_seen, last_updated) "
            "VALUES(?,?,?,?,?)",
            (company.domain, json.dumps(company.to_dict()), status, ts, ts),
        )
        self.conn.commit()
        return True

    def save_company(self, company: Company, status: str, reject_reason: str = "") -> None:
        company.last_updated = now_iso()
        self.conn.execute(
            "UPDATE companies SET data=?, status=?, reject_reason=?, last_updated=? "
            "WHERE domain=?",
            (
                json.dumps(company.to_dict()),
                status,
                reject_reason,
                company.last_updated,
                company.domain,
            ),
        )
        self.conn.commit()

    def get_companies(self, status: str, limit: int = 100) -> list[Company]:
        rows = self.conn.execute(
            "SELECT data FROM companies WHERE status=? ORDER BY first_seen LIMIT ?",
            (status, limit),
        ).fetchall()
        out = []
        for row in rows:
            payload = json.loads(row["data"])
            known = {k: v for k, v in payload.items() if k in Company.fields()}
            out.append(Company(**known))
        return out

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM companies GROUP BY status"
        ).fetchall()
        return {row["status"]: row["n"] for row in rows}
