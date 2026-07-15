"""Write leads to the Google Sheet template.

Three output modes, tried in order:
  1. Service account (GOOGLE_SHEET_ID + GOOGLE_SERVICE_ACCOUNT_JSON)
  2. Apps Script webhook (SHEETS_WEBHOOK_URL) - needs NO Google Cloud
     admin: paste docs/google_apps_script.gs into the sheet's Apps
     Script editor and deploy it as a web app (see README)
  3. CSV fallback (out/leads.csv, same columns)

Column order/headers come from config/sheet_columns.yaml so the output can
be remapped to any sheet template without code changes. Rows are upserted
keyed on the company's domain (via key_column).
"""

from __future__ import annotations

import csv
import logging
import os

import requests
import yaml

from ..models import Company
from ..utils import normalize_domain

log = logging.getLogger("fire_leadgen.sheets")


class SheetWriter:
    def __init__(self, columns_path: str, csv_fallback: str, output_cfg: dict | None = None):
        with open(columns_path) as fh:
            cfg = yaml.safe_load(fh)
        output_cfg = output_cfg or {}
        self.columns: dict[str, str] = cfg["columns"]  # header -> field
        self.key_column: str = cfg.get("key_column", "Website")
        self.csv_fallback = csv_fallback
        self._ws = None
        self.webhook_url = os.environ.get("SHEETS_WEBHOOK_URL", "")
        # per-sector tab in the shared spreadsheet
        self.worksheet = output_cfg.get("worksheet") or os.environ.get(
            "GOOGLE_SHEET_WORKSHEET", "Leads"
        )
        self._connect()

    def _connect(self) -> None:
        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
        sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not sheet_id or not sa_path or not os.path.exists(sa_path):
            if self.webhook_url:
                log.info("Writing to Google Sheet via Apps Script webhook")
            else:
                log.warning(
                    "No sheet output configured (service account or "
                    "SHEETS_WEBHOOK_URL) - writing to %s instead",
                    self.csv_fallback,
                )
            return
        try:
            import gspread

            gc = gspread.service_account(filename=sa_path)
            sh = gc.open_by_key(sheet_id)
            try:
                self._ws = sh.worksheet(self.worksheet)
            except gspread.WorksheetNotFound:
                self._ws = sh.add_worksheet(self.worksheet, rows=2000, cols=len(self.columns))
            self._ensure_header()
            log.info("Connected to Google Sheet %s / %s", sheet_id, self.worksheet)
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
        """Write companies to the configured output. Raises on a transient
        webhook/API failure so callers can retry the batch next cycle."""
        if not companies:
            return 0
        if self._ws is None:
            if self.webhook_url:
                return self._write_webhook(companies)
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

    def _write_webhook(self, companies: list[Company]) -> int:
        """POST rows to the Apps Script web app attached to the sheet."""
        headers = list(self.columns.keys())
        rows = []
        for company in companies:
            data = company.to_dict()
            rows.append({h: str(data.get(f, "") or "") for h, f in self.columns.items()})
        payload = {
            "secret": os.environ.get("SHEETS_WEBHOOK_SECRET", ""),
            "worksheet": self.worksheet,
            "key_column": self.key_column,
            "headers": headers,
            "rows": rows,
        }
        resp = requests.post(self.webhook_url, json=payload, timeout=90)
        resp.raise_for_status()
        try:
            body = resp.json()
        except ValueError as exc:
            raise RuntimeError(
                "Webhook returned non-JSON (check the Apps Script deployment "
                "is a Web app with access 'Anyone')"
            ) from exc
        if not body.get("ok"):
            raise RuntimeError(f"Webhook error: {body.get('error', 'unknown')}")
        return int(body.get("written", len(rows)))

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
