"""Harvest company websites linked from industry directory / association
member pages (AFAA chapters, NAFED members, state licensing lists, ...)
configured in config.yaml under discovery.directory_pages.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..utils import HttpClient, normalize_domain

log = logging.getLogger("fire_leadgen.directories")


def harvest_directory(url: str, http: HttpClient, ignore_domains: set[str]) -> list[dict]:
    """Extract external company links from one directory page."""
    resp = http.get(url)
    if resp is None:
        return []
    page_domain = normalize_domain(url)
    soup = BeautifulSoup(resp.text, "lxml")
    seen: set[str] = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if not href.startswith("http"):
            continue
        domain = normalize_domain(href)
        if (
            not domain
            or domain == page_domain
            or domain in ignore_domains
            or domain in seen
        ):
            continue
        seen.add(domain)
        out.append(
            {
                "url": f"https://{domain}",
                "title": a.get_text(strip=True),
                "snippet": "",
                "domain": domain,
            }
        )
    log.info("Directory %s yielded %d external links", url, len(out))
    return out
