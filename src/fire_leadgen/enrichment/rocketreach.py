"""RocketReach enrichment: find the owner/decision-maker at a company and
their contact info. API docs: https://rocketreach.co/api/v2/docs
"""

from __future__ import annotations

import logging
import os
import re
import time

import requests

log = logging.getLogger("fire_leadgen.rocketreach")

BASE = "https://api.rocketreach.co/api/v2"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _headers() -> dict | None:
    key = os.environ.get("ROCKETREACH_API_KEY", "")
    if not key:
        return None
    return {"Api-Key": key, "Content-Type": "application/json"}


def find_owner(company_name: str, domain: str, owner_titles: list[str]) -> dict:
    """Search people at the company whose title matches owner_titles.

    RocketReach's employer search is fuzzy (searching "Stamford Fire
    Protection" can return anyone at any "Fire Protection" worldwide), so
    every candidate profile must pass _employer_matches before we spend a
    lookup credit on it.

    Returns {name, title, email, phone, linkedin_url, birth_year} or {}.
    """
    headers = _headers()
    if headers is None:
        return {}
    # Strategy 1: exact-phrase employer, ALL employees, rank titles
    # client-side (the API's title filter returns 0 when combined with a
    # quoted employer). Strategy 2: fuzzy employer + server title filter.
    attempts = (
        {"current_employer": [f'"{company_name}"']},
        {"current_employer": [company_name or domain],
         "current_title": owner_titles[:6]} if owner_titles else None,
    )
    profile = None
    for query in filter(None, attempts):
        try:
            resp = requests.post(
                f"{BASE}/person/search",
                headers=headers,
                json={"query": query, "page_size": 25},
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                log.debug("rocketreach search %s: %s", resp.status_code, resp.text[:200])
                return {}
            profiles = resp.json().get("profiles", [])
        except requests.RequestException as exc:
            log.debug("rocketreach search failed: %s", exc)
            return {}
        profiles = [p for p in profiles if _employer_matches(p, company_name, domain)]
        profile = _best_profile(profiles, owner_titles)
        if profile:
            break
    if not profile:
        return {}
    return _lookup(profile.get("id"), headers) or {
        "name": profile.get("name", ""),
        "title": profile.get("current_title", ""),
        "email": "",
        "phone": "",
        "linkedin_url": profile.get("linkedin_url", ""),
        "birth_year": "",
    }


def _employer_matches(profile: dict, company_name: str, domain: str) -> bool:
    """Only accept US profiles whose employer really is this company."""
    country = (profile.get("country_code") or profile.get("country") or "").upper()
    if country and country not in ("US", "UNITED STATES"):
        return False
    prof_domain = (profile.get("current_employer_domain") or "").lower()
    if domain and prof_domain and prof_domain.endswith(domain.lower()):
        return True
    emp = _norm(profile.get("current_employer") or "")
    comp = _norm(company_name)
    if not emp or not comp:
        return False
    if emp == comp or comp in emp:
        return True
    # employer is a substring of our name ("Fire Protection" vs
    # "Stamford Fire Protection") only counts if it's most of the name
    return emp in comp and len(emp) >= 0.75 * len(comp)


def _best_profile(profiles: list[dict], owner_titles: list[str]) -> dict | None:
    """Highest-priority title match; someone with NO matching title never
    qualifies (we must not pick a dispatcher just because they came first)."""
    def rank(p: dict) -> int:
        title = (p.get("current_title") or "").lower()
        for i, t in enumerate(owner_titles):
            if t in title:
                return i
        return len(owner_titles)

    matching = [p for p in profiles if rank(p) < len(owner_titles)]
    matching.sort(key=rank)
    return matching[0] if matching else None


def _lookup(person_id, headers: dict) -> dict | None:
    """Reveal contact details for a profile (consumes a lookup credit)."""
    if not person_id:
        return None
    # Lookups are async on RocketReach's side (status: progress) - retry
    # a few times until phones/emails are populated or we give up.
    p: dict = {}
    for _attempt in range(4):
        try:
            resp = requests.get(
                f"{BASE}/person/lookup",
                headers=headers,
                params={"id": person_id},
                timeout=60,
            )
            if resp.status_code not in (200, 201):
                return None
            p = resp.json()
        except requests.RequestException:
            return None
        if p.get("status") != "progress" or p.get("phones") or p.get("emails"):
            break
        time.sleep(4)

    emails = p.get("emails") or []
    phones = p.get("phones") or []

    return {
        "name": p.get("name", ""),
        "title": p.get("current_title", ""),
        "email": _best_email(emails),
        "phone": _pick_phones(phones),
        "linkedin_url": p.get("linkedin_url", ""),
        "birth_year": p.get("birth_year") or "",
    }


def _val(item) -> str:
    if isinstance(item, dict):
        return item.get("email") or item.get("number") or ""
    return str(item)


def _pick_phones(items: list) -> str:
    """ALL of the owner's mobile/cell numbers (the manual: never the office
    line; upload the strong possibilities ranked most-probable first).
    RocketReach marks mobiles type=mobile and flags one as recommended."""
    mobiles = [
        it for it in items
        if isinstance(it, dict)
        and str(it.get("type", "")).lower() in ("mobile", "cell", "personal")
    ]
    mobiles.sort(key=lambda it: (not it.get("recommended"), it.get("validity") != "valid"))
    numbers = [_val(it) for it in mobiles if _val(it)]
    if not numbers and items:  # no typed mobiles - fall back to first number
        numbers = [_val(items[0])]
    return "; ".join(list(dict.fromkeys(numbers))[:4])  # manual: 3-4 max, ranked


def _best_email(emails: list) -> str:
    """Professional (company-domain) email over personal webmail, per the
    research manual."""
    pro = [e for e in emails if isinstance(e, dict) and e.get("type") == "professional"]
    return _val(pro[0]) if pro else (_val(emails[0]) if emails else "")
