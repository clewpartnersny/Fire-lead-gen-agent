"""Hunter.io enrichment: domain search (emails + org metadata) and
email finder (personal email for a given name + domain).
API docs: https://hunter.io/api-documentation/v2
"""

from __future__ import annotations

import logging
import os

from ..utils import HttpClient

log = logging.getLogger("fire_leadgen.hunter")

BASE = "https://api.hunter.io/v2"


def _key() -> str:
    return os.environ.get("HUNTER_API_KEY", "")


def domain_search(domain: str, http: HttpClient) -> dict:
    """Return {emails: [...], organization, headcount, generic_email} (empty if no key)."""
    if not _key():
        return {}
    resp = http.get(
        f"{BASE}/domain-search",
        params={"domain": domain, "api_key": _key(), "limit": 10},
    )
    if resp is None:
        return {}
    data = resp.json().get("data", {}) or {}
    emails = []
    for e in data.get("emails", []):
        emails.append(
            {
                "value": e.get("value", ""),
                "first_name": e.get("first_name") or "",
                "last_name": e.get("last_name") or "",
                "position": e.get("position") or "",
                "confidence": e.get("confidence") or 0,
            }
        )
    generic = next(
        (e["value"] for e in emails if not e["first_name"]),
        emails[0]["value"] if emails else "",
    )
    return {
        "emails": emails,
        "organization": data.get("organization") or "",
        "headcount": data.get("headcount") or "",
        "generic_email": generic,
    }


def email_finder(domain: str, first_name: str, last_name: str, http: HttpClient) -> str:
    if not _key() or not (first_name and last_name):
        return ""
    resp = http.get(
        f"{BASE}/email-finder",
        params={
            "domain": domain,
            "first_name": first_name,
            "last_name": last_name,
            "api_key": _key(),
        },
    )
    if resp is None:
        return ""
    data = resp.json().get("data", {}) or {}
    if (data.get("score") or 0) >= 50:
        return data.get("email") or ""
    return ""
