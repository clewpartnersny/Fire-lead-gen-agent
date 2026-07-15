import csv
import os

from fire_leadgen.models import Company
from fire_leadgen.output.sheets import SheetWriter

CONFIG = os.path.join(os.path.dirname(__file__), "..", "config", "sheet_columns.yaml")


def test_csv_fallback_roundtrip(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    out = tmp_path / "leads.csv"
    writer = SheetWriter(CONFIG, str(out))
    n = writer.upsert([
        Company(name="Acme Fire", website="https://acmefire.com", domain="acmefire.com",
                owner_name="Jane Doe", independent="yes"),
    ])
    assert n == 1
    with open(out) as fh:
        rows = list(csv.reader(fh))
    header, row = rows[0], rows[1]
    assert header[0] == "Company Name"
    assert row[header.index("Company Name")] == "Acme Fire"
    assert row[header.index("Owner Name")] == "Jane Doe"
    assert row[header.index("Independent")] == "yes"
