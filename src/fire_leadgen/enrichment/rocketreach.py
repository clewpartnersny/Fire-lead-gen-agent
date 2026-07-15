"""RocketReach enrichment: find the owner/decision-maker at a company and
their contact info. API docs: https://rocketreach.co/api/v2/docs
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("fire_leadgen.rocketreach")

BASE = "https://api.rocketreach.co/api/v2"


def _headers() -> dict | None:
    key = os.environ.get("ROCKETREACH_API_KEY", "")
    if not key:
        return None
    return {"Api-Key": key, "Content-Type": "application/json"}


def find_owner(company_name: str, domain: str, owner_titles: list[str]) -> dict:
    """Search people at the company whose title matches owner_titles.

    Returns {name, title, email, phone, linkedin_url} or {}.
    """
    headers = _headers()
    if headers is None:
        return {}
    query: dict = {"current_employer": [company_name or domain]}
    if owner_titles:
        query["current_title"] = owner_titles[:6]
    try:
        resp = requests.post(
            f"{BASE}/person/search",
            headers=headers,
            json={"query": query, "page_size": 5},
            timeout=30,
        )
        if resp.status_code != 200:
            log.debug("rocketreach search %s: %s", resp.status_code, resp.text[:200])
            return {}
        profiles = resp.json().get("profiles", [])
    except requests.RequestException as exc:
        log.debug("rocketreach search failed: %s", exc)
        return {}

    profile = _best_profile(profiles, owner_titles)
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


def _best_profile(profiles: list[dict], owner_titles: list[str]) -> dict | None:
    def rank(p: dict) -> int:
        title = (p.get("current_title") or "").lower()
        for i, t in enumerate(owner_titles):
            if t in title:
                return i
        return len(owner_titles)

    profiles = sorted(profiles, key=rank)
    return profiles[0] if profiles else None


def _lookup(person_id, headers: dict) -> dict | None:
    """Reveal contact details for a profile (consumes a lookup credit)."""
    if not person_id:
        return None
    try:
        resp = requests.get(
            f"{BASE}/person/lookup",
            headers=headers,
            params={"id": person_id},
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            return None
        p = resp.json()
    except requests.RequestException:
        return None

    emails = p.get("emails") or []
    phones = p.get("phones") or []

    def _val(item):
        return item.get("email") or item.get("number") or "" if isinstance(item, dict) else str(item)

    # prefer a professional (company-domain) email over personal webmail,
    # per the research manual
    pro = [e for e in emails if isinstance(e, dict) and e.get("type") == "professional"]
    best_email = _val(pro[0]) if pro else (_val(emails[0]) if emails else "")

    return {
        "name": p.get("name", ""),
        "title": p.get("current_title", ""),
        "email": best_email,
        "phone": _val(phones[0]) if phones else "",
        "linkedin_url": p.get("linkedin_url", ""),
        "birth_year": p.get("birth_year") or "",
    }
