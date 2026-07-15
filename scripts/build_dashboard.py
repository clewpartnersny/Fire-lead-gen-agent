#!/usr/bin/env python3
"""Build the research-team dashboard (out/dashboard.html).

Reads every sectors/*/config.yaml + pe_firms.yaml plus each sector's
SQLite database and bakes a self-contained HTML page: an org view of the
head of research and all sector agents, click-through to each agent's
full configuration, funnel stats, and buyer screen list.

Run:  python scripts/build_dashboard.py
"""

from __future__ import annotations

import collections
import glob
import html
import json
import os
import sqlite3
import subprocess
import sys
import time

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def env_file() -> dict:
    values = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def sector_stats(db_path: str) -> dict:
    out = {"statuses": {}, "reject_reasons": [], "top_states": []}
    if not os.path.exists(db_path):
        return out
    conn = sqlite3.connect(db_path)
    try:
        out["statuses"] = dict(
            conn.execute("SELECT status, COUNT(*) FROM companies GROUP BY status")
        )
        out["reject_reasons"] = [
            [r or "", n] for r, n in conn.execute(
                "SELECT reject_reason, COUNT(*) FROM companies WHERE status='rejected' "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
            )
        ]
        states = collections.Counter()
        for (data,) in conn.execute("SELECT data FROM companies"):
            st = json.loads(data).get("state")
            if st:
                states[st] += 1
        out["top_states"] = [[s, n] for s, n in states.most_common(6)]
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return out


def collect() -> dict:
    envs = env_file()
    sectors = []
    for cfg_path in sorted(glob.glob(os.path.join(ROOT, "sectors", "*", "config.yaml"))):
        slug = os.path.basename(os.path.dirname(cfg_path))
        cfg = yaml.safe_load(open(cfg_path))
        pe = yaml.safe_load(open(os.path.join(os.path.dirname(cfg_path), "pe_firms.yaml")))
        stats = sector_stats(os.path.join(ROOT, cfg["storage"]["database"]))
        st = stats["statuses"]
        sectors.append({
            "slug": slug,
            "persona": cfg.get("persona", ""),
            "name": cfg.get("sector", slug),
            "enabled": bool(cfg.get("enabled", True)),
            "worksheet": (cfg.get("output") or {}).get("worksheet", ""),
            "industry_label": cfg["pipeline"].get("industry_label", ""),
            "multiplier": cfg["pipeline"].get("ppp_revenue_multiplier"),
            "min_ppp": cfg["pipeline"].get("min_ppp_loan"),
            "min_rev": cfg["pipeline"].get("min_est_revenue"),
            "min_service_matches": cfg["pipeline"].get("min_service_matches", 2),
            "keywords": cfg["discovery"].get("keywords", []),
            "templates": len(cfg["discovery"].get("query_templates", [])),
            "regions": cfg["discovery"].get("regions", []),
            "directories": [
                (d.get("note") or d.get("url")) if isinstance(d, dict) else d
                for d in (cfg["discovery"].get("directory_pages") or [])
            ],
            "required": cfg["pipeline"].get("required_services_any", []),
            "owner_titles": cfg["enrichment"].get("owner_titles", []),
            "consolidators": [
                {"name": c.get("name", ""), "sponsor": c.get("sponsor", "")}
                for c in pe.get("consolidators", [])
            ],
            "exported": st.get("exported", 0),
            "queue": st.get("new", 0) + st.get("ready", 0),
            "rejected": st.get("rejected", 0) + st.get("error", 0),
            "reject_reasons": stats["reject_reasons"],
            "top_states": stats["top_states"],
        })
    # fire protection first, then the rest alphabetically
    sectors.sort(key=lambda s: (s["slug"] != "fire-protection", s["name"]))

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        commit = "?"

    apis = [
        ("Serper (Google search + Maps)", bool(envs.get("SERPER_API_KEY"))),
        ("Hunter.io (emails)", bool(envs.get("HUNTER_API_KEY"))),
        ("RocketReach (owners)", bool(envs.get("ROCKETREACH_API_KEY"))),
        ("Sheet webhook", bool(envs.get("SHEETS_WEBHOOK_URL"))),
        ("AI suggestions (Anthropic)", bool(envs.get("ANTHROPIC_API_KEY"))),
    ]
    sheet_id = envs.get("GOOGLE_SHEET_ID", "")
    return {
        "generated": time.strftime("%b %d, %Y %H:%M UTC", time.gmtime()),
        "commit": commit,
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else "",
        "apis": [{"name": n, "ok": ok} for n, ok in apis],
        "sectors": sectors,
        "totals": {
            "exported": sum(s["exported"] for s in sectors),
            "queue": sum(s["queue"] for s in sectors),
            "rejected": sum(s["rejected"] for s in sectors),
            "live": sum(1 for s in sectors if s["enabled"]),
            "count": len(sectors),
        },
    }


TEMPLATE = """<title>Clew Research Desk</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{
  --paper:#F5F4F1; --surface:#FFFFFF; --ink:#23262A; --muted:#6A7076;
  --line:#E4E2DC; --accent:#E85D04; --accent-ink:#B34700;
  --ok:#2F9E44; --queue:#2B6CB0; --bad:#B23A3A; --staged:#8A6D1C;
  --staged-bg:#F6ECD3; --pill-live:#DFF2E3; --scrim:rgba(24,22,18,.45);
}
@media (prefers-color-scheme: dark){:root{
  --paper:#17191C; --surface:#1F2226; --ink:#E9E7E2; --muted:#9BA0A6;
  --line:#2E3237; --accent:#FF7A1A; --accent-ink:#FF9A4D;
  --ok:#3FAE55; --queue:#4C8DFF; --bad:#E36868; --staged:#E0B25A;
  --staged-bg:#332B18; --pill-live:#1D3A25; --scrim:rgba(0,0,0,.6);
}}
:root[data-theme="dark"]{
  --paper:#17191C; --surface:#1F2226; --ink:#E9E7E2; --muted:#9BA0A6;
  --line:#2E3237; --accent:#FF7A1A; --accent-ink:#FF9A4D;
  --ok:#3FAE55; --queue:#4C8DFF; --bad:#E36868; --staged:#E0B25A;
  --staged-bg:#332B18; --pill-live:#1D3A25; --scrim:rgba(0,0,0,.6);
}
:root[data-theme="light"]{
  --paper:#F5F4F1; --surface:#FFFFFF; --ink:#23262A; --muted:#6A7076;
  --line:#E4E2DC; --accent:#E85D04; --accent-ink:#B34700;
  --ok:#2F9E44; --queue:#2B6CB0; --bad:#B23A3A; --staged:#8A6D1C;
  --staged-bg:#F6ECD3; --pill-live:#DFF2E3; --scrim:rgba(24,22,18,.45);
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums;}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px;}
header.top{display:flex;justify-content:space-between;align-items:baseline;
  flex-wrap:wrap;gap:8px;border-bottom:3px solid var(--ink);padding-bottom:14px;}
.wordmark{font-weight:800;font-size:22px;letter-spacing:-.02em;}
.wordmark .amp{color:var(--accent);}
.stamp{color:var(--muted);font-size:12.5px;}
.eyebrow{text-transform:uppercase;letter-spacing:.09em;font-size:11.5px;
  font-weight:700;color:var(--muted);}
/* KPI row */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:10px;margin:20px 0 30px;}
.kpi{background:var(--surface);border:1px solid var(--line);padding:14px 16px;}
.kpi .n{font-size:30px;font-weight:800;letter-spacing:-.02em;line-height:1.1;}
.kpi .l{color:var(--muted);font-size:12.5px;margin-top:2px;}
.kpi.hot .n{color:var(--accent-ink);}
/* Head node */
.head-card{background:var(--surface);border:1px solid var(--line);
  border-left:5px solid var(--accent);padding:18px 20px;}
.head-card h2{margin:2px 0 6px;font-size:18px;font-weight:800;letter-spacing:-.01em;}
.head-card p{margin:0 0 12px;color:var(--muted);max-width:62ch;}
.chips{display:flex;flex-wrap:wrap;gap:6px;}
.chip{font-size:12px;border:1px solid var(--line);padding:3px 9px;border-radius:2px;
  background:var(--paper);white-space:nowrap;}
.chip .dot{display:inline-block;width:7px;height:7px;border-radius:50%;
  margin-right:5px;vertical-align:1px;}
.dot.ok{background:var(--ok);} .dot.off{background:var(--bad);}
.head-links{margin-top:12px;font-size:13px;}
.head-links a{color:var(--accent-ink);font-weight:600;}
/* connectors */
.stem{width:2px;height:22px;background:var(--line);margin:0 auto;}
.bus{height:2px;background:var(--line);margin:0 24px;}
/* avatars */
.avatar{width:46px;height:46px;border-radius:50%;flex:none;
  display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:16px;color:#fff;letter-spacing:.02em;
  background:var(--av,#888);position:relative;}
.avatar.lg{width:56px;height:56px;font-size:19px;}
.avatar .st{position:absolute;right:-1px;bottom:-1px;width:12px;height:12px;
  border-radius:50%;border:2.5px solid var(--surface);}
.avatar .st.on{background:var(--ok);} .avatar .st.off{background:var(--staged);}
.who{display:flex;align-items:center;gap:12px;min-width:0;}
.who .nm{font-weight:800;font-size:16px;letter-spacing:-.01em;line-height:1.2;}
.who .rl{color:var(--muted);font-size:12.5px;}
/* support staff row */
.staff-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));
  gap:12px;margin-top:12px;}
.staff{background:var(--surface);border:1px solid var(--line);padding:14px;}
.staff .who{margin-bottom:8px;}
.s-when{color:var(--accent-ink);font-size:11.5px;font-weight:700;}
.s-what{color:var(--muted);font-size:12.5px;line-height:1.5;}
/* agent grid */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:14px;margin-top:22px;}
.agent{position:relative;text-align:left;background:var(--surface);
  border:1px solid var(--line);padding:16px 16px 14px;cursor:pointer;
  color:inherit;font:inherit;display:flex;flex-direction:column;gap:10px;
  transition:border-color .15s, transform .15s;}
.agent:hover{border-color:var(--accent);}
.agent:focus-visible{outline:3px solid var(--accent);outline-offset:2px;}
.agent .row{display:flex;justify-content:space-between;align-items:center;gap:8px;}
.agent h3{margin:0;font-size:16.5px;font-weight:800;letter-spacing:-.01em;}
.pill{font-size:10.5px;font-weight:700;text-transform:uppercase;
  letter-spacing:.08em;padding:3px 8px;border-radius:2px;white-space:nowrap;}
.pill.live{background:var(--pill-live);color:var(--ok);}
.pill.live .blink{display:inline-block;width:6px;height:6px;border-radius:50%;
  background:var(--ok);margin-right:5px;animation:pulse 2s infinite;vertical-align:1px;}
@keyframes pulse{50%{opacity:.25}}
@media (prefers-reduced-motion: reduce){.pill .blink{animation:none}}
.pill.staged{background:var(--staged-bg);color:var(--staged);}
.agent .meta{color:var(--muted);font-size:12.5px;}
.strip{display:flex;height:12px;gap:2px;}
.strip span{min-width:3px;}
.strip .s-ok{background:var(--ok);} .strip .s-q{background:var(--queue);}
.strip .s-bad{background:var(--bad);}
.strip.empty{background:var(--paper);border:1px dashed var(--line);}
.legend{display:flex;gap:14px;font-size:12px;color:var(--muted);flex-wrap:wrap;}
.legend b{color:var(--ink);font-weight:700;}
.legend .dot{width:8px;height:8px;border-radius:2px;display:inline-block;margin-right:5px;}
.open-hint{color:var(--accent-ink);font-size:12.5px;font-weight:600;}
/* drawer */
.scrim{position:fixed;inset:0;background:var(--scrim);opacity:0;
  pointer-events:none;transition:opacity .2s;z-index:8;}
.scrim.on{opacity:1;pointer-events:auto;}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(520px,100vw);
  background:var(--paper);border-left:1px solid var(--line);z-index:9;
  transform:translateX(102%);transition:transform .22s ease;overflow-y:auto;
  padding:22px 22px 60px;}
@media (prefers-reduced-motion: reduce){.drawer,.scrim{transition:none}}
.drawer.on{transform:none;box-shadow:-18px 0 40px rgba(0,0,0,.18);}
.drawer .close{position:sticky;top:0;float:right;background:var(--surface);
  border:1px solid var(--line);color:var(--ink);font-size:14px;font-weight:700;
  padding:6px 12px;cursor:pointer;}
.drawer .close:focus-visible{outline:3px solid var(--accent);}
.drawer h2{margin:6px 0 2px;font-size:22px;font-weight:800;letter-spacing:-.02em;}
.drawer .sub{color:var(--muted);margin-bottom:18px;font-size:13px;}
.sect{background:var(--surface);border:1px solid var(--line);
  padding:14px 16px;margin-bottom:12px;}
.sect h4{margin:0 0 10px;font-size:11.5px;text-transform:uppercase;
  letter-spacing:.09em;color:var(--muted);}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;font-size:13.5px;}
.kv dt{color:var(--muted);} .kv dd{margin:0;font-weight:600;}
.tags{display:flex;flex-wrap:wrap;gap:5px;}
.tag{font-size:12px;background:var(--paper);border:1px solid var(--line);
  padding:2px 8px;border-radius:2px;}
table.buyers{width:100%;border-collapse:collapse;font-size:12.5px;}
table.buyers td{padding:4px 8px 4px 0;border-bottom:1px solid var(--line);
  vertical-align:top;}
table.buyers td:last-child{color:var(--muted);}
.hint{border:1px dashed var(--line);background:var(--paper);padding:10px 12px;
  font-size:12.5px;display:flex;justify-content:space-between;gap:10px;
  align-items:center;margin-top:8px;}
.hint em{font-style:normal;}
.hint button{border:1px solid var(--accent);background:none;color:var(--accent-ink);
  font-size:11.5px;font-weight:700;padding:3px 9px;cursor:pointer;white-space:nowrap;}
.hint button:focus-visible{outline:2px solid var(--accent);}
.note{color:var(--muted);font-size:12px;margin-top:10px;}
h2.section{font-size:13px;text-transform:uppercase;letter-spacing:.09em;
  color:var(--muted);margin:34px 0 0;}
</style>

<div class="wrap">
  <header class="top">
    <div class="wordmark">CLEW <span class="amp">/</span> RESEARCH DESK</div>
    <div class="stamp mono">generated __GENERATED__ · build __COMMIT__</div>
  </header>

  <div class="kpis" id="kpis"></div>

  <div class="eyebrow">Head of research</div>
  <div class="head-card" style="margin-top:8px">
    <div class="who" style="margin-bottom:10px">
      <div class="avatar lg" style="--av:#B34700">C<span class="st on"></span></div>
      <div><div class="nm" style="font-size:18px">Claude</div>
        <div class="rl">Head of Research — this chat session</div></div>
    </div>
    <p>Holds the research manual, tunes every analyst, screens judgment
    calls, and supervises the support staff. Change anything by texting
    the chat.</p>
    <div class="chips" id="apis"></div>
    <div class="head-links" id="headlinks"></div>
  </div>
  <div class="stem"></div><div class="bus"></div>

  <h2 class="section">Support staff — automated routines</h2>
  <div class="staff-grid">
    <div class="staff">
      <div class="who"><div class="avatar" style="--av:#5B6472">WO<span class="st on"></span></div>
        <div><div class="nm">Walt Okonkwo</div><div class="rl">Operations — Watchdog</div></div></div>
      <div class="s-when mono">hourly</div>
      <div class="s-what">Keeps every analyst running, restores the environment
        after outages, snapshots databases, escalates quota problems.</div>
    </div>
    <div class="staff">
      <div class="who"><div class="avatar" style="--av:#4A6FA5">TR<span class="st on"></span></div>
        <div><div class="nm">Tess Romano</div><div class="rl">Performance Coach — Trainer</div></div></div>
      <div class="s-when mono">daily · 9:00 ET</div>
      <div class="s-what">Refines each analyst from outcomes: search-yield tuning,
        ownership verification, junk-domain learning, and your edits in
        the sheet. Safe changes auto-applied; the rest proposed to you.</div>
    </div>
    <div class="staff">
      <div class="who"><div class="avatar" style="--av:#7A5EA0">DM<span class="st on"></span></div>
        <div><div class="nm">Dee Marsh</div><div class="rl">Market Intelligence — Deal Watch</div></div></div>
      <div class="s-when mono">daily · 8:30 ET</div>
      <div class="s-what">Sweeps each sector's M&amp;A news; flags acquired
        companies already in the sheet, updates buyer screens, sends the
        morning digest.</div>
    </div>
  </div>
  <div class="stem"></div><div class="bus"></div>

  <h2 class="section">Sector agents — click one to inspect</h2>
  <div class="grid" id="grid"></div>
  <div class="legend" style="margin-top:14px">
    <span><span class="dot" style="background:var(--ok)"></span>in the sheet</span>
    <span><span class="dot" style="background:var(--queue)"></span>in queue</span>
    <span><span class="dot" style="background:var(--bad)"></span>screened out</span>
  </div>
</div>

<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-label="Agent configuration"></aside>

<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (s,el=document)=>el.querySelector(s);
const esc = s => String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const money = v => v==null?'—':'$'+Number(v).toLocaleString();

// KPI row
$('#kpis').innerHTML = [
  ['In the sheet', D.totals.exported, 'hot'],
  ['In queue', D.totals.queue, ''],
  ['Screened out', D.totals.rejected, ''],
  ['Agents live', D.totals.live + ' / ' + D.totals.count, ''],
].map(([l,n,c])=>`<div class="kpi ${c}"><div class="n mono">${n}</div><div class="l">${l}</div></div>`).join('');

// head chips
$('#apis').innerHTML = D.apis.map(a =>
  `<span class="chip"><span class="dot ${a.ok?'ok':'off'}"></span>${esc(a.name)}${a.ok?'':' — not connected'}</span>`).join('');
$('#headlinks').innerHTML =
  (D.sheet_url?`<a href="${esc(D.sheet_url)}" target="_blank" rel="noopener">Open the shared spreadsheet →</a> &nbsp;·&nbsp; `:'') +
  `<span class="mono" style="color:var(--muted)">watchdog: hourly</span>`;

// agent cards - each analyst is a person
const HUES = ['#C0532F','#3E7CB1','#6B8E4E','#8A5EA6','#B58329','#4E8E86'];
const initials = n => n.split(/\s+/).map(w=>w[0]).join('').slice(0,2).toUpperCase();
$('#grid').innerHTML = D.sectors.map((s,i)=>{
  const tot = s.exported + s.queue + s.rejected;
  const strip = tot ? `<div class="strip" aria-hidden="true">
      <span class="s-ok" style="flex:${s.exported}"></span>
      <span class="s-q" style="flex:${s.queue}"></span>
      <span class="s-bad" style="flex:${s.rejected}"></span></div>`
    : `<div class="strip empty" aria-hidden="true"></div>`;
  const who = s.persona || s.name;
  return `<button class="agent" data-i="${i}">
    <div class="row">
      <div class="who">
        <div class="avatar" style="--av:${HUES[i%HUES.length]}">${esc(initials(who))}<span class="st ${s.enabled?'on':'off'}"></span></div>
        <div><div class="nm">${esc(who)}</div>
          <div class="rl">${esc(s.name)} Research Analyst</div></div>
      </div>
      ${s.enabled?'<span class="pill live"><span class="blink"></span>Live</span>'
                 :'<span class="pill staged">Staged</span>'}</div>
    <div class="meta">tab <b class="mono">${esc(s.worksheet)}</b>
      · ${s.multiplier?`PPP ×${s.multiplier}`:'no PPP multiplier'}
      · ${s.keywords.length} keywords · ${s.regions.length} states</div>
    ${strip}
    <div class="legend mono">
      <span><span class="dot" style="background:var(--ok)"></span><b>${s.exported}</b></span>
      <span><span class="dot" style="background:var(--queue)"></span><b>${s.queue}</b></span>
      <span><span class="dot" style="background:var(--bad)"></span><b>${s.rejected}</b></span>
    </div>
    <div class="open-hint">Inspect configuration →</div>
  </button>`;
}).join('');

const hint = (label, msg) => `<div class="hint"><em>✎ ${esc(label)}: <b>“${esc(msg)}”</b></em>
  <button data-copy="${esc(msg)}">copy</button></div>`;

function openDrawer(i){
  const s = D.sectors[i];
  const who = s.persona || s.name;
  $('#drawer').innerHTML = `
    <button class="close" id="dclose">Close ✕</button>
    <div class="who" style="margin:4px 0 2px">
      <div class="avatar lg" style="--av:${HUES[i%HUES.length]}">${esc(initials(who))}<span class="st ${s.enabled?'on':'off'}"></span></div>
      <div><h2 style="margin:0">${esc(who)}</h2>
        <div class="rl">${esc(s.name)} Research Analyst · ${s.enabled?'live':'staged'}</div></div>
    </div>
    <div class="sub mono">sectors/${esc(s.slug)}/ · sheet tab “${esc(s.worksheet)}”</div>

    <div class="sect"><h4>Funnel</h4>
      <dl class="kv mono">
        <dt>In the sheet</dt><dd>${s.exported}</dd>
        <dt>In queue</dt><dd>${s.queue}</dd>
        <dt>Screened out</dt><dd>${s.rejected}</dd>
      </dl>
      ${s.reject_reasons.length?`<div class="note">Top screen-out reasons:</div>
        <table class="buyers">${s.reject_reasons.map(([r,n])=>
          `<tr><td class="mono">${n}</td><td>${esc(r)}</td></tr>`).join('')}</table>`:''}
      ${s.top_states.length?`<div class="note">Coverage so far:
        ${s.top_states.map(([st,n])=>`<b>${esc(st)}</b> ${n}`).join(' · ')}</div>`:''}
    </div>

    <div class="sect"><h4>Sizing & thresholds</h4>
      <dl class="kv">
        <dt>Revenue estimate</dt><dd>${s.multiplier?`PPP loan × ${s.multiplier}`:'not estimated (no manual multiplier)'}</dd>
        <dt>PPP flag threshold</dt><dd>${money(s.min_ppp)} (kept &amp; flagged below)</dd>
        <dt>Revenue target</dt><dd>${money(s.min_rev)} (flagged below)</dd>
      </dl>
      ${hint('To change', 'For '+s.name+', change the PPP flag threshold to $100k')}
    </div>

    <div class="sect"><h4>Search scope</h4>
      <div class="note" style="margin:0 0 8px">${s.keywords.length} keywords ×
        ${s.regions.length} states × ${s.templates} phrasings, rotating 24/7</div>
      <div class="tags">${s.keywords.map(k=>`<span class="tag">${esc(k)}</span>`).join('')}</div>
      <div class="note">States, in priority order:</div>
      <div class="tags" style="margin-top:6px">${s.regions.map(r=>`<span class="tag">${esc(r)}</span>`).join('')}</div>
      ${s.directories.length?`<div class="note">Directories: ${s.directories.map(esc).join(' · ')}</div>`:''}
      ${hint('To change', 'For '+s.name+', prioritize Georgia and add “<keyword>”')}
    </div>

    <div class="sect"><h4>Qualification</h4>
      <div class="note" style="margin:0 0 8px">A company must match at least
        ${s.min_service_matches} of these on its website:</div>
      <div class="tags">${s.required.map(k=>`<span class="tag">${esc(k)}</span>`).join('')}</div>
      ${hint('To change', 'For '+s.name+', also require/exclude companies that …')}
    </div>

    <div class="sect"><h4>Owner rules</h4>
      <div class="note" style="margin:0 0 8px">Title priority for the contact
        (generic inboxes are never uploaded; mobile numbers preferred):</div>
      <div class="tags">${s.owner_titles.map(k=>`<span class="tag">${esc(k)}</span>`).join('')}</div>
    </div>

    <div class="sect"><h4>Buyer screen — auto-rejected owners (${s.consolidators.length})</h4>
      <table class="buyers">${s.consolidators.map(c=>
        `<tr><td><b>${esc(c.name)}</b></td><td>${esc(c.sponsor)}</td></tr>`).join('')}</table>
      ${hint('To extend', 'Add <buyer name> to the '+s.name+' buyer screen')}
    </div>

    <div class="note">Every change lands in <span class="mono">sectors/${esc(s.slug)}/</span>
      within minutes of your message — no redeploys needed.</div>`;
  $('#drawer').classList.add('on'); $('#scrim').classList.add('on');
  $('#dclose').focus();
}
function closeDrawer(){ $('#drawer').classList.remove('on'); $('#scrim').classList.remove('on'); }

document.addEventListener('click', e=>{
  const card = e.target.closest('.agent'); if(card) return openDrawer(+card.dataset.i);
  if(e.target.id==='dclose'||e.target.id==='scrim') return closeDrawer();
  const cp = e.target.closest('[data-copy]');
  if(cp){ navigator.clipboard?.writeText(cp.dataset.copy); cp.textContent='copied ✓';
          setTimeout(()=>cp.textContent='copy',1500); }
});
document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeDrawer(); });
</script>
"""


def main() -> int:
    data = collect()
    page = TEMPLATE.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    page = page.replace("__GENERATED__", html.escape(data["generated"]))
    page = page.replace("__COMMIT__", html.escape(data["commit"]))
    out = os.path.join(ROOT, "out", "dashboard.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(page)
    print(f"wrote {out} ({len(page):,} bytes, {len(data['sectors'])} sectors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
