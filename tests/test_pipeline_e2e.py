"""Offline end-to-end test: discovery result -> extraction -> screening ->
PPP/revenue -> owner rules -> export, with the network layer stubbed out.
"""

import csv
import os

import fire_leadgen.pipeline as pipeline_mod
from fire_leadgen.db import Db
from fire_leadgen.enrichment import ppp
from fire_leadgen.output.sheets import SheetWriter
from fire_leadgen.pipeline import Pipeline
from fire_leadgen.screening.pe_screen import PeScreener

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

SITE_TEXT = """
Acme Fire Protection LLC - family owned and operated since 1987.
We provide commercial fire alarm installation, fire sprinkler inspection and
kitchen hood suppression for restaurants and office buildings across the
tri-state area. We also serve residential customers.
Call (203) 555-0142 or email info@acmefire.com
123 Main Street, Stamford, CT 06901
John Smith, Owner
"""

FAKE_CRAWL = {
    "domain": "acmefire.com",
    "website": "https://acmefire.com",
    "site_name": "Acme Fire Protection LLC",
    "text": SITE_TEXT,
    "pages_fetched": 3,
    "team": [("John Smith", "Owner")],
}


def make_config(tmp_path):
    return {
        "discovery": {"ignore_domains": [], "results_per_query": 5, "use_places": False},
        "pipeline": {
            "industry_label": "Fire Protection",
            "required_services_any": ["fire alarm", "fire sprinkler", "kitchen hood"],
            "export_pe_backed": False,
            "pe_news_search": False,
            "min_ppp_loan": 150000,
            "ppp_revenue_multiplier": 15.4,
            "min_est_revenue": 5000000,
        },
        "enrichment": {"hunter": False, "rocketreach": False, "verify_emails": False,
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


def seed_ppp(db, name="ACME FIRE PROTECTION LLC", amount=400000.0, jobs=32):
    ppp.ensure_schema(db.conn)
    db.conn.execute(
        "INSERT INTO ppp_loans VALUES(?,?,?,?,?,?)",
        (ppp.normalize_name(name), name, "STAMFORD", "CT", amount, jobs),
    )
    db.conn.commit()


def add_acme(pipe):
    return pipe._add_candidate(
        {"domain": "acmefire.com", "url": "https://acmefire.com",
         "title": "Acme Fire Protection LLC", "snippet": ""},
        source="web search: fire protection company Stamford CT",
    )


def test_full_pipeline_offline(tmp_path, monkeypatch):
    config, db, pipe = build_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline_mod.website, "crawl_site", lambda url, http: FAKE_CRAWL)
    seed_ppp(db)

    assert add_acme(pipe) == 1
    assert pipe.process_new(limit=10) == 1  # exports inline as it goes

    with open(config["storage"]["csv_fallback"]) as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    row = rows[0]
    # manual: legal entity forms stripped, bare domain, state abbreviation
    assert row["Company Name"] == "Acme Fire Protection"
    assert row["Company - Domain"] == "acmefire.com"
    assert row["City"] == "Stamford"
    assert row["State"] == "CT"
    assert row["MSA"] == "Bridgeport-Stamford-Norwalk"
    assert row["Industry"] == "Fire Protection"
    # commercial hints dominate -> single verdict, never "both"
    assert row["Customer Type"] == "Commercial"
    assert row["Year Founded"] == "1987"
    assert row["Lead Source"] == "Google"
    assert "Stamford, CT" in row["Locations"]
    assert row["Google Reviews"] == "N/A"  # no Serper key in tests
    # owner from team page; generic info@ must NOT be the contact email
    assert row["First Name"] == "John"
    assert row["Last Name"] == "Smith"
    assert row["Position"] == "Owner"
    assert row["Contact Email"] == ""
    assert "Needs Email" in row["Notes"]
    # PPP -> revenue (400k x 15.4) and employees from JobsReported
    assert row["PPP Loan"] == "400000"
    assert row["Est. Revenue"] == "6160000"
    assert row["Employees"] == "32"
    assert db.counts() == {"exported": 1}


def test_ppp_below_minimum_rejected(tmp_path, monkeypatch):
    config, db, pipe = build_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline_mod.website, "crawl_site", lambda url, http: FAKE_CRAWL)
    seed_ppp(db, amount=90000.0, jobs=8)

    add_acme(pipe)
    pipe.process_new(limit=10)
    assert pipe.export_ready() == 0
    assert db.counts() == {"rejected": 1}


def test_no_ppp_match_is_not_rejected(tmp_path, monkeypatch):
    config, db, pipe = build_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline_mod.website, "crawl_site", lambda url, http: FAKE_CRAWL)

    add_acme(pipe)
    pipe.process_new(limit=10)
    assert db.counts() == {"exported": 1}
    with open(config["storage"]["csv_fallback"]) as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["PPP Loan"] == "N/A"
    assert row["Est. Revenue"] == ""


def test_pe_backed_company_is_rejected(tmp_path, monkeypatch):
    config, db, pipe = build_pipeline(tmp_path, monkeypatch)
    pe_crawl = dict(FAKE_CRAWL, text=SITE_TEXT + "\nWe are now part of Pye-Barker Fire & Safety.")
    monkeypatch.setattr(pipeline_mod.website, "crawl_site", lambda url, http: pe_crawl)

    add_acme(pipe)
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
