"""Local PPP-loan index - the research manual's primary size signal.

PPP loan amounts were payroll-based, so they anchor both the revenue
estimate (loan x sector multiplier; 15.4 for fire protection) and the
employee count (the dataset's JobsReported column).

The full loan-level dataset is public FOIA data from the SBA:
    https://data.sba.gov/dataset/ppp-foia   (CSV files)
Download the CSVs (or just the states you work) and index them once:
    fire-leadgen ppp-import path/to/public_up_to_150k_*.csv path/to/public_150k_plus.csv
Lookups then run locally with no network calls.
"""

from __future__ import annotations

import csv
import logging
import re
import sqlite3
import sys

from ..utils import clean_company_name

log = logging.getLogger("fire_leadgen.ppp")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ppp_loans (
    name_norm TEXT NOT NULL,
    name      TEXT NOT NULL,
    city      TEXT,
    state     TEXT,
    amount    REAL,
    jobs      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ppp_state_name ON ppp_loans(state, name_norm);
"""

# column aliases across SBA CSV vintages
COL_NAME = ("BorrowerName", "borrowername", "Name")
COL_CITY = ("BorrowerCity", "borrowercity", "City")
COL_STATE = ("BorrowerState", "borrowerstate", "State")
COL_AMOUNT = ("CurrentApprovalAmount", "InitialApprovalAmount", "currentapprovalamount", "LoanAmount")
COL_JOBS = ("JobsReported", "jobsreported", "Jobs")


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_company_name(name).lower())


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def import_csvs(conn: sqlite3.Connection, paths: list[str]) -> int:
    """Index SBA PPP CSV files into the local database."""
    ensure_schema(conn)
    csv.field_size_limit(sys.maxsize)
    total = 0
    for path in paths:
        n = 0
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            batch = []
            for row in reader:
                name = _pick(row, COL_NAME)
                if not name:
                    continue
                batch.append(
                    (
                        normalize_name(name),
                        name.strip(),
                        (_pick(row, COL_CITY) or "").strip(),
                        (_pick(row, COL_STATE) or "").strip().upper(),
                        _to_float(_pick(row, COL_AMOUNT)),
                        int(_to_float(_pick(row, COL_JOBS)) or 0),
                    )
                )
                n += 1
                if len(batch) >= 5000:
                    conn.executemany("INSERT INTO ppp_loans VALUES(?,?,?,?,?,?)", batch)
                    batch = []
            if batch:
                conn.executemany("INSERT INTO ppp_loans VALUES(?,?,?,?,?,?)", batch)
        conn.commit()
        log.info("Imported %d PPP rows from %s", n, path)
        total += n
    return total


def lookup(conn: sqlite3.Connection, company_name: str, state: str) -> dict:
    """Return {amount, jobs, matched_name} for the best match, or {}.

    A company may appear twice (first + second draw); we take the largest
    single loan, consistent with how the manual uses "PPP loan amount".
    """
    ensure_schema(conn)
    norm = normalize_name(company_name)
    if not norm:
        return {}
    state = (state or "").strip().upper()

    rows = conn.execute(
        "SELECT name, amount, jobs FROM ppp_loans WHERE name_norm=? AND (state=? OR ?='') "
        "ORDER BY amount DESC LIMIT 1",
        (norm, state, state),
    ).fetchall()
    if not rows and len(norm) >= 8:
        rows = conn.execute(
            "SELECT name, amount, jobs FROM ppp_loans WHERE name_norm LIKE ? AND (state=? OR ?='') "
            "ORDER BY amount DESC LIMIT 1",
            (norm + "%", state, state),
        ).fetchall()
    if not rows:
        return {}
    row = rows[0]
    return {"matched_name": row[0], "amount": row[1] or 0.0, "jobs": row[2] or 0}


def has_data(conn: sqlite3.Connection) -> bool:
    ensure_schema(conn)
    return conn.execute("SELECT 1 FROM ppp_loans LIMIT 1").fetchone() is not None


def _pick(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in row and row[key]:
            return row[key]
    return ""


def _to_float(value) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0
