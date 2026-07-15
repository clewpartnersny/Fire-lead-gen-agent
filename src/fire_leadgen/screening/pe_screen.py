"""Independence screening: is this company PE-backed / owned by a
consolidator platform, or independent?

Three layers of evidence:
  1. Known-consolidator match (name/domain/alias from pe_firms.yaml)
  2. Ownership phrases on the company's own website
  3. Optional acquisition-news web search

Verdicts:  pe_backed = "yes" | "no" | "review"
"no" plus independence phrases -> independent = "yes"
"""

from __future__ import annotations

import logging
import re

import yaml

log = logging.getLogger("fire_leadgen.pe_screen")

ACQUISITION_NEWS_RE = re.compile(
    r"(acquir\w+|acquisition|private equity|portfolio company|merger|"
    r"has been purchased|buys|bought)",
    re.IGNORECASE,
)


class PeScreener:
    def __init__(self, pe_firms_path: str):
        with open(pe_firms_path) as fh:
            data = yaml.safe_load(fh) or {}
        self.consolidators = data.get("consolidators", [])
        self.ownership_phrases = [p.lower() for p in data.get("ownership_phrases", [])]
        self.independence_phrases = [
            p.lower() for p in data.get("independence_phrases", [])
        ]

    def screen(
        self,
        name: str,
        domain: str,
        site_text: str,
        news_search_fn=None,
    ) -> dict:
        """Return {pe_backed, independent, evidence}."""
        evidence: list[str] = []
        lower_text = (site_text or "").lower()
        lower_name = (name or "").lower()

        # 1. known consolidators ---------------------------------------
        for c in self.consolidators:
            if domain and domain in [d.lower() for d in c.get("domains", [])]:
                evidence.append(f"domain belongs to {c['name']} ({c.get('sponsor','')})")
            else:
                for alias in c.get("aliases", []):
                    alias = alias.lower()
                    if alias and (alias in lower_name or f" {alias}" in lower_text):
                        evidence.append(
                            f"matches consolidator '{c['name']}' via alias '{alias}'"
                        )
                        break
        if evidence:
            return {"pe_backed": "yes", "independent": "no", "evidence": evidence}

        # 2. ownership phrases on their own site -----------------------
        phrase_hits = []
        for phrase in self.ownership_phrases:
            if ".*" in phrase:
                if re.search(phrase, lower_text):
                    phrase_hits.append(phrase)
            elif phrase in lower_text:
                phrase_hits.append(phrase)
        if phrase_hits:
            evidence.append("site mentions: " + ", ".join(sorted(set(phrase_hits))[:5]))

        # 3. acquisition news search ------------------------------------
        # Search-term set from the research manual: Name + Acquired / Sale /
        # Private Equity / Parent Company / Pitchbook (collapsed into two
        # queries to conserve search quota).
        if news_search_fn and name:
            queries = [
                f'"{name}" (acquired OR acquisition OR "private equity")',
                f'"{name}" ("parent company" OR pitchbook OR sale)',
            ]
            for query in queries:
                try:
                    hits = news_search_fn(query)
                except Exception as exc:
                    log.debug("news search failed for %s: %s", name, exc)
                    continue
                found = False
                for h in hits[:10]:
                    blob = f"{h.get('title','')} {h.get('snippet','')}"
                    if lower_name and lower_name in blob.lower() and ACQUISITION_NEWS_RE.search(blob):
                        evidence.append(f"news: {h.get('title','')[:100]} ({h.get('url','')})")
                        found = True
                        break
                if found:
                    break

        independence_hits = [p for p in self.independence_phrases if p in lower_text]

        if evidence:
            # ownership language or acquisition news -> needs a human look
            return {
                "pe_backed": "review",
                "independent": "review",
                "evidence": evidence,
            }
        return {
            "pe_backed": "no",
            "independent": "yes",
            "evidence": [f"independence signal: {p}" for p in independence_hits[:3]]
            or ["no ownership/acquisition signals found"],
        }
