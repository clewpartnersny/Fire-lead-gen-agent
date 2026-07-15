"""Google Places discovery — the most reliable source of verified
name/address/phone/website plus review counts (a useful size signal).
"""

from __future__ import annotations

import logging
import os

from ..utils import HttpClient

log = logging.getLogger("fire_leadgen.places")

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
DETAIL_FIELDS = (
    "name,formatted_address,formatted_phone_number,website,rating,user_ratings_total"
)


def places_search(keyword: str, region: str, http: HttpClient) -> list[dict]:
    """Return [{name, address, phone, website, rating, reviews}] or [] if no key."""
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        return []
    text_query = f"{keyword} in {region}" if region else keyword
    resp = http.get(TEXT_SEARCH_URL, params={"query": text_query, "key": key})
    if resp is None:
        return []
    payload = resp.json()
    if payload.get("status") not in ("OK", "ZERO_RESULTS"):
        log.warning("Places search error: %s", payload.get("status"))
        return []

    out = []
    for place in payload.get("results", []):
        place_id = place.get("place_id")
        if not place_id:
            continue
        details = http.get(
            DETAILS_URL,
            params={"place_id": place_id, "fields": DETAIL_FIELDS, "key": key},
        )
        if details is None:
            continue
        d = details.json().get("result", {})
        out.append(
            {
                "name": d.get("name", ""),
                "address": d.get("formatted_address", ""),
                "phone": d.get("formatted_phone_number", ""),
                "website": d.get("website", ""),
                "rating": str(d.get("rating", "") or ""),
                "reviews": str(d.get("user_ratings_total", "") or ""),
            }
        )
    return out
