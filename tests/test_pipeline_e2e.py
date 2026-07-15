"""Offline end-to-end test: discovery result -> extraction -> screening ->
size estimate -> export, with the network layer stubbed out.
"""

import csv
import os

import fire_leadgen.pipeline as pipeline_mod
from fire_leadgen.db import Db
from fire_leadgen.models import Company
from fire_leadgen.output.sheets import SheetWriter
from fire_leadgen.pipeline import Pipeline
from fire_leadgen.screening.pe_screen import PeScreener

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

SITE_TEXT = """
Acme Fire Protection - family owned and operated since 1987.
We provide fire alarm installation, fire sprinkler inspection and kitchen
hood suppression across the tri-state area.
Call (203) 555-0142 or email info@acmefire.com
123 Main Street, Stamford, CT 06901
John Smith, Owner
"""

FAKE_CRAWL = {
    "domain": "acmefire.com",
    "website": "https://acmefire.com",
    "site_name": "Acme Fire Protection",
    "text": SITE_TEXT,
    "pages_fetched": 3,
    "team": [("John Smith", "Owner")],
}


def make_config(tmp_path):
    return {
        "discovery": {"ignore_domains": [], "results_per_query": 5, "use_places": False},
        "pipeline": {
            "required_services_any": ["fire alarm", "fire sprinkler", "kitchen hood"],
            "export_pe_backed": False,
            "pe_news_search": False,
        },
        "enrichment": {"hunter": False, "rocketreach": False,
                       "owner_titles": ["owner", "president", "ceo"]},
        "scheduler": {"request_delay_seconds": 0},
        "storage": {"database": str(tmp_path / "db.sqlite3"),
                    "csv_fallback": str(tmp_path / "leads.csv")},
    }


def build_pipeline(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    config = make_config(tmp_path)
    db = Db(config["storage"]["database"])
    screener = PeScreener(os.path.join(CONFIG_DIR, "pe_firms.yaml"))
    writer = SheetWriter(
        os.path.join(CONFIG_DIR, "sheet_columns.yaml"), config["storage"]["csv_fallback"]
    )
    return config, db, Pipeline(config, db, screener, writer)


def test_full_pipeline_offline(tmp_path, monkeypatch):
    config, db, pipe = build_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline_mod.website, "crawl_site", lambda url, http: FAKE_CRAWL)

    assert pipe._add_candidate(
        {"domain": "acmefire.com", "url": "https://acmefire.com",
         "title": "Acme Fire Protection", "snippet": ""},
        source="test",
    ) == 1
    assert pipe.process_new(limit=10) == 1
    assert pipe.export_ready() == 1

    with open(config["storage"]["csv_fallback"]) as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    row = rows[0]
    assert row["Company Name"] == "Acme Fire Protection"
    assert row["Phone"] == "(203) 555-0142"
    assert row["Email"] == "info@acmefire.com"
    assert row["City"] == "Stamford"
    assert row["State"] == "CT"
    assert row["Zip"] == "06901"
    assert "fire alarm" in row["Services"]
    assert row["Year Founded"] == "1987"
    assert row["Owner Name"] == "John Smith"
    assert row["Owner Title"] == "Owner"
    assert row["Owner Source"] == "company website"
    assert row["Independent"] == "yes"
    assert row["Est. Employees"] != ""
    assert db.counts() == {"exported": 1}


def test_pe_backed_company_is_rejected(tmp_path, monkeypatch):
    config, db, pipe = build_pipeline(tmp_path, monkeypatch)
    pe_crawl = dict(FAKE_CRAWL, text=SITE_TEXT + "\nWe are now part of Pye-Barker Fire & Safety.")
    monkeypatch.setattr(pipeline_mod.website, "crawl_site", lambda url, http: pe_crawl)

    pipe._add_candidate(
        {"domain": "acmefire.com", "url": "https://acmefire.com", "title": "Acme", "snippet": ""},
        source="test",
    )
    pipe.process_new(limit=10)
    assert pipe.export_ready() == 0
    assert db.counts() == {"rejected": 1}


def test_unreachable_site_rejected(tmp_path, monkeypatch):
    config, db, pipe = build_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline_mod.website, "crawl_site", lambda url, http: None)
    pipe._add_candidate(
        {"domain": "deadsite.com", "url": "https://deadsite.com", "title": "Dead", "snippet": ""},
        source="test",
    )
    pipe.process_new(limit=10)
    assert db.counts() == {"rejected": 1}
