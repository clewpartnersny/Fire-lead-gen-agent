"""Live PPP-loan lookup against public web databases - no CSV download
needed. Tries ProPublica's Coronavirus Bailouts database first, then
FederalPay's PPP search. Hits and misses are cached in the local DB (via
ppp.store / ppp.cache_miss) so each company is fetched at most once.

These are HTML pages, not APIs, so parsing is deliberately defensive:
any layout change degrades to "no match" rather than bad data.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..utils import HttpClient
from .ppp import normalize_name

log = logging.getLogger("fire_leadgen.ppp_web")

PROPUBLICA_SEARCH = "https://projects.propublica.org/coronavirus/bailouts/search"
FEDERALPAY_SEARCH = "https://www.federalpay.org/paycheck-protection-program/search"

AMOUNT_RE = re.compile(r"\$\s?([\d,]{4,})")
JOBS_RE = re.compile(r"([\d,]+)\s*jobs(?:\s+reported)?", re.IGNORECASE)


def lookup_web(name: str, state: str, http: HttpClient) -> dict:
    """Return {amount, jobs, matched_name, source} or {}."""
    for provider, label in ((_propublica, "ProPublica"), (_federalpay, "FederalPay")):
        try:
            hit = provider(name, state, http)
        except Exception as exc:
            log.debug("%s PPP lookup failed for %r: %s", label, name, exc)
            continue
        if hit:
            hit["source"] = label
            log.info(
                "PPP (%s): %s -> $%s / %s jobs",
                label, name, f"{hit['amount']:,.0f}", hit.get("jobs") or "?",
            )
            return hit
    return {}


def _names_match(wanted: str, found: str) -> bool:
    a, b = normalize_name(wanted), normalize_name(found)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _propublica(name: str, state: str, http: HttpClient) -> dict:
    resp = http.get(PROPUBLICA_SEARCH, params={"q": name})
    if resp is None:
        return {}
    soup = BeautifulSoup(resp.text, "lxml")
    state_u = (state or "").strip().upper()

    for link in soup.select('a[href*="/coronavirus/bailouts/loans/"]'):
        found_name = link.get_text(strip=True)
        if not _names_match(name, found_name):
            continue
        row = link.find_parent("tr")
        row_text = row.get_text(" ", strip=True) if row else found_name
        if state_u and not re.search(rf"\b{state_u}\b", row_text.upper()):
            continue
        return _read_detail(urljoin(resp.url, link["href"]), found_name, row_text, http)
    return {}


def _federalpay(name: str, state: str, http: HttpClient) -> dict:
    resp = http.get(FEDERALPAY_SEARCH, params={"q": name})
    if resp is None:
        return {}
    soup = BeautifulSoup(resp.text, "lxml")
    state_u = (state or "").strip().upper()

    for link in soup.select('a[href*="/paycheck-protection-program/"]'):
        if "/search" in link.get("href", ""):
            continue
        found_name = link.get_text(strip=True)
        if not _names_match(name, found_name):
            continue
        row = link.find_parent("tr")
        row_text = row.get_text(" ", strip=True) if row else found_name
        if state_u and not re.search(rf"\b{state_u}\b", row_text.upper()):
            continue
        return _read_detail(urljoin(resp.url, link["href"]), found_name, row_text, http)
    return {}


def _read_detail(detail_url: str, found_name: str, row_text: str, http: HttpClient) -> dict:
    """Amount/jobs from the loan detail page, falling back to the result row."""
    amount, jobs = _extract_amount_jobs(row_text)
    detail = http.get(detail_url)
    if detail is not None:
        text = BeautifulSoup(detail.text, "lxml").get_text(" ", strip=True)
        d_amount, d_jobs = _extract_amount_jobs(text)
        amount = d_amount or amount
        jobs = d_jobs or jobs
    if not amount:
        return {}
    return {"amount": amount, "jobs": jobs, "matched_name": found_name}


def _extract_amount_jobs(text: str) -> tuple[float, int]:
    amounts = [float(a.replace(",", "")) for a in AMOUNT_RE.findall(text or "")]
    amount = max(amounts) if amounts else 0.0
    jobs_m = JOBS_RE.search(text or "")
    jobs = int(jobs_m.group(1).replace(",", "")) if jobs_m else 0
    return amount, jobs
