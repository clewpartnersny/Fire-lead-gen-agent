# Fire Protection Lead-Gen Agent

A 24/7 agent that continuously discovers **independent (non-PE-backed) fire
protection & life safety companies** across the web — including fire alarm,
fire suppression, sprinkler, extinguisher and inspection businesses —
verifies their info, estimates their size, finds the **owner** and their
contact details (via Hunter.io + RocketReach), screens out private-equity /
consolidator-owned companies, and writes qualified leads into a
**Google Sheet**.

## How it works

```
 DISCOVERY                 EXTRACTION               SCREENING
 ─────────                 ──────────               ─────────
 web search (SerpAPI  ──►  crawl company site  ──►  known PE consolidators
   or DuckDuckGo)          (home/contact/about/     (Pye-Barker, APi, Summit,
 Google Places              team pages): phone,      Impact, Sciens, Marmic…)
 industry directories       email, address,         ownership phrases on site
                            services, year          acquisition news search
                            founded, team                 │
                                                          ▼
 GOOGLE SHEET              ENRICHMENT               independent? yes/no/review
 ────────────              ──────────
 upsert rows per      ◄──  owner via team page /
 sheet_columns.yaml        RocketReach / Hunter
 (CSV fallback)            owner email (Hunter
                           email-finder)
                           size estimate (headcount,
                           locations, reviews, team)
```

Everything found is stored in a local SQLite DB (`data/leads.sqlite3`) so the
agent never re-processes a company, and the query rotation pointer survives
restarts. Rejected companies are kept with the reject reason (e.g.
`PE-backed / consolidator`) for auditability.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env        # fill in your API keys (see below)

fire-leadgen once           # one discovery/process/export cycle
fire-leadgen run            # run 24/7 (Ctrl-C to stop)
fire-leadgen stats          # pipeline counts
fire-leadgen export         # re-push 'ready' leads to the sheet
```

With no API keys at all it still works: DuckDuckGo search + website crawling
+ CSV output (`out/leads.csv`). Keys unlock accuracy:

| Key | Service | What it adds |
|---|---|---|
| `SERPAPI_KEY` | serpapi.com | reliable high-volume Google results |
| `GOOGLE_PLACES_API_KEY` | Google Cloud | verified name/address/phone + review counts |
| `HUNTER_API_KEY` | hunter.io | company emails, headcount, owner email finder |
| `ROCKETREACH_API_KEY` | rocketreach.co | owner/decision-maker contact lookup |
| `GOOGLE_SHEET_ID` + `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Sheets | live sheet output |

### Google Sheet setup

1. Create a GCP service account, enable the Sheets API, download its JSON key
   as `service_account.json`.
2. Share your sheet with the service account's email address (Editor).
3. Put the sheet ID and worksheet name in `.env`.
4. **To match your sheet template**: edit `config/sheet_columns.yaml` —
   rename/reorder the headers there to mirror the template exactly. No code
   changes needed. Rows are de-duplicated by website domain.

## Running it 24/7

```bash
docker compose up -d --build     # restart: unless-stopped keeps it alive
docker compose logs -f           # watch it work
```

Deploy the same compose file on any small VPS (a $5 instance is plenty — the
agent is deliberately slow/polite). State persists in `./data`.

## Configuration

- **`config/config.yaml`** — search keywords, regions, query templates,
  service-qualification rules, pacing (politeness delays, batch sizes),
  ignore-list of directory/social domains, and optional industry directory
  pages to harvest (AFAA/NAFED member lists, state license rosters, …).
- **`config/pe_firms.yaml`** — the independence-screening knowledge base:
  known PE-backed consolidator platforms (name/sponsor/aliases/domains),
  ownership phrases, independence phrases. **Extend this as the research
  manual dictates and as new acquisitions happen.**
- **`config/sheet_columns.yaml`** — sheet template mapping (header → field).

### Research-manual rules (implemented)

The Clew research manual's rules are encoded as follows:

| Manual rule | Implementation |
|---|---|
| Sheet template columns (Company Name … Notes) | `sheet_columns.yaml` — matches Research_Template.xlsx exactly |
| Remove legal entity forms (LLC, Inc.) from names | `clean_company_name()` applied to every lead |
| Website as bare domain (example.com) | `Company - Domain` column uses the normalized domain |
| PPP loan ≥ $150k to qualify | `pipeline.min_ppp_loan` — rejects when a PPP match is below it |
| Revenue = PPP × 15.4 (fire protection multiplier) | `pipeline.ppp_revenue_multiplier`; digits only, `N/A` when no PPP |
| Employees from PPP "Jobs" column | PPP index `JobsReported` → `Employees` column |
| Revenue > $5M target | `pipeline.min_est_revenue` — flags in Notes (doesn't reject) |
| Ignore Google reviews for commercial-services sizing | reviews recorded but only used as a weak fallback signal |
| Owner = most senior (Owner/CEO/President) | `enrichment.owner_titles` priority order |
| NEVER upload generic emails (info@…) | generic inboxes are stripped from Contact Email |
| Prefer professional email over personal | RocketReach professional-type emails preferred |
| Verify emails before upload | Hunter email-verifier; invalid → dropped + "Needs Email" |
| "No Contact" / "Needs Email" statuses | written to Notes per manual Step 5G |
| Owner age (retirement signal) | RocketReach birth year when available; else manual step |
| Organize by MSA | `enrichment/msa.py` city/state → MSA, fallback "ST (Other)" |
| Acquisition checks (Name + Acquired/Sale/PE/Parent/Pitchbook) | PE screener news queries + consolidator list + site phrases |
| 1000+ reviews → call to confirm ownership | flagged in Notes |
| Company age 20+ / multiple locations are green flags | Year Founded + Locations columns populated from site |

### PPP loan data (recommended setup)

The manual's primary size signal is the PPP loan database. It's free,
public SBA FOIA data. One-time setup:

1. Download the loan CSVs from https://data.sba.gov/dataset/ppp-foia
   (the `public_150k_plus` file alone covers every loan ≥ $150k and is
   enough, since smaller loans are rejected anyway).
2. Index locally: `fire-leadgen ppp-import path/to/public_150k_plus_*.csv`

Every lead is then matched against the index automatically (largest draw
wins), filling PPP Loan, Est. Revenue and Employees with zero API cost.

## Independence verdicts

Each company gets `independent = yes / no / review`:

- **no** — matched a known consolidator (domain, name or alias).
- **review** — its own site uses ownership language ("portfolio company",
  "now part of…", "a subsidiary of…") or an acquisition headline was found;
  evidence is written to the *PE Evidence* column for a human decision.
- **yes** — no ownership signals; independence phrases ("family owned",
  "third generation", …) are recorded as supporting evidence.

## Size estimates

`Est. Employees` is a bucket (`1-10`, `11-25`, `26-50`, `51-100`, `101-250`,
`250+`) with the reasoning in *Size Basis* — Hunter headcount when available,
otherwise a heuristic over team-page size, location count, Google review
volume and email footprint. Treat it as a research starting point, not a fact.

## Tests

```bash
pip install pytest && pytest
```

## A note on scraping etiquette & accuracy

The agent rate-limits itself (one request every ~2s, small batches per
cycle), only reads public pages, and prefers official APIs (Places, Hunter,
RocketReach) over scraping wherever possible. LinkedIn is intentionally not
scraped — owner data comes from company sites and the RocketReach/Hunter
APIs. All extracted facts carry their source, and anything uncertain is
labeled `review` rather than guessed.
