"""The processing pipeline: discovery -> extraction -> qualification ->
PE screening -> enrichment -> export. The Scheduler (scheduler.py) calls
run_cycle() forever for 24/7 operation.
"""

from __future__ import annotations

import logging
import time

from .db import Db
from .discovery import directories, llm_suggest, places, search
from .enrichment import hunter, msa, owners, ppp, ppp_web, reviews, size
from .extraction import website
from .extraction.website import CITY_STATE_RE
from .models import Company
from .output.sheets import SheetWriter
from .screening.pe_screen import PeScreener
from .utils import (
    ADDRESS_RE,
    HttpClient,
    clean_city,
    clean_company_name,
    normalize_domain,
    split_person_name,
)

log = logging.getLogger("fire_leadgen.pipeline")

RESIDENTIAL_HINTS = ("residential", "homeowner", "home owner", "your home", "houses", "apartment")
COMMERCIAL_HINTS = (
    "commercial", "industrial", "facilities", "businesses", "restaurants",
    "warehouses", "office buildings", "institutional", "municipal", "retail",
)


def _mix_counts(site_text: str, res_terms=None, com_terms=None) -> tuple[int, int]:
    """(residential_hits, commercial_hits) counted in the site copy.

    Term lists default to the module hint constants; a sector can pass its own
    (via config) so niche vocabulary - HOA, multifamily, vacation rental - is
    scored as residential and office/retail phrases as commercial.
    """
    lower = site_text.lower()
    res = sum(lower.count(h.lower()) for h in (res_terms or RESIDENTIAL_HINTS))
    com = sum(lower.count(h.lower()) for h in (com_terms or COMMERCIAL_HINTS))
    return res, com


def _customer_type(site_text: str) -> str:
    """Single verdict - whichever customer base dominates the site copy."""
    res, com = _mix_counts(site_text)
    if not res and not com:
        return ""
    return "Residential" if res > com else "Commercial"


def _lead_source(source: str) -> str:
    s = (source or "").lower()
    if s.startswith("web search"):
        return "Google"
    if "places" in s:
        return "Google Maps"
    if s.startswith("directory"):
        return "Industry Directory"
    if s.startswith("ai suggestion"):
        return "AI Suggestion"
    return source[:40]


def _employee_lower_bound(value) -> int | None:
    """Confident lower bound of an employee estimate, or None if unknown.

    Accepts an exact count ('45'), a size bucket ('26-50', '250+'), or ''.
    Returns the smallest number the estimate could represent so a caller can
    enforce a strict '>= N employees' gate: '45'->45, '26-50'->26, '11-25'->11,
    '250+'->250, ''->None. A bucket therefore only clears a floor of 20 from
    the 26-50 band up; '11-25' (lower bound 11) does not.
    """
    s = str(value or "").strip().replace("+", "")
    if not s:
        return None
    if "-" in s:
        s = s.split("-")[0]
    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits) if digits else None


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

        # Method F (research manual): AI-suggested companies, each verified
        # by resolving a real website through search before entering the DB.
        if disc.get("use_llm_suggestions") and llm_suggest.enabled() and queries:
            topic = queries[0]
            names = llm_suggest.suggest_companies(
                topic, disc.get("llm_suggestions_per_cycle", 10)
            )
            for name in names:
                results = search.web_search(f'"{name}" website', 5, self.http)
                for cand in search.filter_candidates(results, self.ignore_domains):
                    if self.db.has_company(cand["domain"]):
                        break
                    added += self._add_candidate(
                        cand, source=f"AI suggestion (verified): {topic}"
                    )
                    break
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
            m = ADDRESS_RE.search(company.address)
            if m:
                company.city, company.state, company.zip = (
                    clean_city(m.group(1)), m.group(2), m.group(3),
                )
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
            # flush to the sheet as we go so rows appear within a minute
            # of qualifying instead of at the end of a 30+ minute cycle
            self.export_ready()
        return processed

    def _process_one(self, company: Company) -> None:
        pcfg = self.cfg["pipeline"]
        ecfg = self.cfg["enrichment"]
        notes: list[str] = []

        # ---- extraction ------------------------------------------------
        crawl = website.crawl_site(company.website, self.http)
        if crawl is None:
            self.db.save_company(company, "rejected", "website unreachable")
            return
        company.domain = crawl["domain"]
        company.website = crawl["website"]
        company.name = clean_company_name(crawl["site_name"] or company.name)

        facts = website.extract_facts(crawl, pcfg.get("required_services_any", []))
        for field in ("phone", "email", "address", "city", "state", "zip"):
            if not getattr(company, field):
                setattr(company, field, facts[field])
        company.services = facts["services"]
        company.year_founded = facts["year_founded"]
        company.locations = facts["locations"]
        company.office_locations = facts.get("office_locations", "")
        n_offices = len([o for o in company.office_locations.split(";") if o.strip()])
        if not company.locations and n_offices > 1:
            company.locations = str(n_offices)
        company.lead_source = _lead_source(company.source)

        # ---- qualification ----------------------------------------------
        required = pcfg.get("required_services_any", [])
        n_matches = len([s for s in company.services.split(",") if s.strip()])
        min_matches = pcfg.get("min_service_matches", 2) if required else 0
        if required and n_matches < min_matches:
            self.db.save_company(
                company, "rejected",
                f"only {n_matches} fire/life-safety service signal(s) "
                f"(need {min_matches})",
            )
            return

        company.industry = pcfg.get("industry_label", "Fire Protection")
        company.customer_type = _customer_type(crawl["text"])

        # ---- business-mix screen (optional, per-sector) ------------------
        # For sectors like Property Management whose guide targets RESIDENTIAL,
        # pure-play firms only. Hard-reject a firm that reads clearly COMMERCIAL
        # (office/retail) with NO residential signal at all; soft-flag a mixed
        # book (so a human confirms residential is the revenue majority) and any
        # development / brokerage / construction exposure (development-heavy and
        # non-pure-play firms are not tops). Inert unless business_mix_screen is
        # set, so other sectors are unaffected.
        if pcfg.get("business_mix_screen"):
            res_terms = pcfg.get("residential_terms") or None
            com_terms = pcfg.get("commercial_terms") or None
            res_hits, com_hits = _mix_counts(crawl["text"], res_terms, com_terms)
            if com_hits and not res_hits:
                self.db.save_company(
                    company, "rejected",
                    f"commercial/office-retail only, no residential signal "
                    f"(commercial hits={com_hits})",
                )
                return
            if com_hits and res_hits:
                notes.append(
                    f"VERIFY business mix: commercial exposure "
                    f"(residential={res_hits} vs commercial={com_hits}) - "
                    f"confirm residential is the revenue majority"
                )
            lower_text = crawl["text"].lower()
            dilution = sorted(
                t for t in pcfg.get("dilution_terms", []) if t.lower() in lower_text
            )
            if dilution:
                notes.append(
                    "VERIFY pure-play: non-management exposure ("
                    + ", ".join(dilution)
                    + ") - development-heavy / brokerage firms are not tops"
                )

        # Google Reviews must always be populated: leads found via Maps
        # already carry it; backfill everything else via Serper /places
        # (which also returns the listing address - a location fallback).
        maps_address = ""
        if not company.google_reviews:
            rating, count, maps_address = reviews.lookup_reviews(
                company.name, company.city, company.state, self.http
            )
            company.google_rating = company.google_rating or rating
            company.google_reviews = count
        if not company.google_reviews:
            company.google_reviews = "N/A"

        # City/State/MSA must always be populated. Fallback chain:
        # site address -> Google Maps listing -> office list -> search region.
        if (not company.city or not company.state) and maps_address:
            m = ADDRESS_RE.search(maps_address) or CITY_STATE_RE.search(maps_address)
            if m:
                company.city = company.city or clean_city(m.group(1))
                company.state = company.state or m.group(2)
        if (not company.city or not company.state) and company.office_locations:
            first = company.office_locations.split(";")[0].strip()
            if "," in first:
                c, st = first.rsplit(",", 1)
                company.city = company.city or c.strip()
                company.state = company.state or st.strip()
        if not company.state:
            company.state = msa.region_to_state(company.source)
        company.msa = msa.assign_msa(company.city, company.state)

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
        if company.pe_backed == "review":
            notes.append(f"VERIFY OWNERSHIP - {company.pe_evidence}")

        # ---- PPP loan -> revenue estimate (manual Step 4) ----------------
        # local index first; then live web lookup (ProPublica/FederalPay),
        # cached either way so each company is fetched at most once
        ppp_hit = ppp.lookup(self.db.conn, company.name, company.state)
        if (
            not ppp_hit
            and ecfg.get("ppp_web", True)
            and not ppp.is_cached_miss(self.db.conn, company.name, company.state)
        ):
            web_hit = ppp_web.lookup_web(company.name, company.state, self.http)
            if web_hit.get("amount"):
                ppp.store(
                    self.db.conn, company.name, company.city, company.state,
                    web_hit["amount"], web_hit.get("jobs", 0),
                )
                ppp_hit = web_hit
                notes.append(f"PPP via {web_hit.get('source', 'web')}")
            else:
                ppp.cache_miss(self.db.conn, company.name, company.state)
        if ppp_hit:
            amount = ppp_hit["amount"]
            min_ppp = pcfg.get("min_ppp_loan", 150_000)
            if amount and min_ppp and amount < min_ppp:
                # kept (not rejected) - just flagged for the sourcing team
                notes.append(f"PPP ${amount:,.0f} below ${min_ppp:,.0f} threshold")
            company.ppp_loan = str(int(amount)) if amount else "N/A"
            company.ppp_jobs = str(ppp_hit["jobs"] or "")
            # sectors without a known PPP multiplier set it null -> the
            # loan/jobs still export, revenue stays blank
            multiplier = pcfg.get("ppp_revenue_multiplier")
            if amount and multiplier:
                est = int(amount * multiplier)
                company.est_revenue = str(est)
                min_rev = pcfg.get("min_est_revenue", 5_000_000)
                if min_rev and est < min_rev:
                    notes.append(f"est revenue ${est:,} below ${min_rev:,} target")
        else:
            company.ppp_loan = "N/A"

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
        company.first_name, company.last_name = split_person_name(owner["name"])
        company.position = owner["title"]
        company.contact_email = owner["email"]
        company.contact_phone = owner["phone"]
        company.owner_source = owner["source"]
        company.linkedin_url = owner.get("linkedin_url", "")
        if owner.get("birth_year"):
            try:
                company.owner_age = str(int(time.strftime("%Y")) - int(owner["birth_year"]))
            except ValueError:
                pass

        # manual Step 5G: email-status labels for the sourcing team
        if not owner["name"]:
            company.email_status = "No Contact"
        elif not company.contact_email:
            company.email_status = "Needs Email"
        elif ecfg.get("verify_emails") and ecfg.get("hunter"):
            status = hunter.verify_email(company.contact_email, self.http)
            if status:
                notes.append(f"email {status} (Hunter verifier)")
                if status == "invalid":
                    company.contact_email = ""
                    company.email_status = "Needs Email"
        if company.email_status:
            notes.append(company.email_status)

        # ---- employees: combine all FREE online size signals -------------
        # Priority: SBA-PPP JobsReported (gov, exact) > headcount the company
        # states on its OWN crawled website (e.g. "team of 35", "employs 40")
        # > Hunter headcount + on-site heuristic (team page, locations,
        # reviews, email footprint). No paid/login-walled source (e.g.
        # LinkedIn) is used.
        site_headcount = size.headcount_from_text(crawl.get("text", ""))
        if company.ppp_jobs:
            company.employees = company.ppp_jobs
            company.size_basis = "PPP JobsReported"
        elif site_headcount:
            company.employees = str(site_headcount)
            company.size_basis = "website-stated headcount"
        else:
            bucket, basis = size.estimate_size(
                hunter_headcount=str(hunter_data.get("headcount", "")),
                team_count=len(crawl["team"]),
                locations=company.locations,
                google_reviews=company.google_reviews,
                email_count=len(hunter_data.get("emails", [])),
            )
            company.employees = bucket
            company.size_basis = basis
        if company.size_basis:
            notes.append(f"size basis: {company.size_basis}")

        # ---- minimum-size gate (research manual: >= N employees) ---------
        # Strict: reject unless we are confident the company meets the floor,
        # i.e. the confident LOWER bound of its size estimate is >= min.
        # Unknown / possibly-below-floor estimates are rejected.
        min_emp = pcfg.get("min_employees", 0)
        if min_emp:
            low = _employee_lower_bound(company.employees)
            if low is None or low < min_emp:
                self.db.save_company(
                    company, "rejected",
                    f"under {min_emp} employees or size undetermined "
                    f"(estimate: {company.employees or 'unknown'}, "
                    f"basis: {company.size_basis or 'none'})",
                )
                return

        # manual Step 3D: very large review counts need an ownership call
        try:
            if int(company.google_reviews or 0) >= 1000:
                notes.append("1000+ Google reviews - call to confirm still founder/family owned")
        except ValueError:
            pass

        if company.source:
            notes.append(f"lead source: {company.source}")
        company.notes = " | ".join(notes)[:1000]

        # Locations column carries the NUMBER of locations; the city list
        # stays internal (office_locations). At least 1 once we know
        # where the company is.
        if not company.locations and company.office_locations:
            company.locations = str(len([o for o in company.office_locations.split(";") if o.strip()]))
        if not company.locations and (company.city or company.address):
            company.locations = "1"

        self.db.save_company(company, "ready")
        log.info(
            "Qualified: %s (%s) owner=%s %s rev=%s independent=%s",
            company.name, company.domain,
            f"{company.first_name} {company.last_name}".strip() or "?",
            company.email_status or "ok", company.est_revenue or "?",
            company.independent,
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_ready(self) -> int:
        ready = self.db.get_companies("ready", limit=500)
        if not ready:
            return 0
        try:
            written = self.writer.upsert(ready)
        except Exception as exc:
            log.warning(
                "Sheet export failed (%s) - %d leads stay queued and will "
                "be retried next cycle", exc, len(ready),
            )
            return 0
        for company in ready:
            self.db.save_company(company, "exported")
        log.info("Exported %d leads to the sheet", written)
        return written
