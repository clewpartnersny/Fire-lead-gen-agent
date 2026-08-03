"""Web-search discovery: turns keyword x region combinations into search
queries and yields candidate company websites.

Uses SerpAPI (Google) when SERPAPI_KEY is set, otherwise falls back to
DuckDuckGo via the duckduckgo_search package.
"""

from __future__ import annotations

import itertools
import logging
import os

from ..utils import HttpClient, normalize_domain

log = logging.getLogger("fire_leadgen.search")


def build_queries(discovery_cfg: dict) -> list[str]:
    """All keyword x region x template combinations, in a stable order."""
    queries = []
    for keyword, region in itertools.product(
        discovery_cfg.get("keywords", []), discovery_cfg.get("regions", [])
    ):
        for template in discovery_cfg.get("query_templates", ["{keyword} {region}"]):
            queries.append(template.format(keyword=keyword, region=region))
    return queries


def web_search(query: str, max_results: int, http: HttpClient) -> list[dict]:
    """Return [{url, title, snippet}] for one query."""
    serper_key = os.environ.get("SERPER_API_KEY")
    if serper_key:
        results = _serper_search(query, max_results, serper_key, http)
        if results:
            return results
    serpapi_key = os.environ.get("SERPAPI_KEY")
    if serpapi_key:
        return _serpapi_search(query, max_results, serpapi_key, http)
    return _ddg_search(query, max_results)


def _serper_search(query: str, max_results: int, key: str, http: HttpClient) -> list[dict]:
    resp = http.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "num": min(max_results, 20)},
    )
    if resp is None:
        return []
    return [
        {
            "url": o.get("link", ""),
            "title": o.get("title", ""),
            "snippet": o.get("snippet", ""),
        }
        for o in resp.json().get("organic", [])[:max_results]
    ]


def _serpapi_search(query: str, max_results: int, key: str, http: HttpClient) -> list[dict]:
    resp = http.get(
        "https://serpapi.com/search.json",
        params={"engine": "google", "q": query, "num": max_results, "api_key": key},
    )
    if resp is None:
        return []
    results = []
    for item in resp.json().get("organic_results", [])[:max_results]:
        results.append(
            {
                "url": item.get("link", ""),
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
            }
        )
    return results


# Hard wall-clock cap for a single DuckDuckGo query. The ddgs library fans
# out across many engines (yandex, yahoo, mojeek, brave, ...) and its
# primp-based HTTP layer has been observed to hang indefinitely on a stalled
# connection through the proxy, which would freeze the whole sector thread.
# We run the call on a worker thread and abandon it past this deadline so the
# scheduler loop always makes progress.
_DDG_TIMEOUT = 45


def _ddg_search_raw(query: str, max_results: int) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        try:  # older package name, pre-2025 rename
            from duckduckgo_search import DDGS  # type: ignore
        except ImportError:
            log.error("ddgs not installed and no SERPAPI_KEY set")
            return []
    try:
        with DDGS(timeout=_DDG_TIMEOUT) as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
    except TypeError:
        # older ddgs signatures don't accept timeout=
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
    return [
        {"url": h.get("href", ""), "title": h.get("title", ""), "snippet": h.get("body", "")}
        for h in hits
    ]


def _ddg_search(query: str, max_results: int) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_ddg_search_raw, query, max_results)
        try:
            return future.result(timeout=_DDG_TIMEOUT + 15)
        except FutureTimeout:
            log.warning("DuckDuckGo search timed out for %r after %ds", query, _DDG_TIMEOUT + 15)
            return []
        except Exception as exc:
            log.warning("DuckDuckGo search failed for %r: %s", query, exc)
            return []


def filter_candidates(results: list[dict], ignore_domains: set[str]) -> list[dict]:
    """Drop directories/social/etc. and dedupe by registrable domain."""
    seen: set[str] = set()
    out = []
    for r in results:
        domain = normalize_domain(r.get("url", ""))
        if not domain or domain in seen or domain in ignore_domains:
            continue
        seen.add(domain)
        out.append({**r, "domain": domain})
    return out
