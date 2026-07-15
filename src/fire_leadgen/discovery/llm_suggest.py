"""Method F from the research manual, automated: ask an LLM for
independent companies matching the current search topic, then VERIFY each
suggestion by finding its real website via web search before it enters
the pipeline (the manual warns AI output must always be double-checked -
here every name must resolve to a live site, and it still passes the
same PE screening as every other lead).

Requires ANTHROPIC_API_KEY; silently disabled otherwise.
"""

from __future__ import annotations

import logging
import os
import re

import requests

log = logging.getLogger("fire_leadgen.llm")

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("LLM_SUGGEST_MODEL", "claude-haiku-4-5-20251001")

PROMPT = (
    "Find independent {topic} companies. Make sure they are neither PE "
    "backed, nor acquired by other companies, and focus on family-owned "
    "businesses with a good online presence.\n\n"
    "List up to {count} real company names, one per line, with no "
    "numbering, no commentary, and no other text. If you are not "
    "confident real companies exist for this query, output nothing."
)


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def suggest_companies(topic: str, count: int = 15) -> list[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return []
    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": PROMPT.format(topic=topic, count=count),
                    }
                ],
            },
            timeout=60,
        )
        if resp.status_code != 200:
            log.warning("LLM suggestion call failed: %s %s", resp.status_code, resp.text[:200])
            return []
        blocks = resp.json().get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    except requests.RequestException as exc:
        log.warning("LLM suggestion call failed: %s", exc)
        return []
    names = parse_names(text)
    log.info("LLM suggested %d companies for %r", len(names), topic)
    return names


def parse_names(text: str) -> list[str]:
    """Clean LLM output into plausible company names."""
    names = []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-*•").strip()
        m = re.match(r"^\d{1,3}[.)]\s+(.*)", line)
        if m:
            line = m.group(1).strip()
        if not (3 <= len(line) <= 80):
            continue
        if line.endswith(":") or line.lower().startswith(("here", "note", "i ", "these")):
            continue
        names.append(line)
    return names[:25]
