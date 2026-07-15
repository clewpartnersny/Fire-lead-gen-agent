from __future__ import annotations

import logging
import os
import re
import time

import requests
import tldextract

log = logging.getLogger("fire_leadgen")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(
    r"(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)"
)
# "123 Main St, Springfield, IL 62704" style
ADDRESS_RE = re.compile(
    r"\d{1,6}\s+[\w.\- ]{3,40}?,?\s+([A-Za-z .'\-]{2,30}),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?"
)
YEAR_RE = re.compile(
    r"(?:since|est\.?|established(?:\s+in)?|founded(?:\s+in)?|serving[\w\s,]{0,40}since)\s+(19\d{2}|20[0-2]\d)",
    re.IGNORECASE,
)


class HttpClient:
    """Shared requests session with a global politeness delay and per-host memory."""

    def __init__(self, delay_seconds: float = 2.0, timeout: int = 20):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        ca = os.environ.get("REQUESTS_CA_BUNDLE")
        if ca:
            self.session.verify = ca
        self.delay = delay_seconds
        self.timeout = timeout
        self._last_request = 0.0

    def get(self, url: str, **kwargs) -> requests.Response | None:
        wait = self.delay - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()
        try:
            resp = self.session.get(url, timeout=self.timeout, **kwargs)
            if resp.status_code >= 400:
                log.debug("GET %s -> %s", url, resp.status_code)
                return None
            return resp
        except requests.RequestException as exc:
            log.debug("GET %s failed: %s", url, exc)
            return None


def normalize_domain(url_or_domain: str) -> str:
    """Return the registrable domain (example.com) for a URL or hostname."""
    if not url_or_domain:
        return ""
    ext = tldextract.extract(url_or_domain.strip().lower())
    if not ext.domain or not ext.suffix:
        return ""
    return f"{ext.domain}.{ext.suffix}"


def normalize_phone(raw: str) -> str:
    m = PHONE_RE.search(raw or "")
    if not m:
        return ""
    return f"({m.group(1)}) {m.group(2)}-{m.group(3)}"


def first_email(text: str, domain: str = "") -> str:
    """Prefer an email on the company's own domain; skip junk inboxes."""
    candidates = EMAIL_RE.findall(text or "")
    junk = ("example.", "sentry.", "wixpress", "godaddy", ".png", ".jpg", ".webp")
    candidates = [c for c in candidates if not any(j in c.lower() for j in junk)]
    if domain:
        own = [c for c in candidates if c.lower().endswith("@" + domain)]
        if own:
            return own[0]
    return candidates[0] if candidates else ""


def now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("filelock").setLevel(logging.WARNING)
