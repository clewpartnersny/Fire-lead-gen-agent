"""Fetch a company's website (home + contact/about/team pages) and extract
structured facts: name, phone, email, address, services, founding year,
location count, and team members (for owner identification).
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..utils import (
    ADDRESS_RE,
    HttpClient,
    YEAR_RE,
    clean_city,
    first_email,
    normalize_domain,
    normalize_phone,
)

log = logging.getLogger("fire_leadgen.website")

# internal links worth following, by keyword in the path/anchor text
FOLLOW_HINTS = (
    "contact", "about", "team", "leadership", "our-story", "staff",
    "management", "who-we-are", "history", "locations", "service",
)
MAX_SUBPAGES = 6

US_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|"
    "MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
CITY_STATE_RE = re.compile(rf"([A-Z][A-Za-z .'\-]{{2,25}}),\s*({US_STATES})\b")

TITLE_WORDS = (
    "owner", "founder", "president", "ceo", "chief executive", "principal",
    "managing partner", "vice president", "general manager", "coo", "cfo",
)
# "John Smith, Owner" / "John Smith - President" / "John Smith | CEO"
NAME_TITLE_RE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*[,\-–|]\s*([A-Za-z /&]{3,40})"
)


def crawl_site(website: str, http: HttpClient) -> dict | None:
    """Return {text, html_title, site_name, pages, team, ...} or None if unreachable."""
    if not website.startswith("http"):
        website = "https://" + website
    resp = http.get(website)
    if resp is None and website.startswith("https://"):
        resp = http.get("http://" + website[len("https://"):])
    if resp is None:
        return None

    base_url = resp.url
    domain = normalize_domain(base_url)
    soup = BeautifulSoup(resp.text, "lxml")
    texts = [_page_text(soup)]
    team: list[tuple[str, str]] = []

    subpages = _pick_subpages(soup, base_url, domain)
    for sub_url in subpages:
        sub = http.get(sub_url)
        if sub is None:
            continue
        sub_soup = BeautifulSoup(sub.text, "lxml")
        texts.append(_page_text(sub_soup))
        if any(h in sub_url.lower() for h in ("team", "about", "leader", "staff", "management", "story", "who-we-are")):
            team.extend(_extract_team(sub_soup))
    team.extend(_extract_team(soup))

    full_text = "\n".join(texts)
    return {
        "domain": domain,
        "website": f"https://{domain}",
        "site_name": _site_name(soup, domain),
        "text": full_text,
        "pages_fetched": 1 + len(subpages),
        "team": _dedupe_team(team),
    }


def extract_facts(crawl: dict, service_keywords: list[str]) -> dict:
    """Pull structured fields out of crawled text."""
    text = crawl["text"]
    lower = text.lower()

    services = sorted({kw for kw in service_keywords if kw.lower() in lower})

    # addresses are often split across lines ("123 Main St\nStamford, CT
    # 06901"), so match against a newline-collapsed copy of the text
    flat = re.sub(r"[ \t]*\n[ \t]*", ", ", text)
    address = city = state = zipcode = ""
    m = ADDRESS_RE.search(flat)
    if m:
        address = m.group(0)
        city, state, zipcode = clean_city(m.group(1)), m.group(2), m.group(3)

    year = ""
    ym = YEAR_RE.search(text)
    if ym:
        year = ym.group(1)

    locations = ""
    lm = re.search(r"(\d{1,3})\+?\s+(?:locations|branches|offices)", lower)
    if lm:
        locations = lm.group(1)

    # distinct "City, ST" mentions -> office/coverage list
    offices: list[str] = []
    for cm in CITY_STATE_RE.finditer(text):
        office_city = clean_city(cm.group(1))
        if not office_city or len(office_city) < 3:
            continue
        tag = f"{office_city}, {cm.group(2)}"
        if tag not in offices:
            offices.append(tag)
        if len(offices) >= 8:
            break

    return {
        "office_locations": "; ".join(offices),
        "phone": normalize_phone(text),
        "email": first_email(text, crawl["domain"]),
        "address": address,
        "city": city,
        "state": state,
        "zip": zipcode,
        "services": ", ".join(services),
        "year_founded": year,
        "locations": locations,
    }


# ---------------------------------------------------------------------------

def _page_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"[ \t]+", " ", soup.get_text(separator="\n", strip=True))


def _site_name(soup: BeautifulSoup, domain: str) -> str:
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        # "Acme Fire Protection | Fire Alarms NYC" -> "Acme Fire Protection"
        return re.split(r"[|\-–:]", soup.title.string)[0].strip()
    return domain


def _pick_subpages(soup: BeautifulSoup, base_url: str, domain: str) -> list[str]:
    chosen: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if normalize_domain(href) != domain:
            continue
        path = urlparse(href).path.lower()
        anchor = a.get_text(strip=True).lower()
        if not any(h in path or h in anchor for h in FOLLOW_HINTS):
            continue
        clean = href.split("#")[0].rstrip("/")
        if clean in seen or not clean:
            continue
        seen.add(clean)
        chosen.append(clean)
        if len(chosen) >= MAX_SUBPAGES:
            break
    return chosen


def _extract_team(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Find (name, title) pairs where the title looks like a leadership role."""
    found: list[tuple[str, str]] = []
    text = _page_text(soup)
    for m in NAME_TITLE_RE.finditer(text):
        name, title = m.group(1).strip(), m.group(2).strip()
        if any(w in title.lower() for w in TITLE_WORDS):
            found.append((name, title))
    # also headings followed by a title line (common team-card markup)
    for h in soup.find_all(["h2", "h3", "h4", "h5"]):
        name = h.get_text(strip=True)
        if not re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z.]+){1,2}", name):
            continue
        sib = h.find_next(["p", "span", "h6", "div"])
        if sib:
            title = sib.get_text(strip=True)
            if 0 < len(title) < 40 and any(w in title.lower() for w in TITLE_WORDS):
                found.append((name, title))
    return found


def _dedupe_team(team: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out = []
    for name, title in team:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((name, title))
    return out
