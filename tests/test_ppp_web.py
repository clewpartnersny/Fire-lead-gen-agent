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


class FakeHttp:
    """Serves canned pages by URL substring; records requests."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append(url)
        for fragment, html in self.pages.items():
            if fragment in url:
                return FakeResp(html, url)
        return None


def test_propublica_lookup_matches_state():
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
