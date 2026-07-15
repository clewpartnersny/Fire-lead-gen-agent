"""Write leads to the Google Sheet template (or a CSV fallback when no
service-account credentials are configured).

Column order/headers come from config/sheet_columns.yaml so the output can
be remapped to any sheet template without code changes. Rows are upserted
keyed on the company's domain (via key_column).
"""

from __future__ import annotations

import csv
import logging
import os

import yaml

from ..models import Company
from ..utils import normalize_domain

log = logging.getLogger("fire_leadgen.sheets")


class SheetWriter:
    def __init__(self, columns_path: str, csv_fallback: str):
        with open(columns_path) as fh:
            cfg = yaml.safe_load(fh)
        self.columns: dict[str, str] = cfg["columns"]  # header -> field
        self.key_column: str = cfg.get("key_column", "Website")
        self.csv_fallback = csv_fallback
        self._ws = None
        self._connect()

    def _connect(self) -> None:
        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
        sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not sheet_id or not sa_path or not os.path.exists(sa_path):
            log.warning(
                "Google Sheets not configured (GOOGLE_SHEET_ID / "
                "GOOGLE_SERVICE_ACCOUNT_JSON) - writing to %s instead",
                self.csv_fallback,
            )
            return
        try:
            import gspread

            gc = gspread.service_account(filename=sa_path)
            sh = gc.open_by_key(sheet_id)
            ws_name = os.environ.get("GOOGLE_SHEET_WORKSHEET", "Leads")
            try:
                self._ws = sh.worksheet(ws_name)
            except gspread.WorksheetNotFound:
                self._ws = sh.add_worksheet(ws_name, rows=2000, cols=len(self.columns))
            self._ensure_header()
            log.info("Connected to Google Sheet %s / %s", sheet_id, ws_name)
        except Exception as exc:
            log.error("Google Sheets connection failed (%s); using CSV fallback", exc)
            self._ws = None

    def _ensure_header(self) -> None:
        headers = list(self.columns.keys())
        current = self._ws.row_values(1)
        if current != headers:
            if current:
                log.warning(
                    "Sheet header differs from sheet_columns.yaml; leaving the "
                    "sheet's existing header in place and mapping by name"
                )
                # append any missing headers at the end
                missing = [h for h in headers if h not in current]
                if missing:
                    self._ws.update(
                        range_name=f"R1C{len(current) + 1}",
                        values=[missing],
                    )
            else:
                self._ws.update(range_name="A1", values=[headers])

    def _row_for(self, company: Company, headers: list[str]) -> list[str]:
        data = company.to_dict()
        return [str(data.get(self.columns.get(h, ""), "") or "") for h in headers]

    def upsert(self, companies: list[Company]) -> int:
        if not companies:
            return 0
        if self._ws is None:
            return self._write_csv(companies)

        headers = self._ws.row_values(1)
        key_field = self.columns.get(self.key_column, "website")
        try:
            key_col_idx = headers.index(self.key_column) + 1
        except ValueError:
            key_col_idx = 1
        existing = {
            normalize_domain(v): i + 2
            for i, v in enumerate(self._ws.col_values(key_col_idx)[1:])
            if v
        }

        appends = []
        written = 0
        for company in companies:
            row = self._row_for(company, headers)
            key = normalize_domain(str(company.to_dict().get(key_field, "")))
            if key in existing:
                self._ws.update(range_name=f"A{existing[key]}", values=[row])
            else:
                appends.append(row)
            written += 1
        if appends:
            self._ws.append_rows(appends, value_input_option="USER_ENTERED")
        return written

    def _write_csv(self, companies: list[Company]) -> int:
        os.makedirs(os.path.dirname(self.csv_fallback) or ".", exist_ok=True)
        headers = list(self.columns.keys())
        new_file = not os.path.exists(self.csv_fallback)
        with open(self.csv_fallback, "a", newline="") as fh:
            writer = csv.writer(fh)
            if new_file:
                writer.writerow(headers)
            for company in companies:
                writer.writerow(self._row_for(company, headers))
        return len(companies)
