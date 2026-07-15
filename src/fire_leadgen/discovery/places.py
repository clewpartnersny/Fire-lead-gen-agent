"""Google Places discovery — the most reliable source of verified
name/address/phone/website plus review counts (a useful size signal).
"""

from __future__ import annotations

import logging
import os

from ..utils import HttpClient

log = logging.getLogger("fire_leadgen.places")

SERPER_PLACES_URL = "https://google.serper.dev/places"
TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"


def serper_places(query: str, key: str, http: HttpClient) -> list[dict]:
    """Google Maps results via Serper: name/address/phone/website + reviews."""
    resp = http.post(
        SERPER_PLACES_URL,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query},
    )
    if resp is None:
        return []
    out = []
    for p in resp.json().get("places", []):
        out.append(
            {
                "name": p.get("title", ""),
                "address": p.get("address", ""),
                "phone": p.get("phoneNumber", ""),
                "website": p.get("website", ""),
                "rating": str(p.get("rating", "") or ""),
                "reviews": str(p.get("ratingCount", "") or ""),
            }
        )
    return out
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
DETAIL_FIELDS = (
    "name,formatted_address,formatted_phone_number,website,rating,user_ratings_total"
)


def places_search(keyword: str, region: str, http: HttpClient) -> list[dict]:
    """Return [{name, address, phone, website, rating, reviews}].

    Prefers Serper's /places (Google Maps data, includes review counts,
    no GCP account needed); falls back to the official Places API when
    only GOOGLE_PLACES_API_KEY is set.
    """
    text_query = f"{keyword} in {region}" if region else keyword
    serper_key = os.environ.get("SERPER_API_KEY")
    if serper_key:
        return serper_places(text_query, serper_key, http)
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        return []
    resp = http.get(TEXT_SEARCH_URL, params={"query": text_query, "key": key})
    if resp is None:
        return []
    payload = resp.json()
    if payload.get("status") not in ("OK", "ZERO_RESULTS"):
        log.warning("Places search error: %s", payload.get("status"))
        return []

    out = []
    for place in payload.get("results", []):  # official Places API path
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
