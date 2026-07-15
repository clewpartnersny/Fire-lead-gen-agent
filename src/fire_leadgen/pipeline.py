"""The processing pipeline: discovery -> extraction -> qualification ->
PE screening -> enrichment -> export. The Scheduler (scheduler.py) calls
run_cycle() forever for 24/7 operation.
"""

from __future__ import annotations

import logging

from .db import Db
from .discovery import directories, places, search
from .enrichment import hunter, owners, size
from .extraction import website
from .models import Company
from .output.sheets import SheetWriter
from .screening.pe_screen import PeScreener
from .utils import HttpClient, normalize_domain

log = logging.getLogger("fire_leadgen.pipeline")


class Pipeline:
    def __init__(self, config: dict, db: Db, screener: PeScreener, writer: SheetWriter):
        self.cfg = config
        self.db = db
        self.screener = screener
        self.writer = writer
        self.http = HttpClient(
            delay_seconds=config["scheduler"].get("request_delay_seconds", 2)
        )
        self.ignore_domains = set(config["discovery"].get("ignore_domains", []))
        # never re-discover known consolidator platforms
        for c in screener.consolidators:
            self.ignore_domains.update(d.lower() for d in c.get("domains", []))

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover(self, queries: list[str]) -> int:
        added = 0
        disc = self.cfg["discovery"]
        for query in queries:
            log.info("Searching: %s", query)
            results = search.web_search(query, disc.get("results_per_query", 20), self.http)
            for cand in search.filter_candidates(results, self.ignore_domains):
                added += self._add_candidate(cand, source=f"web search: {query}")

        if disc.get("use_places"):
            for query in queries[:3]:  # places is billed per request; sample the batch
                keyword_region = query
                for place in places.places_search(keyword_region, "", self.http):
                    domain = normalize_domain(place.get("website", ""))
                    if not domain or domain in self.ignore_domains:
                        continue
                    added += self._add_candidate(
                        {
                            "domain": domain,
                            "url": place["website"],
                            "title": place["name"],
                            "snippet": "",
                            "places": place,
                        },
                        source="google places",
                    )

        for entry in disc.get("directory_pages") or []:
            url = entry["url"] if isinstance(entry, dict) else entry
            if not self.db.mark_url_seen(f"directory:{url}"):
                continue  # each directory page is harvested once
            for cand in directories.harvest_directory(url, self.http, self.ignore_domains):
                added += self._add_candidate(cand, source=f"directory: {url}")
        return added

    def _add_candidate(self, cand: dict, source: str) -> int:
        domain = cand["domain"]
        if self.db.has_company(domain):
            return 0
        company = Company(
            name=cand.get("title", ""),
            website=f"https://{domain}",
            domain=domain,
            source=source,
        )
        place = cand.get("places") or {}
        if place:
            company.name = place.get("name") or company.name
            company.address = place.get("address", "")
            company.phone = place.get("phone", "")
            company.google_rating = place.get("rating", "")
            company.google_reviews = place.get("reviews", "")
        return 1 if self.db.add_company(company) else 0

    # ------------------------------------------------------------------
    # Processing (extraction -> screening -> enrichment -> ready)
    # ------------------------------------------------------------------
    def process_new(self, limit: int) -> int:
        processed = 0
        for company in self.db.get_companies("new", limit):
            try:
                self._process_one(company)
            except Exception:
                log.exception("Failed processing %s", company.domain)
                self.db.save_company(company, "error", "unhandled exception")
            processed += 1
        return processed

    def _process_one(self, company: Company) -> None:
        pcfg = self.cfg["pipeline"]
        ecfg = self.cfg["enrichment"]

        # ---- extraction ------------------------------------------------
        crawl = website.crawl_site(company.website, self.http)
        if crawl is None:
            self.db.save_company(company, "rejected", "website unreachable")
            return
        company.domain = crawl["domain"]
        company.website = crawl["website"]
        company.name = crawl["site_name"] or company.name

        facts = website.extract_facts(crawl, pcfg.get("required_services_any", []))
        for field in ("phone", "email", "address", "city", "state", "zip"):
            if not getattr(company, field):
                setattr(company, field, facts[field])
        company.services = facts["services"]
        company.year_founded = facts["year_founded"]
        company.locations = facts["locations"]

        # ---- qualification ----------------------------------------------
        required = pcfg.get("required_services_any", [])
        if required and not company.services:
            self.db.save_company(company, "rejected", "no fire/life-safety services found")
            return

        # ---- PE / independence screening --------------------------------
        news_fn = None
        if pcfg.get("pe_news_search"):
            news_fn = lambda q: search.web_search(q, 10, self.http)  # noqa: E731
        verdict = self.screener.screen(company.name, company.domain, crawl["text"], news_fn)
        company.pe_backed = verdict["pe_backed"]
        company.independent = verdict["independent"]
        company.pe_evidence = "; ".join(verdict["evidence"])[:500]

        if company.pe_backed == "yes" and not pcfg.get("export_pe_backed"):
            self.db.save_company(company, "rejected", "PE-backed / consolidator")
            return

        # ---- enrichment --------------------------------------------------
        hunter_data = hunter.domain_search(company.domain, self.http) if ecfg.get("hunter") else {}
        if hunter_data:
            company.email = company.email or hunter_data.get("generic_email", "")

        owner = owners.find_owner(
            company.name,
            company.domain,
            crawl["team"],
            hunter_data,
            [t.lower() for t in ecfg.get("owner_titles", [])],
            self.http,
            use_rocketreach=bool(ecfg.get("rocketreach")),
            use_hunter=bool(ecfg.get("hunter")),
        )
        company.owner_name = owner["name"]
        company.owner_title = owner["title"]
        company.owner_email = owner["email"]
        company.owner_phone = owner["phone"]
        company.owner_source = owner["source"]
        company.linkedin_url = owner.get("linkedin_url", "")

        bucket, basis = size.estimate_size(
            hunter_headcount=str(hunter_data.get("headcount", "")),
            team_count=len(crawl["team"]),
            locations=company.locations,
            google_reviews=company.google_reviews,
            email_count=len(hunter_data.get("emails", [])),
        )
        company.employee_estimate = bucket
        company.size_basis = basis

        self.db.save_company(company, "ready")
        log.info(
            "Qualified: %s (%s) owner=%s size=%s independent=%s",
            company.name, company.domain, company.owner_name or "?",
            company.employee_estimate or "?", company.independent,
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_ready(self) -> int:
        ready = self.db.get_companies("ready", limit=500)
        if not ready:
            return 0
        written = self.writer.upsert(ready)
        for company in ready:
            self.db.save_company(company, "exported")
        log.info("Exported %d leads to the sheet", written)
        return written
