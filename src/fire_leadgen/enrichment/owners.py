"""Owner identification, in priority order:
  1. Team/leadership pages on the company's own website
  2. RocketReach person search (title = owner/president/CEO/...)
  3. Hunter domain-search results whose position matches an owner title
Then fill in the owner's email via Hunter email-finder if still missing.
"""

from __future__ import annotations

import logging

from ..utils import HttpClient
from . import hunter, rocketreach

log = logging.getLogger("fire_leadgen.owners")


def find_owner(
    company_name: str,
    domain: str,
    team: list[tuple[str, str]],
    hunter_data: dict,
    owner_titles: list[str],
    http: HttpClient,
    use_rocketreach: bool = True,
    use_hunter: bool = True,
) -> dict:
    """Return {name, title, email, phone, source, linkedin_url} (fields may be empty)."""
    owner = {"name": "", "title": "", "email": "", "phone": "", "source": "", "linkedin_url": ""}

    # 1. website team page --------------------------------------------
    match = _pick_by_title(
        [{"name": n, "title": t} for n, t in team], owner_titles
    )
    if match:
        owner.update(name=match["name"], title=match["title"], source="company website")

    # 2. RocketReach ----------------------------------------------------
    if use_rocketreach and not owner["name"]:
        rr = rocketreach.find_owner(company_name, domain, owner_titles)
        if rr.get("name"):
            owner.update(
                name=rr["name"],
                title=rr.get("title", ""),
                email=rr.get("email", ""),
                phone=rr.get("phone", ""),
                linkedin_url=rr.get("linkedin_url", ""),
                source="RocketReach",
            )

    # 3. Hunter positions ----------------------------------------------
    if not owner["name"]:
        contacts = [
            {
                "name": f"{e['first_name']} {e['last_name']}".strip(),
                "title": e.get("position", ""),
                "email": e.get("value", ""),
            }
            for e in hunter_data.get("emails", [])
            if e.get("first_name")
        ]
        match = _pick_by_title(contacts, owner_titles)
        if match:
            owner.update(
                name=match["name"],
                title=match["title"],
                email=match.get("email", ""),
                source="Hunter.io",
            )

    # email fill-in ------------------------------------------------------
    if owner["name"] and not owner["email"] and use_hunter:
        parts = owner["name"].split()
        if len(parts) >= 2:
            email = hunter.email_finder(domain, parts[0], parts[-1], http)
            if email:
                owner["email"] = email
                owner["source"] += " + Hunter email-finder"

    # last resort: RocketReach contact details for a website-found owner
    if use_rocketreach and owner["name"] and not owner["email"] and owner["source"] == "company website":
        rr = rocketreach.find_owner(company_name, domain, [owner["title"].lower()] if owner["title"] else owner_titles)
        if rr.get("name", "").lower() == owner["name"].lower():
            owner["email"] = rr.get("email", "")
            owner["phone"] = owner["phone"] or rr.get("phone", "")
            owner["linkedin_url"] = rr.get("linkedin_url", "")
            owner["source"] += " + RocketReach"

    return owner


def _pick_by_title(people: list[dict], owner_titles: list[str]) -> dict | None:
    for wanted in owner_titles:
        for person in people:
            if wanted in (person.get("title") or "").lower():
                return person
    return None
