"""Offline tests for the live PPP web lookup (synthetic HTML fixtures)."""

import sqlite3

from fire_leadgen.enrichment import ppp, ppp_web

PROPUBLICA_SEARCH_HTML = """
<html><body><table>
<tr>
  <td><a href="/coronavirus/bailouts/loans/acme-fire-protection-llc-123">ACME FIRE PROTECTION LLC</a></td>
  <td>Stamford, CT</td><td>$325,000</td>
</tr>
<tr>
  <td><a href="/coronavirus/bailouts/loans/acme-fire-az-999">ACME FIRE PROTECTION LLC</a></td>
  <td>Phoenix, AZ</td><td>$99,000</td>
</tr>
</table></body></html>
"""

PROPUBLICA_DETAIL_HTML = """
<html><body>
<h1>ACME FIRE PROTECTION LLC</h1>
<p>Approved loan amount: $325,000</p>
<p>28 jobs reported</p>
</body></html>
"""


class FakeResp:
    def __init__(self, text, url):
        self.text = text
        self.url = url


USASPENDING_JSON = {
    "results": [
        {"Recipient Name": "ACME FIRE PROTECTION LLC", "Loan Value": 325000.0,
         "Place of Performance State Code": "CT"},
        {"Recipient Name": "ACME FIRE PROTECTION LLC", "Loan Value": 180000.0,
         "Place of Performance State Code": "CT"},
        {"Recipient Name": "ACME FIRE PROTECTION LLC", "Loan Value": 500000.0,
         "Place of Performance State Code": "AZ"},
        {"Recipient Name": "UNRELATED PLUMBING CO", "Loan Value": 900000.0,
         "Place of Performance State Code": "CT"},
    ]
}


class FakeJsonResp:
    def __init__(self, payload, url):
        self._payload = payload
        self.url = url

    def json(self):
        return self._payload


class FakeHttp:
    """Serves canned pages (HTML for get, JSON for post) by URL substring."""

    def __init__(self, pages, json_pages=None):
        self.pages = pages
        self.json_pages = json_pages or {}
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append(url)
        for fragment, html in self.pages.items():
            if fragment in url:
                return FakeResp(html, url)
        return None

    def post(self, url, **kwargs):
        self.requests.append(url)
        for fragment, payload in self.json_pages.items():
            if fragment in url:
                return FakeJsonResp(payload, url)
        return None


def test_usaspending_lookup_filters_state_and_name():
    http = FakeHttp({}, json_pages={"usaspending.gov": USASPENDING_JSON})
    hit = ppp_web.lookup_web("Acme Fire Protection", "CT", http)
    assert hit["amount"] == 325000.0  # largest CT draw; AZ and unrelated ignored
    assert hit["source"] == "USAspending"
    assert hit["matched_name"] == "ACME FIRE PROTECTION LLC"


def test_propublica_fallback_when_usaspending_empty():
    http = FakeHttp({
        "propublica.org/coronavirus/bailouts/search": PROPUBLICA_SEARCH_HTML,
        "bailouts/loans/acme-fire-protection-llc-123": PROPUBLICA_DETAIL_HTML,
    })
    hit = ppp_web.lookup_web("Acme Fire Protection", "CT", http)
    assert hit["amount"] == 325000.0
    assert hit["jobs"] == 28
    assert hit["source"] == "ProPublica"
    # the AZ row must not have been chosen
    assert not any("acme-fire-az-999" in r for r in http.requests)


def test_no_match_returns_empty():
    http = FakeHttp({"propublica.org/coronavirus/bailouts/search": PROPUBLICA_SEARCH_HTML})
    assert ppp_web.lookup_web("Totally Different Company", "CT", http) == {}


def test_unreachable_providers_return_empty():
    assert ppp_web.lookup_web("Acme Fire Protection", "CT", FakeHttp({})) == {}


def test_web_hit_and_miss_caching():
    conn = sqlite3.connect(":memory:")
    ppp.store(conn, "Acme Fire Protection", "Stamford", "CT", 325000.0, 28)
    hit = ppp.lookup(conn, "Acme Fire Protection", "CT")
    assert hit["amount"] == 325000.0

    assert not ppp.is_cached_miss(conn, "Unknown Fire Co", "CT")
    ppp.cache_miss(conn, "Unknown Fire Co", "CT")
    assert ppp.is_cached_miss(conn, "Unknown Fire Co", "CT")
