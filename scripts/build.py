#!/usr/bin/env python3
"""Static site generator for AI IPO Watch. Zero dependencies (Python 3.9+).
Reads site.config.json + data/*.json, writes the full site to public/.
Run: python3 scripts/build.py"""
import json, html, shutil, datetime, pathlib, re
from urllib.parse import urlparse
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "public"
CFG = json.loads((ROOT / "site.config.json").read_text())
def load(n):
    p = ROOT / "data" / n
    return json.loads(p.read_text()) if p.exists() else {}
PIPE, IPOS, LOCK, FUNDS = load("pipeline.json"), load("ipos.json"), load("lockups.json"), load("funds.json")
PRICES, EDGAR = load("prices.json"), load("edgar.json")
TODAY = datetime.date.today()
SITE = CFG["site_name"]; BASE = CFG["base_url"].rstrip("/")
# Project Pages lives at /<repo>/, not the domain root. Root-absolute links
# like href="/assets/style.css" would be fetched from github.io/ and 404.
PREFIX = urlparse(BASE).path.rstrip("/")  # "/ai-ipo-watch", or "" on a custom domain

def prefix_root_urls(text):
    """Rewrite internal href/src="/…" to the Pages subpath. Leaves https:// and protocol-relative URLs alone."""
    if not PREFIX:
        return text
    def repl(m):
        return f"{m.group('attr')}={m.group('q')}{PREFIX}/{m.group('rest')}{m.group('q')}"
    return re.sub(r'''(?P<attr>\b(?:href|src))=(?P<q>["'])/(?!/)(?P<rest>[^"']*)(?P=q)''', repl, text)

e = lambda s: html.escape(str(s)) if s is not None else ""
NA = '<span class="na">n/a</span>'
PAGES = []  # for sitemap

# ---------- helpers ----------
def d(s):
    try: return datetime.date.fromisoformat(s)
    except Exception: return None
def fmt_date(s):
    if not s: return NA
    x = d(s)
    if x: return x.strftime("%b %-d, %Y")
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return datetime.date.fromisoformat(s + "-01").strftime("%b %Y")
    return e(s)
def fmt_ts(s):
    """'2026-10-19T18:24Z' -> 'Oct 19, 2026 18:24 UTC'"""
    if not s: return ""
    try:
        x = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%MZ")
        return x.strftime("%b %-d, %Y %H:%M UTC")
    except Exception:
        return s
def money(v, cur="USD"):
    if v is None: return NA
    sym = {"USD": "$", "HKD": "HK$", "CAD": "C$"}.get(cur or "USD", "")
    return f"{sym}{v:,.2f}"
def pct(v, signed=True, neutral=False):
    if v is None: return NA
    cls = "prem" if neutral else "pos" if v > 0 else "neg" if v < 0 else ""
    return f'<span class="{cls}">{v*100:+.1f}%</span>' if signed else f"{v*100:.1f}%"
def price_of(tk):
    p = PRICES.get("prices", {}).get(tk) or {}
    return p
def src(url, name):
    if not url: return ""
    return f'<a class="src" href="{e(url)}" rel="noopener nofollow" target="_blank">{e(name or "source")}</a>'
STATUS_LABEL = {"reported": "Reported", "confidentially_filed": "Confidentially filed", "publicly_filed": "Publicly filed",
                "roadshow": "Roadshow", "priced": "Priced", "withdrawn": "Withdrawn", "pre_ipo": "Pre-IPO (no filing)"}
def badge(status, confirmed=True):
    b = f'<span class="badge b-{e(status)}">{e(STATUS_LABEL.get(status, status))}</span>'
    if status == "reported" or (not confirmed and status not in ("pre_ipo",)):
        b += ' <span class="badge b-unconf" title="Based on media reports, not confirmed by the company or an SEC filing">not confirmed</span>'
    return b
def dated_badge(confirmed):
    return '<span class="tag ok">confirmed</span>' if confirmed else '<span class="tag rep">reported</span>'

# ---------- computed data ----------
def leaderboard():
    rows = []
    for it in IPOS.get("items", []):
        p = price_of(it["ticker"]); cur = p.get("price")
        basis, basis_label = it.get("offer_price"), it.get("basis_label") or "IPO price (424B4)"
        if basis is None and it.get("listing_type") == "direct_listing":
            basis, basis_label = p.get("first_open"), "First-day open (direct listing, no IPO price)"
        ret = (cur / basis - 1) if (cur is not None and basis) else None
        rows.append(dict(it, latest=cur, price_time=p.get("price_time"), stale=p.get("stale"), basis=basis, basis_label=basis_label, ret=ret, price_src=p.get("source_url")))
    rows.sort(key=lambda r: (r["ret"] is None, -(r["ret"] or 0)))
    return rows
def lockups():
    out = []
    for it in LOCK.get("items", []):
        it = dict(it); dt = d(it.get("date")) if it.get("date") else None
        if not dt and it.get("prospectus_date") and it.get("days") and not it.get("date_text"):
            dt = d(it["prospectus_date"]) + datetime.timedelta(days=it["days"]); it["date_computed"] = True
        if not dt and it.get("prospectus_date") and it.get("days") and it.get("date_text"):
            it["outer_date"] = (d(it["prospectus_date"]) + datetime.timedelta(days=it["days"])).isoformat()
        it["date"] = dt.isoformat() if dt else None
        it["days_away"] = (dt - TODAY).days if dt else None
        out.append(it)
    up = sorted([x for x in out if x["days_away"] is None or x["days_away"] >= 0], key=lambda x: (x["date"] or x.get("outer_date") or "9999"))
    past = sorted([x for x in out if x["days_away"] is not None and x["days_away"] < 0], key=lambda x: x["date"], reverse=True)
    return up, past
def funds():
    rows = []
    for f in FUNDS.get("items", []):
        p = price_of(f["ticker"]); price = p.get("price"); nav = (f.get("nav") or {}).get("value")
        prem = None if f.get("nav_is_daily") or price is None or not nav else price / nav - 1
        rows.append(dict(f, price=price, price_time=p.get("price_time"), stale=p.get("stale"), premium=prem))
    return rows
def next_date(item):
    fut = [k for k in item.get("key_dates", []) if (k["date"] or "") >= TODAY.isoformat()[:len(k["date"] or "")]]
    k = fut[0] if fut else (item.get("key_dates") or [None])[-1]
    return k

# ---------- layout ----------
NAV = [("/ipo-pipeline/", "Pipeline"), ("/ai-ipo-returns/", "Returns"), ("/lockup-calendar/", "Lock-ups"), ("/private-ai-funds/", "Pre-IPO funds"), ("/how-to-buy-vcx-in-canada/", "Canada")]
def layout(path, title, desc, body, schema=None, og_type="website", priority="0.7"):
    PAGES.append((path, priority))
    url = BASE + path; full_title = title if SITE in title else f"{title} | {SITE}"
    ld = "".join(f'<script type="application/ld+json">{json.dumps(s, ensure_ascii=False)}</script>' for s in (schema or []))
    nav = "".join(f'<a href="{h}"{" aria-current=page" if h == path else ""}>{e(t)}</a>' for h, t in NAV)
    asof = PRICES.get("as_of", "")
    doc = f"""<!doctype html><html lang="en-CA"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(full_title)}</title><meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}"><meta name="theme-color" content="{e(CFG.get('theme_color','#0b1020'))}">
<meta property="og:type" content="{og_type}"><meta property="og:site_name" content="{e(SITE)}"><meta property="og:title" content="{e(full_title)}">
<meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(url)}"><meta property="og:image" content="{BASE}/assets/og-default.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:locale" content="en_CA">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{e(full_title)}"><meta name="twitter:description" content="{e(desc)}"><meta name="twitter:image" content="{BASE}/assets/og-default.png">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/style.css">{ld}
</head><body>
<header class="top"><div class="wrap bar"><a class="logo" href="/"><span class="dot"></span>{e(SITE)}</a>
<button class="menu" aria-label="Menu" onclick="document.body.classList.toggle('nav-open')">☰</button><nav>{nav}</nav></div></header>
<main class="wrap">{body}</main>
<footer class="foot"><div class="wrap">
<p class="disc"><strong>Not financial advice.</strong> {e(SITE)} is an independent information site. Nothing here is a recommendation to buy or sell any security. IPO dates and terms change; reported items are not confirmed. Prices are delayed and may be wrong. Do your own research or talk to a registered advisor.</p>
<p class="disc"><strong>Affiliate disclosure:</strong> Some links on this site may be affiliate links (marked "partner link"). If you open an account through one, we may earn a commission at no cost to you. This never changes the data we show. Affiliate links are currently placeholders.</p>
<p class="small">Data: SEC EDGAR, company announcements, fund websites, Renaissance Capital, Yahoo Finance (delayed quotes). Prices as of {e(fmt_ts(asof))}. <a href="/methodology/">Methodology &amp; sources</a> · <a href="/about/">About</a> · <a href="/disclaimer/">Disclaimer</a> · <a href="/data/">Data (JSON)</a></p>
<p class="small">© {TODAY.year} {e(SITE)} · Made in {e(CFG.get('location','Canada'))}</p></div></footer>
<script src="/assets/app.js" defer></script></body></html>"""
    return prefix_root_urls(doc)

def newsletter():
    """Signup control comes from site.config.json.
    newsletter_form_action: POST endpoint (swap in a beehiiv embed action later).
    newsletter_url: hosted subscribe page. Beehiiv's /subscribe form does not
    prefill from a query param, so this is a link, not a prefilled form."""
    action = (CFG.get("newsletter_form_action") or "").strip()
    url = (CFG.get("newsletter_url") or "").strip()
    name = e(CFG["newsletter_name"])
    if action:
        control = f"""<form class="nl" action="{e(action)}" method="post">
<label class="sr" for="nl-email">Email</label><input id="nl-email" type="email" name="email" placeholder="you@example.com" required>
<button type="submit">Subscribe free</button></form>"""
    elif url:
        control = f"""<p class="nl"><a class="btn" href="{e(url)}">Subscribe free</a></p>
<p class="small nl-msg">Free. Opens the {name} signup.</p>"""
    else:
        control = """<form class="nl" action="" method="post" data-placeholder="1">
<label class="sr" for="nl-email">Email</label><input id="nl-email" type="email" name="email" placeholder="you@example.com" required>
<button type="submit">Subscribe</button><p class="small nl-msg" aria-live="polite">Signup is not live yet (placeholder form).</p></form>"""
    return f"""<section class="card news" id="newsletter"><div><h2>{name}</h2>
<p>One email a week: new AI IPO filings, pricing dates, lock-up expiries and premium/discount moves on DXYZ, VCX and RVI. Written for Canadian investors.</p></div>
<div>{control}</div></section>"""

def affiliates(context="buy US-listed funds from Canada"):
    btns = ""
    for k, a in CFG.get("affiliates", {}).items():
        href = a.get("url") or "#"
        ph = ' <span class="tag rep">placeholder</span>' if a.get("placeholder") or not a.get("url") else ""
        btns += f'<a class="btn ghost" href="{e(href)}" rel="sponsored nofollow noopener" data-affiliate="{e(k)}">Open a {e(a["label"])} account{ph}</a>'
    return f"""<aside class="card aff"><h3>Brokers Canadians use to {e(context)}</h3><div class="btns">{btns}</div>
<p class="small">Partner links (placeholders, not yet active). We may earn a commission if you sign up. Check that your broker actually offers the ticker before funding an account. Availability below is unverified unless marked otherwise.</p></aside>"""

# ---------- tables ----------
def pipeline_table(limit=None):
    rows = ""
    items = PIPE.get("items", [])
    order = {"roadshow": 0, "publicly_filed": 1, "confidentially_filed": 2, "reported": 3, "pre_ipo": 4, "withdrawn": 5}
    items = sorted(items, key=lambda x: (order.get(x["status"], 9), x["name"]))
    for it in items[:limit]:
        k = next_date(it)
        nd = f'{fmt_date(k["date"])} <span class="muted">{e(k["label"])}</span> {dated_badge(k["confirmed"])}' if k else NA
        v = it.get("last_private_valuation")
        val = f'{e(v["value"])}<br><span class="muted">{fmt_date(v["date"])}</span>' if v else NA
        ca = ' <span class="tag ca" title="Canadian company">🇨🇦</span>' if it.get("canadian") else ""
        srcs = " ".join(src(x["source_url"], x["source_name"]) for x in it.get("key_dates", [])[:2])
        rows += f"""<tr><td><a href="/company/{e(it['slug'])}/"><strong>{e(it['name'])}</strong></a>{ca}<br><span class="muted">{e(it.get('sector') or '')}</span></td>
<td>{badge(it['status'], it.get('status_confirmed', True))}</td><td>{nd}</td><td>{val}</td><td class="srcs">{srcs}</td></tr>"""
    return f"""<div class="tw"><table class="sortable"><thead><tr><th>Company</th><th>Status</th><th>Next / latest key date</th><th>Last private valuation</th><th>Sources</th></tr></thead><tbody>{rows}</tbody></table></div>"""

def leaderboard_table():
    rows = ""
    for i, r in enumerate(leaderboard(), 1):
        stale = ' <span class="tag rep">stale</span>' if r.get("stale") else ""
        rows += f"""<tr><td>{i}</td><td><a href="/company/{e(r['slug'])}/"><strong>{e(r['name'])}</strong></a><br><span class="muted">{e(r['ticker'])} · {e(r['exchange'])}</span></td>
<td data-v="{e(r['pricing_date'])}">{fmt_date(r['pricing_date'])}</td><td data-v="{r['basis'] or ''}">{money(r['basis'], r['currency'])}<br><span class="muted small">{e(r['basis_label'])}</span></td>
<td data-v="{r['latest'] or ''}">{money(r['latest'], r['currency'])}{stale}</td><td data-v="{r['ret'] if r['ret'] is not None else ''}">{pct(r['ret'])}</td>
<td class="small">{e(r['ai_category'])}{('<br><span class="muted">Renaissance AI rating: '+e(r['renaissance_ai_rating'])+'</span>') if r.get('renaissance_ai_rating') else ''}</td>
<td class="srcs">{src(r['source_url'], r['source_name'])} {src(r.get('price_src'), 'quote')}</td></tr>"""
    return f"""<div class="tw"><table class="sortable"><thead><tr><th>#</th><th>Company</th><th>Priced / listed</th><th>Basis price</th><th>Latest</th><th>Return</th><th>AI angle</th><th>Sources</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="small muted">Return = latest delayed price ÷ basis price − 1. Excludes dividends. Prices as of {e(fmt_ts(PRICES.get('as_of','')))} (Yahoo Finance, delayed). MiniMax is in HKD.</p>"""

def lockup_table(show_past=True):
    up, past = lockups()
    def row(x):
        when = fmt_date(x["date"]) if x["date"] else e(x.get("date_text") or "TBD")
        if x.get("outer_date"): when += f'<br><span class="muted small">no later than {fmt_date(x["outer_date"])} (computed)</span>'
        comp = '<span class="tag rep" title="Computed from the prospectus date and the lock-up length in days">computed</span>' if x.get("date_computed") else ""
        da = f'<span class="cd" data-date="{e(x["date"])}">{x["days_away"]} days</span>' if x["days_away"] is not None and x["days_away"] >= 0 else ("passed" if x["days_away"] is not None else "TBD")
        return f"""<tr><td data-v="{e(x['date'] or x.get('outer_date') or '')}">{when} {comp}</td><td>{da}</td><td><strong>{e(x['name'])}</strong><br><span class="muted">{e(x['ticker'])}</span></td>
<td class="small">{e(x['shares'])}</td><td class="small">{e(x['kind'])}{('<br><span class="muted">'+e(x['days'])+' days after prospectus dated '+fmt_date(x['prospectus_date'])+'</span>') if x.get('days') and x.get('prospectus_date') else ''}</td><td class="srcs">{src(x['source_url'], x['source_name'])}</td></tr>"""
    head = "<thead><tr><th>Date</th><th>Countdown</th><th>Company</th><th>What unlocks</th><th>Basis</th><th>Source</th></tr></thead>"
    html_ = f'<div class="tw"><table class="sortable">{head}<tbody>{"".join(row(x) for x in up)}</tbody></table></div>'
    if show_past and past:
        html_ += f'<details><summary>Recently passed lock-ups ({len(past)})</summary><div class="tw"><table>{head}<tbody>{"".join(row(x) for x in past)}</tbody></table></div></details>'
    return html_

BROKER_NAMES = [("questrade", "Questrade"), ("wealthsimple", "Wealthsimple"), ("ibkr", "IBKR"), ("qtrade", "Qtrade")]
def broker_cell(b):
    s = (b or {}).get("status", "unverified")
    cls = {"available": "ok", "not_available": "neg", "unverified": "rep"}.get(s, "rep")
    t = {"available": "available", "not_available": "not available", "unverified": "unverified"}.get(s, s)
    extra = f'<br><span class="muted small">checked {fmt_date(b.get("checked"))}</span>' if b and b.get("checked") else ""
    return f'<span class="tag {cls}">{t}</span>{extra}'
def funds_table():
    rows = ""
    for f in funds():
        hold = ", ".join(f'{e(h["name"])} <span class="muted">{e(h["weight"])}</span>' for h in f["ai_holdings"][:5])
        n = f["nav"]
        prem = "n/a (interval fund, trades at NAV)" if f.get("nav_is_daily") else pct(f["premium"], neutral=True)
        stale = ' <span class="tag rep">stale</span>' if f.get("stale") else ""
        rows += f"""<tr><td><a href="/company/{e(f['slug'])}/"><strong>{e(f['ticker'])}</strong></a><br><span class="muted">{e(f['name'])}</span><br><span class="muted small">{e(f['structure'])}</span></td>
<td class="small">{hold}<br><span class="muted">as of {fmt_date(f['holdings_as_of'])}</span> {src(f['holdings_source_url'], 'holdings source')}</td>
<td data-v="{f['price'] or ''}">{money(f['price'])}{stale}<br><span class="muted small">{e(fmt_ts(f.get('price_time')))}</span></td>
<td data-v="{n.get('value') or ''}">{money(n.get('value'))}<br><span class="muted small">as of {fmt_date(n.get('date'))}</span><br>{src(n.get('source_url'), 'NAV source')}</td>
<td data-v="{f['premium'] if f['premium'] is not None else ''}">{prem}<br><span class="muted small">vs last reported NAV</span></td>
<td class="small brk">{''.join(f'<div>{nm}: {broker_cell(f["brokers"].get(k))}</div>' for k, nm in BROKER_NAMES)}</td></tr>"""
    return f"""<div class="tw"><table class="sortable"><thead><tr><th>Fund</th><th>Key AI holdings</th><th>Latest price</th><th>Last reported NAV</th><th>Premium / discount</th><th>Canadian brokers</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="small muted">Premium/discount is computed against the <em>last reported</em> NAV, which can be months old. Broker availability: "available" / "not available" were confirmed in that broker's own symbol search on the date shown; "unverified" means we could not confirm it; confirm in your broker's symbol search.</p>"""

def faq_block(qas):
    body = "".join(f"<details class='faq'><summary>{e(q)}</summary><div>{a}</div></details>" for q, a in qas)
    schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub("<[^>]+>", "", a)}} for q, a in qas]}
    return f"<section><h2>FAQ</h2>{body}</section>", schema

def asof_line(extra=""):
    return f'<p class="asof">Data as of {fmt_date(PIPE.get("as_of"))} · prices {e(fmt_ts(PRICES.get("as_of","")))} {extra}</p>'

# ---------- pages ----------
def write(path, content):
    p = OUT / path.strip("/") / "index.html" if not path.endswith(".html") else OUT / path.strip("/")
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)

def home():
    lb = leaderboard(); up, _ = lockups(); fs = funds()
    anth = next(x for x in PIPE["items"] if x["slug"] == "anthropic")
    nxt = up[0] if up else None
    stats = f"""<div class="stats">
<div class="stat"><span class="k">Tracked pipeline</span><span class="v">{len(PIPE['items'])}</span><span class="muted small">companies</span></div>
<div class="stat"><span class="k">Recent AI listings</span><span class="v">{len(lb)}</span><span class="muted small">with returns</span></div>
<div class="stat"><span class="k">Next lock-up</span><span class="v">{fmt_date(nxt['date']) if nxt and nxt['date'] else 'TBD'}</span><span class="muted small">{e(nxt['name']) if nxt else ''}</span></div>
<div class="stat"><span class="k">Anthropic</span><span class="v sm">{e(STATUS_LABEL[anth['status']])}</span><span class="muted small">public S-1 reported for Oct 26</span></div></div>"""
    body = f"""<section class="hero"><p class="eyebrow">AI IPO tracker for Canadian investors</p><h1>Every AI IPO, lock-up and pre-IPO fund in one place</h1>
<p class="lead">Track Anthropic, OpenAI and the rest of the AI IPO pipeline, see how recent AI listings have traded, know when insiders can sell, and compare the listed funds that hold private AI stakes, including which Canadian brokers carry them.</p>{asof_line()}{stats}</section>
<section id="pipeline"><div class="sh"><h2>IPO pipeline</h2><a href="/ipo-pipeline/">Full pipeline →</a></div>
<p class="muted">Status comes from SEC EDGAR or a company announcement. Anything marked <span class="tag rep">reported</span> comes from media reports and is not confirmed.</p>{pipeline_table()}</section>
<section id="returns"><div class="sh"><h2>AI IPO leaderboard: return since listing</h2><a href="/ai-ipo-returns/">Details →</a></div>{leaderboard_table()}</section>
<section id="lockups"><div class="sh"><h2>Lock-up expiry calendar</h2><a href="/lockup-calendar/">Calendar →</a></div><p class="muted">The dates when pre-IPO insiders can first sell. Big unlocks can weigh on a share price.</p>{lockup_table(show_past=False)}</section>
<section id="funds"><div class="sh"><h2>Listed funds with private AI stakes</h2><a href="/private-ai-funds/">Compare →</a></div>{funds_table()}</section>
{affiliates()}
<section class="grid3"><a class="card link" href="/anthropic-ipo-date/"><h3>Anthropic IPO date</h3><p>What's confirmed, what's only reported, and how to get exposure today.</p></a>
<a class="card link" href="/openai-ipo/"><h3>OpenAI IPO</h3><p>The confidential S-1, the reported 2027 timeline, and the funds that hold it.</p></a>
<a class="card link" href="/how-to-buy-vcx-in-canada/"><h3>How to buy VCX in Canada</h3><p>Brokers, USD accounts, the premium to NAV and the risks.</p></a>
<a class="card link" href="/dxyz-premium-to-nav/"><h3>DXYZ premium to NAV</h3><p>The live premium/discount vs Destiny Tech100's last reported NAV.</p></a></section>
{newsletter()}"""
    schema = [{"@context": "https://schema.org", "@type": "WebSite", "name": SITE, "url": BASE + "/", "description": CFG["tagline"]},
              {"@context": "https://schema.org", "@type": "Dataset", "name": f"{SITE} AI IPO pipeline", "description": "AI IPO pipeline, returns, lock-ups and pre-IPO fund NAVs with sources", "url": BASE + "/data/", "dateModified": PIPE.get("as_of"), "creator": {"@type": "Person", "name": CFG["owner"]}}]
    write("/", layout("/", f"{SITE}: AI IPO tracker, lock-ups & pre-IPO funds (Canada)", "Track the AI IPO pipeline (Anthropic, OpenAI, Databricks), AI IPO returns, lock-up expiries and listed funds holding private AI stakes (DXYZ, VCX, RVI, ARKVX), with Canadian broker info.", body, schema, priority="1.0"))

def section_pages():
    legend = "".join(f"<li>{badge(k)} {e(v)}</li>" for k, v in PIPE.get("status_legend", {}).items())
    write("/ipo-pipeline/", layout("/ipo-pipeline/", "AI IPO pipeline: who has filed, who is rumoured", "Every AI company in the IPO pipeline, from reported plans to confidential and public S-1 filings, with key dates and SEC EDGAR links.",
        f"<h1>AI IPO pipeline</h1>{asof_line()}<ul class='legend'>{legend}</ul>{pipeline_table()}{newsletter()}", priority="0.9"))
    write("/ai-ipo-returns/", layout("/ai-ipo-returns/", "AI IPO returns since listing (leaderboard)", "How recent AI IPOs have traded: IPO price vs latest price for CoreWeave, Cerebras, SpaceX, Accelevation and more.",
        f"<h1>AI IPO leaderboard</h1>{asof_line()}<p>Ranked by return since listing. IPO prices come from each final prospectus (424B4). Direct listings have no IPO price, so we use the first-day opening price and label it.</p>{leaderboard_table()}{affiliates('buy US-listed AI stocks')}{newsletter()}", priority="0.9"))
    write("/lockup-calendar/", layout("/lockup-calendar/", "AI IPO lock-up expiry calendar", "Upcoming lock-up expiry dates for recent AI IPOs (SpaceX, Cerebras, Csquare, Accelevation and more), from the prospectus, with countdowns.",
        f"<h1>Lock-up expiry calendar</h1>{asof_line()}<p>{e(LOCK.get('method',''))}</p>{lockup_table()}{newsletter()}", priority="0.9"))
    write("/private-ai-funds/", layout("/private-ai-funds/", "Funds holding private AI stakes: DXYZ, VCX, RVI, ARKVX", "Compare the listed funds that hold Anthropic, OpenAI, SpaceX/xAI and Databricks: holdings, price, last reported NAV, premium/discount and Canadian broker availability.",
        f"<h1>Listed funds with private AI stakes</h1>{asof_line()}<p>{e(FUNDS.get('premium_method',''))}</p>{funds_table()}<p class='small'>{e(FUNDS.get('broker_method',''))}</p>{affiliates()}{newsletter()}", priority="0.9"))

def fund_by(tk): return next((f for f in funds() if f["ticker"] == tk), None)
def exposure_list(company):
    out = []
    for f in funds():
        for h in f["ai_holdings"]:
            if company.lower() in h["name"].lower():
                out.append(f"<li><a href='/company/{e(f['slug'])}/'><strong>{e(f['ticker'])}</strong></a> ({e(f['name'])}): {e(h['weight'])} as of {fmt_date(f['holdings_as_of'])}; price {money(f['price'])}, {('premium/discount vs last NAV ' + pct(f['premium'], neutral=True)) if f['premium'] is not None else 'trades at NAV'} {src(f['holdings_source_url'],'source')}</li>")
    return "<ul>" + "".join(out) + "</ul>" if out else "<p class='muted'>No listed fund in our table reports this holding.</p>"
def timeline(item):
    lis = "".join(f"<li><span class='t'>{fmt_date(k['date'])}</span> {dated_badge(k['confirmed'])} {e(k['label'])} {src(k['source_url'], k['source_name'])}</li>" for k in item.get("key_dates", []))
    return f"<ol class='tl'>{lis}</ol>"
def edgar_list(cik):
    c = (EDGAR.get("companies") or {}).get(str(cik)) if cik else None
    if not c: return "<p class='muted'>No public SEC registration filings on EDGAR.</p>"
    lis = "".join(f"<li>{fmt_date(f['date'])}: <a href='{e(f['url'])}' rel='noopener nofollow' target='_blank'>{e(f['form'])}</a></li>" for f in c["filings"][:10])
    return f"<ul class='filings'>{lis}</ul><p class='small'><a href='{e(c['edgar_page'])}' rel='noopener nofollow' target='_blank'>All filings on EDGAR →</a> (refreshed {e(EDGAR.get('as_of',''))})</p>"

def anthropic_page():
    a = next(x for x in PIPE["items"] if x["slug"] == "anthropic"); v = a["last_private_valuation"]; rv = a.get("reported_valuation_talk")
    faq, fs = faq_block([
        ("When is the Anthropic IPO date?", "No date is confirmed. Anthropic confirmed a confidential draft S-1 on June 1, 2026. IFR (via Newsquawk) reported a public SEC filing planned for around October 26, 2026 and a mid-November listing target; Renaissance Capital says December is also being considered. Treat all of these dates as reported, not confirmed."),
        ("Has Anthropic filed an S-1?", "Confidentially, yes (announced June 1, 2026). A confidential draft is not public. As of our last EDGAR check there is no public S-1. When it appears, it will show the ticker, exchange and financials."),
        ("What is Anthropic's valuation?", f"The last confirmed private valuation was {e(v['value'])} ({e(v['label'])}, {fmt_date(v['date'])}). Reuters reported on Oct 15, 2026 that some investors discussed about $1.5T for the IPO, which is not confirmed."),
        ("Can Canadians buy Anthropic stock before the IPO?", "Not directly. Indirect exposure exists through listed funds that report Anthropic holdings, such as DXYZ and VCX, which you may be able to buy through a Canadian broker that offers US-listed securities. These funds can trade at large premiums or discounts to their last reported NAV."),
        ("Will Anthropic list on the TSX?", "Nothing reported suggests a TSX listing. If it lists on a US exchange, Canadians can usually buy it through brokers that offer US stocks."),
    ])
    body = f"""<article><h1>Anthropic IPO date: what's confirmed and what's reported</h1>{asof_line()}
<div class="card status">{badge(a['status'], True)}<p>{e(a['summary'])}</p></div>
<h2>Key dates</h2>{timeline(a)}
<h2>Valuation</h2><p>Last confirmed private valuation: <strong>{e(v['value'])}</strong> ({e(v['label'])}, {fmt_date(v['date'])}) {src(v['source_url'], v['source_name'])}.</p>
<p>IPO valuation talk: {e(rv['value'])} {dated_badge(False)} {src(rv['source_url'], rv['source_name'])}</p>
<h2>SEC filings</h2><p>{e(a.get('edgar_note',''))} We check EDGAR full-text search for "Anthropic, PBC" on every refresh.</p>
<h2>How to get Anthropic exposure before the IPO</h2>{exposure_list('Anthropic')}
{affiliates('buy US-listed funds like DXYZ and VCX')}
{faq}{newsletter()}</article>"""
    art = {"@context": "https://schema.org", "@type": "Article", "headline": "Anthropic IPO date: what's confirmed and what's reported", "dateModified": PIPE.get("as_of"), "author": {"@type": "Person", "name": CFG["owner"]}}
    write("/anthropic-ipo-date/", layout("/anthropic-ipo-date/", "Anthropic IPO date (2026): filing, timeline & how to invest", "When is the Anthropic IPO? Confidential S-1 confirmed June 1, 2026; public filing reported for Oct 26 and a mid-November listing target. Sources, valuation and pre-IPO exposure for Canadians.", body, [fs, art], "article", "0.9"))

def openai_page():
    a = next(x for x in PIPE["items"] if x["slug"] == "openai"); v = a["last_private_valuation"]
    faq, fs = faq_block([
        ("When is the OpenAI IPO?", "Not set. OpenAI announced a confidential draft S-1 on June 8, 2026 and said it had not decided on timing. Reuters, citing the New York Times, reported on June 25, 2026 that it was leaning toward a 2027 listing (reported, not confirmed)."),
        ("Has OpenAI filed for an IPO?", "Confidentially, yes. No public S-1 appears on EDGAR as of our last check."),
        ("What is OpenAI's valuation?", f"{e(v['value'])} per CNBC (latest round). Reuters reported the IPO could target up to $1T (reported)."),
        ("How can Canadians get OpenAI exposure now?", "Through listed funds reporting OpenAI holdings, such as RVI, VCX and DXYZ, if your Canadian broker offers them. ARK Venture Fund (ARKVX) also holds OpenAI but is not exchange-listed."),
    ])
    body = f"""<article><h1>OpenAI IPO: the confidential S-1 and the 2027 question</h1>{asof_line()}
<div class="card status">{badge(a['status'], True)}<p>{e(a['summary'])}</p></div>
<h2>Key dates</h2>{timeline(a)}
<h2>Valuation</h2><p>{e(v['value'])} ({e(v['label'])}) {src(v['source_url'], v['source_name'])}</p>
<h2>Funds that hold OpenAI</h2>{exposure_list('OpenAI')}{affiliates()}{faq}{newsletter()}</article>"""
    write("/openai-ipo/", layout("/openai-ipo/", "OpenAI IPO: date, S-1 status & how to invest (2026)", "OpenAI confidentially filed for an IPO in June 2026 and has pointed toward 2027. Status, sources, valuation and listed funds that hold OpenAI, for Canadian investors.", body, [fs], "article", "0.9"))

def vcx_canada_page():
    f = fund_by("VCX"); n = f["nav"]
    brows = "".join(f"<tr><td>{nm}</td><td>{broker_cell(f['brokers'].get(k))}</td></tr>" for k, nm in BROKER_NAMES)
    faq, fs = faq_block([
        ("Can you buy VCX in Canada?", "VCX trades on the NYSE, so in principle any Canadian broker that offers US-listed closed-end funds can carry it. Questrade offered it in its symbol search when checked on Oct 20, 2026; Wealthsimple did not. We have not verified IBKR or Qtrade, so check the symbol search in your account."),
        ("Can I hold VCX in a TFSA or RRSP?", "US-listed securities are commonly held in TFSAs and RRSPs at Canadian brokers. Whether VCX is eligible at your broker, and how US withholding tax applies to any distributions, are questions to confirm with your broker or a tax professional."),
        ("Is VCX trading at a premium to NAV?", f"At the latest price ({money(f['price'])}) VCX is {pct(f['premium'], neutral=True)} vs its last reported NAV of {money(n['value'])} (NAV as of {fmt_date(n['date'])})."),
        ("What does VCX hold?", "Per its June 30, 2026 schedule of investments (as summarized by a secondary source): Anthropic above 20% of net assets, OpenAI and Databricks 10–20% each, plus Anduril and SpaceX."),
    ])
    body = f"""<article><h1>How to buy VCX (Fundrise Innovation Fund) in Canada</h1>{asof_line()}
<p class="lead">VCX is a NYSE-listed closed-end fund whose biggest positions are Anthropic, OpenAI and Databricks. Here's how a Canadian investor can buy it, and what to check first.</p>
<div class="stats"><div class="stat"><span class="k">Latest price</span><span class="v">{money(f['price'])}</span><span class="muted small">{e(fmt_ts(f.get('price_time')))}</span></div>
<div class="stat"><span class="k">Last reported NAV</span><span class="v">{money(n['value'])}</span><span class="muted small">as of {fmt_date(n['date'])}</span></div>
<div class="stat"><span class="k">Premium vs last NAV</span><span class="v">{pct(f['premium'], neutral=True)}</span><span class="muted small">computed</span></div></div>
<h2>Step by step</h2><ol class="steps"><li><strong>Pick a broker that offers US-listed securities.</strong> Check that VCX shows up in its symbol search before you fund the account (table below).</li>
<li><strong>Choose the account type</strong> (TFSA, RRSP, FHSA or non-registered). Confirm eligibility with your broker.</li>
<li><strong>Get US dollars.</strong> VCX trades in USD. Compare the broker's currency conversion cost; a USD sub-account helps you avoid converting twice.</li>
<li><strong>Fill out the W-8BEN form</strong> if your broker asks for it (standard for US securities).</li>
<li><strong>Use a limit order.</strong> Closed-end funds like VCX can swing a lot in price, and the premium to NAV can change fast.</li>
<li><strong>Check the premium to NAV first.</strong> You are buying a fund share, not Anthropic shares. Above NAV, you pay more than the fund's last stated value of its assets.</li></ol>
<h2>Canadian broker availability</h2><div class="tw"><table><thead><tr><th>Broker</th><th>VCX</th></tr></thead><tbody>{brows}</tbody></table></div><p class="small">{e(f.get('broker_note',''))}</p>
{affiliates('buy VCX')}
<h2>What VCX holds</h2><ul>{''.join(f"<li>{e(h['name'])}: {e(h['weight'])}</li>" for h in f['ai_holdings'])}</ul><p class="small">As of {fmt_date(f['holdings_as_of'])}. {src(f['holdings_source_url'], f['holdings_source_name'])}</p>
<h2>Key risks</h2><ul><li>Premium/discount to NAV can move sharply; VCX's own filing showed a 75.67% premium on Sep 8, 2026 {src('https://www.sec.gov/Archives/edgar/data/1867090/000121390026098534/ea0303702-01_424b2.htm','424B2')}.</li><li>NAV is quarterly and based on private-company marks.</li><li>Concentration in a few AI companies.</li><li>The fund can issue new shares through an at-the-market program (filed Sep 2026).</li></ul>
{faq}{newsletter()}</article>"""
    write("/how-to-buy-vcx-in-canada/", layout("/how-to-buy-vcx-in-canada/", "How to buy VCX in Canada (Fundrise Innovation Fund)", "How Canadians can buy VCX, the NYSE-listed fund holding Anthropic, OpenAI and Databricks: brokers, USD, TFSA/RRSP, premium to NAV and risks.", body, [fs], "article", "0.9"))

def dxyz_page():
    f = fund_by("DXYZ"); n = f["nav"]
    hist = "".join(f"<tr><td>{fmt_date(h['date'])}</td><td>{money(h['value'])}</td><td class='srcs'>{src(h['source_url'], h['source_name'])}</td></tr>" for h in f.get("nav_history", []))
    faq, fs = faq_block([
        ("What is DXYZ's premium to NAV?", f"At {money(f['price'])} (latest delayed price) vs the last reported NAV of {money(n['value'])} (as of {fmt_date(n['date'])}), DXYZ is at {pct(f['premium'], neutral=True)}. A negative number is a discount."),
        ("How often does DXYZ report NAV?", "Destiny Tech100 reports NAV in its periodic SEC filings (N-CSR / N-CSRS) and quarterly results releases, so the last reported NAV is often weeks or months old."),
        ("What AI companies does DXYZ hold?", "Per its website (as of June 30, 2026): Anthropic 14.4%, SpaceX 10.6% (which now includes xAI), OpenAI 2.6%, OpenEvidence 2.1%, Shield AI 1.8%, Databricks 1.2%."),
        ("Can I buy DXYZ in Canada?", "DXYZ is NYSE-listed. It was available in both Questrade's and Wealthsimple's symbol search when checked on Oct 20, 2026. Availability at IBKR and Qtrade is unverified on our side; check your broker's symbol search."),
    ])
    body = f"""<article><h1>DXYZ premium to NAV (Destiny Tech100)</h1>{asof_line()}
<div class="stats"><div class="stat"><span class="k">Latest price</span><span class="v">{money(f['price'])}</span><span class="muted small">{e(fmt_ts(f.get('price_time')))}</span></div>
<div class="stat"><span class="k">Last reported NAV</span><span class="v">{money(n['value'])}</span><span class="muted small">as of {fmt_date(n['date'])}</span></div>
<div class="stat"><span class="k">Premium / discount</span><span class="v">{pct(f['premium'], neutral=True)}</span><span class="muted small">vs last reported NAV</span></div></div>
<p>NAV source: {src(n['source_url'], n['source_name'])}. The premium is computed as price ÷ last reported NAV − 1. Because the NAV is months old and mostly private-company marks, the "true" premium today is unknown.</p>
<h2>Reported NAV per share history</h2><div class="tw"><table><thead><tr><th>NAV date</th><th>NAV / share</th><th>Source</th></tr></thead><tbody>{hist}</tbody></table></div>
<h2>Top AI holdings</h2><ul>{''.join(f"<li>{e(h['name'])}: {e(h['weight'])}</li>" for h in f['ai_holdings'])}</ul><p class="small">{src(f['holdings_source_url'], f['holdings_source_name'])}, as of {fmt_date(f['holdings_as_of'])}</p>
{affiliates('buy DXYZ')}{faq}{newsletter()}</article>"""
    write("/dxyz-premium-to-nav/", layout("/dxyz-premium-to-nav/", "DXYZ premium to NAV: live vs last reported NAV", "Destiny Tech100 (DXYZ) premium or discount to its last reported NAV, NAV history from SEC filings, and its Anthropic, SpaceX/xAI and OpenAI holdings.", body, [fs], "article", "0.9"))

def company_pages():
    """Per-company template: one page for each pipeline company, listed AI IPO and fund."""
    seen = set()
    ipo_by = {i["slug"]: i for i in IPOS.get("items", [])}
    lb = {r["slug"]: r for r in leaderboard()}
    up, past = lockups()
    for it in PIPE.get("items", []) + IPOS.get("items", []) + FUNDS.get("items", []):
        slug = it["slug"]
        if slug in seen: continue
        seen.add(slug)
        name = it["name"]; is_fund = it in FUNDS.get("items", [])
        parts = [f"<h1>{e(name)}{' IPO' if not is_fund else ''}: status, dates &amp; exposure</h1>", asof_line()]
        if "status" in it:
            parts.append(f"<div class='card status'>{badge(it['status'], it.get('status_confirmed', True))}<p>{e(it.get('summary',''))}</p></div><h2>Key dates</h2>{timeline(it)}")
        if slug in lb:
            r = lb[slug]
            parts.append(f"""<div class='card status'><span class='badge b-priced'>Listed</span> <strong>{e(r['ticker'])}</strong> on {e(r['exchange'])}, {'priced' if r['listing_type']=='ipo' else 'direct listing'} {fmt_date(r['pricing_date'])}
<div class='stats'><div class='stat'><span class='k'>Basis price</span><span class='v'>{money(r['basis'], r['currency'])}</span><span class='muted small'>{e(r['basis_label'])}</span></div>
<div class='stat'><span class='k'>Latest</span><span class='v'>{money(r['latest'], r['currency'])}</span><span class='muted small'>{e(fmt_ts(r.get('price_time')))}</span></div>
<div class='stat'><span class='k'>Return</span><span class='v'>{pct(r['ret'])}</span><span class='muted small'>since listing</span></div></div>{src(r['source_url'], r['source_name'])}</div>""")
            mine = [x for x in up + past if x["ticker"] == r["ticker"]]
            if mine:
                parts.append("<h2>Lock-ups</h2><ul>" + "".join(f"<li>{fmt_date(x['date']) if x['date'] else e(x.get('date_text','TBD'))}: {e(x['shares'])} ({e(x['kind'])}) {src(x['source_url'], x['source_name'])}</li>" for x in mine) + "</ul>")
        if is_fund:
            f = fund_by(it["ticker"]); n = f["nav"]
            parts.append(f"""<div class='stats'><div class='stat'><span class='k'>Latest price</span><span class='v'>{money(f['price'])}</span></div><div class='stat'><span class='k'>Last reported NAV</span><span class='v'>{money(n['value'])}</span><span class='muted small'>as of {fmt_date(n['date'])}</span></div>
<div class='stat'><span class='k'>Premium / discount</span><span class='v'>{'n/a' if f.get('nav_is_daily') else pct(f['premium'], neutral=True)}</span><span class='muted small'>vs last reported NAV</span></div></div><p>{src(n['source_url'], n['source_name'])}</p>
<h2>Key AI holdings</h2><ul>{''.join(f"<li>{e(h['name'])}: {e(h['weight'])}</li>" for h in f['ai_holdings'])}</ul><p class='small'>{src(f['holdings_source_url'], f['holdings_source_name'])}</p>
<h2>Canadian brokers</h2><div class='tw'><table><tbody>{''.join(f"<tr><td>{nm}</td><td>{broker_cell(f['brokers'].get(k))}</td></tr>" for k, nm in BROKER_NAMES)}</tbody></table></div><p class='small'>{e(f.get('broker_note',''))}</p>""")
        else:
            parts.append(f"<h2>Listed funds holding {e(name)}</h2>{exposure_list(name.split(' (')[0])}")
        parts.append(f"<h2>SEC filings</h2>{edgar_list(it.get('cik'))}")
        parts.append(affiliates()); parts.append(newsletter())
        desc = (it.get("summary") or f"{name}: IPO status, price since listing, lock-ups, SEC filings and listed-fund exposure.")[:155]
        write(f"/company/{slug}/", layout(f"/company/{slug}/", f"{name} IPO: status, dates & how to invest" if not is_fund else f"{it['ticker']} ({name}): NAV, premium & holdings", desc, "<article>" + "".join(parts) + "</article>", priority="0.6"))

def static_pages():
    write("/about/", layout("/about/", "About", f"About {SITE}", f"<article><h1>About {e(SITE)}</h1><p>{e(SITE)} is an independent tracker of AI IPOs and pre-IPO exposure, built in {e(CFG['location'])} for investors, with a focus on what Canadians can actually access.</p><p>Owner: {e(CFG['owner'])}.</p><p>The data is kept in open JSON files and refreshed by scripts; every number links to its source. If you spot an error, tell us and we will fix it.</p>{newsletter()}</article>", priority="0.3"))
    write("/disclaimer/", layout("/disclaimer/", "Disclaimer & affiliate disclosure", "Not financial advice. Affiliate disclosure.", f"<article><h1>Disclaimer</h1><p><strong>Not financial advice.</strong> All content is general information only and is not investment, tax or legal advice, nor an offer or solicitation to buy or sell any security. IPO timing and terms reported in the media are frequently wrong or change. Prices are delayed and may be inaccurate. Past performance is not indicative of future results. Consult a registered professional.</p><h2>Affiliate disclosure</h2><p>Some links (labelled partner links) may earn us a commission if you open an account. This does not influence the data. As of today all affiliate links are placeholders.</p></article>", priority="0.2"))
    srcs = "".join(f"<li>{x}</li>" for x in ["SEC EDGAR submissions API &amp; full-text search (filings, IPO prices from Form 424B4, lock-up terms)", "Company announcements (Anthropic, OpenAI, Waymo)", "Fund websites and filings (Destiny, Fundrise, Robinhood Ventures, ARK Funds)", "Renaissance Capital AI IPO tracker (pipeline candidates, AI ratings)", "Yahoo Finance public chart endpoint (delayed prices), Stooq fallback", "News reports (Reuters, Bloomberg, CNBC, IFR) for reported items, always labelled 'reported'"])
    write("/methodology/", layout("/methodology/", "Methodology & sources", "How the AI IPO data is sourced, verified and refreshed.", f"""<article><h1>Methodology &amp; sources</h1><ul>{srcs}</ul>
<h2>Rules</h2><ul><li>No invented numbers. Unknown values are shown as n/a.</li><li>Status is 'confirmed' only when it comes from an SEC filing or the company itself; media items are labelled 'reported'.</li><li>Lock-up dates come from the prospectus. When the prospectus gives "N days after the date of this prospectus", we compute the date and label it 'computed'.</li><li>Premium/discount is always vs the <em>last reported</em> NAV, shown with its date.</li><li>Broker availability stays 'unverified' until confirmed in the broker's own symbol search, with the check date recorded.</li></ul>
<h2>Refresh</h2><p>Prices: every market day. EDGAR filings and fund NAV checks: daily. Reported news: reviewed by an editor or AI agent, with sources.</p></article>""", priority="0.3"))
    # data index
    files = "".join(f"<li><a href='/data/{n}'>{n}</a></li>" for n in ["pipeline.json", "ipos.json", "lockups.json", "funds.json", "prices.json", "edgar.json"])
    write("/data/", layout("/data/", "Open data (JSON)", "Download the AI IPO pipeline, returns, lock-ups and fund NAV data as JSON.", f"<article><h1>Open data</h1><p>The JSON files behind this site. Free to use with attribution.</p><ul>{files}</ul></article>", priority="0.3"))
    (OUT / "404.html").write_text(layout("/404.html", "Page not found", "Page not found", "<h1>Page not found</h1><p><a href='/'>Back to the tracker</a></p>").replace("", ""))
    PAGES.pop()  # don't list 404 in sitemap

def assets_and_seo():
    shutil.copytree(ROOT / "src" / "assets", OUT / "assets", dirs_exist_ok=True)
    (OUT / "data").mkdir(exist_ok=True)
    for n in ["pipeline.json", "ipos.json", "lockups.json", "funds.json", "prices.json", "edgar.json"]:
        if (ROOT / "data" / n).exists(): shutil.copy(ROOT / "data" / n, OUT / "data" / n)
    lastmod = TODAY.isoformat()
    urls = "".join(f"<url><loc>{BASE}{p}</loc><lastmod>{lastmod}</lastmod><priority>{pr}</priority></url>" for p, pr in PAGES)
    (OUT / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n")
    (OUT / ".nojekyll").write_text("")

def assert_subpath():
    """Fail the build if a root-absolute link would miss the GitHub Pages subpath."""
    bad = []
    attr = re.compile(r'''(?:href|src)=(["'])(/[^"']*)\1''')
    for p in OUT.rglob("*.html"):
        for m in attr.finditer(p.read_text()):
            url = m.group(2)
            if url.startswith("//"):
                continue
            if PREFIX and not (url == PREFIX or url.startswith(PREFIX + "/")):
                bad.append(f"{p.relative_to(OUT)}: {url}")
    for loc in re.findall(r"<loc>([^<]+)</loc>", (OUT / "sitemap.xml").read_text()):
        if not loc.startswith(BASE + "/"):
            bad.append(f"sitemap: {loc}")
    robots = (OUT / "robots.txt").read_text()
    if f"Sitemap: {BASE}/sitemap.xml" not in robots:
        bad.append("robots.txt sitemap URL")
    home = (OUT / "index.html").read_text()
    og = f"{BASE}/assets/og-default.png"
    if f'href="{BASE}/"' not in home:
        bad.append("homepage canonical")
    if f'content="{og}"' not in home:
        bad.append("homepage og:image")
    css = PREFIX + "/assets/style.css"
    if f'href="{css}"' not in home:
        bad.append("homepage stylesheet")
    if not (OUT / "assets" / "style.css").is_file():
        bad.append("missing assets/style.css")
    if bad:
        raise SystemExit("subpath check failed:\n" + "\n".join(bad))

def main():
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir()
    home(); section_pages(); anthropic_page(); openai_page(); vcx_canada_page(); dxyz_page(); company_pages(); static_pages(); assets_and_seo()
    assert_subpath()
    print(f"Built {len(PAGES)} pages into {OUT}")

if __name__ == "__main__":
    main()
