"""Apps Script webhook output mode (requests mocked)."""

import pytest

import fire_leadgen.output.sheets as sheets_mod
from fire_leadgen.models import Company
from fire_leadgen.output.sheets import SheetWriter

import os

CONFIG = os.path.join(os.path.dirname(__file__), "..", "sectors", "fire-protection", "sheet_columns.yaml")


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def make_writer(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.setenv("SHEETS_WEBHOOK_URL", "https://script.google.com/macros/s/XXX/exec")
    monkeypatch.setenv("SHEETS_WEBHOOK_SECRET", "s3cret")
    return SheetWriter(CONFIG, str(tmp_path / "leads.csv"))


def test_webhook_payload_and_success(tmp_path, monkeypatch):
    writer = make_writer(tmp_path, monkeypatch)
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResp({"ok": True, "written": 1})

    monkeypatch.setattr(sheets_mod.requests, "post", fake_post)
    n = writer.upsert([Company(name="Acme Fire", domain="acmefire.com", first_name="Jane")])
    assert n == 1
    assert captured["url"].endswith("/exec")
    assert captured["json"]["secret"] == "s3cret"
    assert captured["json"]["key_column"] == "Company - Domain"
    row = captured["json"]["rows"][0]
    assert row["Company Name"] == "Acme Fire"
    assert row["Company - Domain"] == "acmefire.com"
    assert row["First Name"] == "Jane"


def test_webhook_error_raises(tmp_path, monkeypatch):
    writer = make_writer(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sheets_mod.requests, "post",
        lambda url, json=None, timeout=None: FakeResp({"ok": False, "error": "bad secret"}),
    )
    with pytest.raises(RuntimeError, match="bad secret"):
        writer.upsert([Company(name="Acme Fire", domain="acmefire.com")])
