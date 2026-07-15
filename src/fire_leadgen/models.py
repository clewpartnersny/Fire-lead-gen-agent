from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Company:
    """One lead. Field names match the `columns` values in sheet_columns.yaml."""

    name: str = ""
    website: str = ""
    domain: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    services: str = ""
    employee_estimate: str = ""
    size_basis: str = ""
    year_founded: str = ""
    locations: str = ""
    owner_name: str = ""
    owner_title: str = ""
    owner_email: str = ""
    owner_phone: str = ""
    owner_source: str = ""
    independent: str = ""       # "yes" / "no" / "review"
    pe_backed: str = ""         # "yes" / "no" / "review"
    pe_evidence: str = ""
    google_rating: str = ""
    google_reviews: str = ""
    linkedin_url: str = ""
    source: str = ""            # where the lead was discovered
    notes: str = ""
    first_seen: str = ""
    last_updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def fields(cls) -> list[str]:
        return list(cls().to_dict().keys())
