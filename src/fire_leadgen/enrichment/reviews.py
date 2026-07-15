"""Google review count/rating for a specific company, via Serper's
/places endpoint (Google Maps data). Used to backfill the Google Reviews
column for leads discovered through web search rather than Maps, so the
column is always populated.
"""

from __future__ import annotations

import logging
import os
import re

from ..utils import HttpClient

log = logging.getLogger("fire_leadgen.reviews")

SERPER_PLACES_URL = "https://google.serper.dev/places"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def lookup_reviews(name: str, city: str, state: str, http: HttpClient) -> tuple[str, str, str]:
    """Return (rating, review_count, address) as strings; empties if unavailable.
    The address is the Google Maps listing address - used to backfill
    city/state when the company website didn't yield one."""
    key = os.environ.get("SERPER_API_KEY")
    if not key or not name:
        return "", "", ""
    query = " ".join(part for part in (name, city, state) if part)
    resp = http.post(
        SERPER_PLACES_URL,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query},
    )
    if resp is None:
        return "", "", ""
    wanted = _norm(name)
    for place in resp.json().get("places", []):
        found = _norm(place.get("title", ""))
        if not wanted or not found:
            continue
        if wanted == found or wanted in found or (
            found in wanted and len(found) >= 0.6 * len(wanted)
        ):
            rating = str(place.get("rating", "") or "")
            count = str(place.get("ratingCount", "") or "0")
            return rating, count, place.get("address", "") or ""
    return "", "", ""
