"""Employee-count estimation from multiple weak signals, combined into a
size bucket with a transparent "basis" string so a human can judge it.
"""

from __future__ import annotations

import re

BUCKETS = ["1-10", "11-25", "26-50", "51-100", "101-250", "250+"]

# Phrases a company uses to state its own headcount on its website. These are
# a FREE, self-reported signal (we already crawl the site), more reliable than
# the heuristic. Each pattern must carry an employee/staff/team context so we
# never pick up "50 years", "500 customers", "24/7", etc.
_HEADCOUNT_PATTERNS = [
    re.compile(r"\bteam of (?:over |more than |nearly |about |around )?(\d{1,5})\b", re.I),
    re.compile(r"\bstaff of (?:over |more than |nearly |about |around )?(\d{1,5})\b", re.I),
    re.compile(r"\bemploys?\s+(?:over |more than |nearly |about |approximately |around )?(\d{1,5})\b", re.I),
    re.compile(r"\b(?:over|more than|nearly)\s+(\d{1,5})\s*(?:full[- ]time\s+)?"
               r"(?:employees|technicians|staff|professionals|team members)\b", re.I),
    re.compile(r"\b(\d{1,5})\s*\+?\s*(?:full[- ]time\s+)?"
               r"(?:employees|technicians|team members|staff members|professionals)\b", re.I),
    re.compile(r"\b(\d{1,5})[- ]person (?:team|crew|staff)\b", re.I),
]


def headcount_from_text(text: str) -> int | None:
    """Largest plausible employee count a company states on its own site.

    Returns an int (a confident, self-reported headcount) or None if the site
    makes no such claim. Values outside a sane range are ignored.
    """
    if not text:
        return None
    best: int | None = None
    for pat in _HEADCOUNT_PATTERNS:
        for m in pat.finditer(text):
            try:
                n = int(m.group(1))
            except (ValueError, IndexError):
                continue
            if 1 <= n <= 100000 and (best is None or n > best):
                best = n
    return best


def estimate_size(
    hunter_headcount: str = "",
    team_count: int = 0,
    locations: str = "",
    google_reviews: str = "",
    email_count: int = 0,
) -> tuple[str, str]:
    """Return (bucket, basis). Empty bucket when there's nothing to go on."""
    basis: list[str] = []

    # Hunter/company-data headcount is the strongest signal when present.
    if hunter_headcount:
        basis.append(f"Hunter headcount: {hunter_headcount}")
        bucket = _bucket_from_headcount(hunter_headcount)
        if bucket:
            return bucket, "; ".join(basis)

    score = 0
    if team_count:
        basis.append(f"{team_count} leadership/team members on site")
        score += min(team_count, 12)
    n_loc = _to_int(locations)
    if n_loc:
        basis.append(f"{n_loc} locations")
        score += n_loc * 8
    n_rev = _to_int(google_reviews)
    if n_rev:
        basis.append(f"{n_rev} Google reviews")
        score += min(n_rev // 15, 15)
    if email_count:
        basis.append(f"{email_count} emails found on domain")
        score += min(email_count, 10)

    if not basis:
        return "", ""

    if score <= 5:
        bucket = "1-10"
    elif score <= 12:
        bucket = "11-25"
    elif score <= 22:
        bucket = "26-50"
    elif score <= 35:
        bucket = "51-100"
    else:
        bucket = "101-250"
    return bucket, "; ".join(basis)


def _bucket_from_headcount(headcount: str) -> str:
    """Hunter returns ranges like '11-50' or '51-200'."""
    digits = "".join(ch if ch.isdigit() or ch == "-" else " " for ch in headcount).split()
    nums = []
    for token in digits:
        for part in token.split("-"):
            if part.isdigit():
                nums.append(int(part))
    if not nums:
        return ""
    mid = sum(nums[:2]) / len(nums[:2])
    for bucket in BUCKETS:
        hi = bucket.split("-")[-1].rstrip("+")
        if mid <= int(hi):
            return bucket
    return BUCKETS[-1]


def _to_int(value: str) -> int:
    try:
        return int(str(value).strip() or 0)
    except ValueError:
        return 0
