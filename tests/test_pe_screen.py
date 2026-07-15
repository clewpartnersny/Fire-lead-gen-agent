import os

from fire_leadgen.screening.pe_screen import PeScreener

CONFIG = os.path.join(os.path.dirname(__file__), "..", "sectors", "fire-protection", "pe_firms.yaml")


def screener():
    return PeScreener(CONFIG)


def test_known_consolidator_by_domain():
    verdict = screener().screen("Some Branch", "pyebarkerfs.com", "we protect your business")
    assert verdict["pe_backed"] == "yes"
    assert verdict["independent"] == "no"


def test_known_consolidator_by_alias_in_text():
    verdict = screener().screen(
        "Acme Fire", "acmefire.com", "Acme Fire is now part of Pye-Barker Fire & Safety."
    )
    assert verdict["pe_backed"] == "yes"


def test_ownership_phrase_flags_review():
    verdict = screener().screen(
        "Acme Fire", "acmefire.com",
        "We are proud to be a portfolio company of Example Capital.",
    )
    assert verdict["pe_backed"] == "review"
    assert any("portfolio company" in e for e in verdict["evidence"])


def test_independent_family_owned():
    verdict = screener().screen(
        "Acme Fire", "acmefire.com",
        "Family owned and operated since 1985, serving the tri-state area.",
    )
    assert verdict["pe_backed"] == "no"
    assert verdict["independent"] == "yes"


def test_news_search_evidence():
    hits = [{
        "title": "Example Capital announces acquisition of Acme Fire",
        "snippet": "Acme Fire has been acquired by Example Capital",
        "url": "https://news.example.com/1",
    }]
    verdict = screener().screen(
        "Acme Fire", "acmefire.com", "welcome to acme fire", news_search_fn=lambda q: hits
    )
    assert verdict["pe_backed"] == "review"
    assert any("news:" in e for e in verdict["evidence"])
