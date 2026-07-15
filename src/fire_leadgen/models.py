from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Company:
    """One lead. Field names match the `columns` values in sheet_columns.yaml.

    Field conventions follow the Clew research manual:
    - name: legal entity forms (LLC, Inc.) stripped
    - domain: bare registrable domain, e.g. example.com (no www, no path)
    - contact_email: the OWNER's direct email - never a generic inbox
    - ppp_loan / est_revenue: digits only, "N/A" when unavailable
    - state: two-letter abbreviation
    """

    # -- sheet template fields -----------------------------------------
    name: str = ""
    first_name: str = ""
    last_name: str = ""
    position: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    linkedin_url: str = ""
    owner_age: str = ""
    domain: str = ""
    industry: str = ""
    customer_type: str = ""
    city: str = ""
    state: str = ""
    msa: str = ""
    google_reviews: str = ""
    ppp_loan: str = ""
    est_revenue: str = ""
    employees: str = ""
    locations: str = ""
    office_locations: str = ""  # "City, ST; City, ST" list of offices
    lead_source: str = ""       # Google / Google Maps / Industry Directory / ...
    year_founded: str = ""
    notes: str = ""

    # -- internal / audit fields ----------------------------------------
    website: str = ""
    zip: str = ""
    address: str = ""
    phone: str = ""            # main company phone (from site / Places)
    email: str = ""            # generic company email (never uploaded as contact)
    services: str = ""
    google_rating: str = ""
    ppp_jobs: str = ""
    size_basis: str = ""
    owner_source: str = ""
    email_status: str = ""     # "" | "Needs Email" | "No Contact"
    independent: str = ""      # "yes" / "no" / "review"
    pe_backed: str = ""        # "yes" / "no" / "review"
    pe_evidence: str = ""
    source: str = ""           # lead source (search term, directory, ...)
    first_seen: str = ""
    last_updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def fields(cls) -> list[str]:
        return list(cls().to_dict().keys())
