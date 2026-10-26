#!/usr/bin/env python3
"""Static site generator for AI IPO Watch. Zero dependencies (Python 3.9+).
Reads site.config.json + data/*.json, writes the full site to public/.
Run: python3 scripts/build.py"""
import json, html, shutil, datetime, pathlib, re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "public"
CFG = json.loads((ROOT / "site.config.json").read_text())
def load(n):
    p = ROOT / "data" / n
    return json.loads(p.read_text()) if p.exists() else {}
PIPE, IPOS, LOCK, FUNDS = load("pipeline.json"), load("ipos.json"), load("lockups.json"), load("funds.json")
PRICES, EDGAR = load("prices.json"), load("edgar.json")
CA_BROKERS = load("ca_brokers.json")
DATA_FILES = ["pipeline.json", "ipos.json", "lockups.json", "funds.json", "prices.json", "edgar.json", "ca_brokers.json"]
TODAY = datetime.date.today()
SITE = CFG["site_name"]; BASE = CFG["base_url"].rstrip("/")
# A project-Pages URL has a path (/ai-ipo-watch); a custom domain is the root.
# Root-absolute links are prefixed only when that path is set.
PREFIX = urlparse(BASE).path.rstrip("/")  # "" for https://ipowatch.ca

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
NAV = [("/ipo-pipeline/", "Pipeline"), ("/ai-ipo-returns/", "Returns"), ("/lockup-calendar/", "Lock-ups"), ("/private-ai-funds/", "Pre-IPO funds"), ("/upcoming-ai-ipos/", "Upcoming"), ("/how-to-buy-a-us-ipo-from-canada/", "Canada")]
def layout(path, title, desc, body, schema=None, og_type="website", priority="0.7"):
    PAGES.append((path, priority))
    url = BASE + path; full_title = title if SITE in title else f"{title} | {SITE}"
    ld = "".join(f'<script type="application/ld+json">{json.dumps(s, ensure_ascii=False)}</script>' for s in (schema or []))
    nav = "".join(f'<a href="{h}"{" aria-current=page" if h == path else ""}>{e(t)}</a>' for h, t in NAV)
    sub = (CFG.get("newsletter_url") or "").strip()
    if sub:
        nav += f'<a href="{e(sub)}">Subscribe</a>'
    asof = PRICES.get("as_of", "")
    doc = f"""<!doctype html><html lang="en-CA"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name='impact-site-verification' value='0bb4882c-bc98-4a99-8bdc-d1fdd926ec95'>
<title>{e(full_title)}</title><meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}"><meta name="theme-color" content="{e(CFG.get('theme_color','#0b1020'))}">
<meta property="og:type" content="{og_type}"><meta property="og:site_name" content="{e(SITE)}"><meta property="og:title" content="{e(full_title)}">
<meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(url)}"><meta property="og:image" content="{BASE}/assets/og-default.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:locale" content="en_CA">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{e(full_title)}"><meta name="twitter:description" content="{e(desc)}"><meta name="twitter:image" content="{BASE}/assets/og-default.png">{twitter_site_tag()}
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/style.css">{ld}
</head><body>
<header class="top"><div class="wrap bar"><a class="logo" href="/"><span class="dot"></span>{e(SITE)}</a>
<button class="menu" aria-label="Menu" onclick="document.body.classList.toggle('nav-open')">☰</button><nav>{nav}</nav></div></header>
<main class="wrap">{body}</main>
<footer class="foot"><div class="wrap">
<p class="disc"><strong>Not financial advice.</strong> {e(SITE)} is an independent information site. Nothing here is a recommendation to buy or sell any security. IPO dates and terms change; reported items are not confirmed. Prices are delayed and may be wrong. Do your own research or talk to a registered advisor.</p>
<p class="disc"><strong>Affiliate disclosure:</strong> Some links on this site may be affiliate links. If you open an account through one, we may earn a commission at no cost to you. This never changes the data we show. <a href="/disclosure/">How we make money</a>.</p>
<p class="small">Updated {e(updated_label())}.</p>
<p class="small">Data: SEC EDGAR, company announcements, fund websites, Renaissance Capital, Yahoo Finance (delayed quotes). Prices as of {e(fmt_ts(asof))}. <a href="/methodology/">Methodology &amp; sources</a> · <a href="/about/">About</a> · <a href="/disclaimer/">Disclaimer</a> · <a href="/disclosure/">How we make money</a> · <a href="/data/">Data (JSON)</a></p>
<p class="small">© {TODAY.year} {e(SITE)} · Made in {e(CFG.get('location','Canada'))}</p></div></footer>
<script src="/assets/app.js" defer></script>
<script data-goatcounter="https://ipowatch.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script></body></html>"""
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

def twitter_site_tag():
    handle = (CFG.get("twitter_handle") or "").strip().lstrip("@")
    if not handle:
        return ""
    return f'<meta name="twitter:site" content="@{e(handle)}">'

def newsletter_cta(label=None):
    """Compact hero CTA. Shown on the home page and the Anthropic page."""
    url = (CFG.get("newsletter_url") or CFG.get("newsletter_form_action") or "").strip()
    if not url:
        return ""
    text = label or "Get the S-1 breakdown the day it's filed - Subscribe free"
    return f'<p class="nl-cta"><a class="btn" href="{e(url)}">{html.escape(text, quote=False)}</a></p>'

def live_affiliates():
    """Real affiliate links only. Empty or placeholder URLs stay hidden."""
    out = []
    for k, a in CFG.get("affiliates", {}).items():
        url = (a.get("url") or "").strip()
        if not url or a.get("placeholder"):
            continue
        out.append((k, a, url))
    return out

def affiliate_disclosure(items):
    """Short line next to affiliate links. Rendered only when a page actually links one."""
    if not items:
        return ""
    extra = f"<p>{WS_OPINION}</p>" if any(k == "wealthsimple" for k, _, _ in items) else ""
    return f'<p class="small aff-note">Some links on this page may earn us a commission. <a href="/disclosure/">See how we make money.</a></p>{extra}'

def affiliates(context="buy US-listed funds from Canada"):
    items = live_affiliates()
    if not items:
        return ""
    btns = "".join(
        f'<a class="btn ghost" href="{e(url)}" rel="sponsored nofollow noopener" data-affiliate="{e(k)}">Open a {e(a["label"])} account</a>'
        for k, a, url in items)
    return f"""<aside class="card aff"><h3>Brokers Canadians use to {e(context)}</h3><div class="btns">{btns}</div>
{affiliate_disclosure(items)}
<p class="small">Check that your broker actually offers the ticker before funding an account.</p></aside>"""

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
def broker_home_link(key, label=None):
    """Public homepage only. Affiliate URLs stay in site.config.json and are not used here."""
    a = (CFG.get("affiliates") or {}).get(key) or {}
    name = label or a.get("label") or key
    url = (a.get("homepage") or "").strip()
    if not url:
        return e(name)
    return f'<a href="{e(url)}" rel="noopener" target="_blank">{e(name)}</a>'
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
<td class="small brk">{''.join(f'<div>{broker_home_link(k, nm)}: {broker_cell(f["brokers"].get(k))}</div>' for k, nm in BROKER_NAMES)}</td></tr>"""
    return f"""<div class="tw"><table class="sortable"><thead><tr><th>Fund</th><th>Key AI holdings</th><th>Latest price</th><th>Last reported NAV</th><th>Premium / discount</th><th>Canadian brokers</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="small muted">Premium/discount is computed against the <em>last reported</em> NAV, which can be months old. Broker availability: "available" / "not available" were confirmed in that broker's own symbol search on the date shown; "unverified" means we could not confirm it; confirm in your broker's symbol search.</p>"""

def faq_block(qas):
    body = "".join(f"<details class='faq'><summary>{e(q)}</summary><div>{a}</div></details>" for q, a in qas)
    schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub("<[^>]+>", "", a)}} for q, a in qas]}
    return f"<section><h2>FAQ</h2>{body}</section>", schema

def asof_line(extra=""):
    return f'<p class="asof">Data as of {fmt_date(PIPE.get("as_of"))} · prices {e(fmt_ts(PRICES.get("as_of","")))} {extra}</p>'

MT = ZoneInfo("America/Edmonton")
STAMP_KEYS = {"as_of", "edgar_checked_at", "price_time"}
WS_OPINION = "Any opinions expressed in this content are solely my own and not the views or opinions of Wealthsimple. If you click on referral links in this piece and sign up for a Wealthsimple account I may receive a commission."

def _parse_stamp(s):
    """Parse a data timestamp. Date-only strings are not clocks."""
    if not isinstance(s, str) or "T" not in s:
        return None
    s = s.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2})?Z", s)
    if m:
        y, mo, da, hh, mm = (int(x) for x in m.groups())
        return datetime.datetime(y, mo, da, hh, mm, tzinfo=datetime.timezone.utc)
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})\s*MT", s)
    if m:
        y, mo, da, hh, mm = (int(x) for x in m.groups())
        return datetime.datetime(y, mo, da, hh, mm, tzinfo=MT)
    return None

def _walk_stamps(obj, acc):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in STAMP_KEYS:
                dt = _parse_stamp(v)
                if dt:
                    acc.append(dt)
            _walk_stamps(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _walk_stamps(v, acc)

def newest_dt():
    acc = []
    for p in sorted((ROOT / "data").glob("*.json")):
        try:
            _walk_stamps(json.loads(p.read_text()), acc)
        except Exception:
            continue
    return max(acc) if acc else None

def updated_label():
    dt = newest_dt()
    if not dt:
        return fmt_date(PIPE.get("as_of"))
    local = dt.astimezone(MT)
    clock = local.strftime("%-I:%M %p")
    return f"{local.strftime('%b %-d, %Y')} {clock} MT"

def newest_iso():
    dt = newest_dt()
    if not dt:
        return PIPE.get("as_of")
    return dt.astimezone(MT).isoformat(timespec="minutes")

def article_ld(headline):
    return {"@context": "https://schema.org", "@type": "Article", "headline": headline,
            "datePublished": PIPE.get("as_of"), "dateModified": newest_iso(),
            "author": {"@type": "Person", "name": CFG["owner"]}}

def linkify(text):
    parts = re.split(r"(https?://[^\s)]+)", text or "")
    out = ""
    for p in parts:
        if p.startswith("http"):
            trail = ""
            while p and p[-1] in ".,;:":
                trail = p[-1] + trail
                p = p[:-1]
            out += f'<a href="{e(p)}" rel="noopener nofollow" target="_blank">{e(p)}</a>{trail}'
        else:
            out += e(p)
    return out

def fmt_md(s):
    x = d(s) if s and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None
    return x.strftime("%b %-d") if x else fmt_date(s)

def short_source(name):
    name = name or ""
    if name.lower().startswith("yahoo"):
        return "Yahoo"
    return name

def anthropic_item():
    return next(x for x in PIPE["items"] if x["slug"] == "anthropic")

def format_checked(raw):
    raw = (raw or "").strip()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?Z", raw)
    if m:
        return f"{fmt_date(m.group(1))} {m.group(2)} UTC"
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})\s*MT", raw)
    if m:
        return f"{fmt_date(m.group(1))} {m.group(2)} MT"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return fmt_date(raw)
    return raw

def confirmed_public_s1_date(a):
    for k in a.get("key_dates") or []:
        lab = (k.get("label") or "").lower()
        if k.get("confirmed") and lab.startswith("public s-1 filed"):
            return k.get("date")
    return None

def edgar_note_for(a):
    """Generated from edgar_checked_at so a filing-day edit does not touch this sentence."""
    if a.get("status") == "publicly_filed":
        return "Public S-1 is on EDGAR."
    day = (a.get("edgar_checked_at") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return f"No public S-1 found on EDGAR as of {day}."
    return a.get("edgar_note") or "No public S-1 found on EDGAR."

def s1_edgar_url(a):
    url = (a.get("public_s1_url") or "").strip()
    if url:
        return url
    if a.get("status") == "publicly_filed" and a.get("cik"):
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={str(a['cik']).zfill(10)}&type=S-1"
    return ""

def _unconfirmed(a):
    return [k for k in a.get("key_dates", []) if not k.get("confirmed")]

def filing_key_dates(a):
    out = []
    for k in _unconfirmed(a):
        lab = (k.get("label") or "").lower()
        if "confidential" in lab:
            continue
        if "s-1" in lab or "filing" in lab:
            out.append(k)
    return out

def filing_blurb(a):
    dates = filing_key_dates(a)
    if not dates:
        return "No reported public S-1 date"
    bits = []
    for k in dates:
        who = short_source(k.get("source_name"))
        when = fmt_md(k.get("date"))
        bits.append(f"{when} ({who})" if who else when)
    if len(bits) == 1:
        return f"Public S-1 reported as early as {bits[0]}"
    return "Public S-1 reported as early as " + " or ".join(bits)

def timing_extra(a):
    candidates = []
    for k in _unconfirmed(a):
        lab = k.get("label") or ""
        low = lab.lower()
        if "s-1" in low or "filing" in low or "confidential" in low:
            continue
        if any(w in low for w in ("roadshow", "listing", "pricing")):
            candidates.append(k)
    specific = [k for k in candidates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", k.get("date") or "")]
    lines = []
    for k in candidates:
        if specific and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", k.get("date") or ""):
            continue
        lines.append(f"{e(k.get('label') or '')} {src(k.get('source_url'), k.get('source_name'))}")
    return "<br>".join(lines)

def s1_box(a):
    filed = a.get("status") == "publicly_filed"
    link = s1_edgar_url(a)
    if filed and link:
        yn = f'Yes (<a href="{e(link)}" rel="noopener nofollow" target="_blank">view on EDGAR</a>)'
    elif filed:
        yn = "Yes"
    else:
        yn = "No"
    extra = timing_extra(a)
    checked = format_checked(a.get("edgar_checked_at"))
    if filed:
        when = fmt_date(confirmed_public_s1_date(a))
        tk = a.get("ticker") or "n/a"
        ex = a.get("exchange") or "n/a"
        blurb = f"Filed {when}. Proposed ticker {tk}. Applied to list on {ex}. The price range is not set"
        extra_html = f"<p><strong>Still reported, not confirmed:</strong><br>{extra}</p>" if extra else ""
        note = "The filing itself is the S-1 on EDGAR. Roadshow and debut dates are media reports and are not confirmed."
    else:
        blurb = filing_blurb(a)
        extra_html = f"<p>{extra}</p>" if extra else ""
        note = "None of this timing is confirmed by the company."
    return f"""<aside class="card s1" id="s1-status"><h2>S-1 filed?</h2>
<p><strong>Public S-1 on EDGAR:</strong> {yn}</p>
<p>{e(blurb)}.</p>
{extra_html}
<p class="small muted">Last checked {e(checked)}. {e(note)}</p></aside>"""

def _fin_cell(v):
    return e(v) if v else NA

def s1_financials_html(a):
    fin = a.get("s1_financials") or {}
    if not fin.get("h1_2026_revenue"):
        return ""
    link = src(fin.get("source_url"), fin.get("source_name") or "S-1")
    rows = [
        ("Revenue", fin.get("h1_2025_revenue"), fin.get("h1_2026_revenue"), fin.get("fy2025_revenue")),
        ("Operating loss", fin.get("h1_2025_operating_loss"), fin.get("h1_2026_operating_loss"), ""),
        ("Net loss", "", fin.get("h1_2026_net_loss"), ""),
        ("of which: change in fair value of convertible notes, derivative liabilities, and SAFEs", "", fin.get("h1_2026_fair_value"), ""),
        ("Compute and infrastructure, percent of revenue", fin.get("h1_2025_compute_pct"), fin.get("h1_2026_compute_pct"), ""),
    ]
    body = "".join(
        f"<tr><td>{e(line)}</td><td>{_fin_cell(c1)}</td><td>{_fin_cell(c2)}</td><td>{_fin_cell(c3)}</td></tr>"
        for line, c1, c2, c3 in rows
    )
    return f"""<h2>Financials from the S-1</h2>
<p>For the six months ended June 30, 2026, the S-1 reports revenue of {e(fin.get('h1_2026_revenue'))}, compared with {e(fin.get('h1_2025_revenue'))} in the six months ended June 30, 2025. Operating loss was {e(fin.get('h1_2026_operating_loss'))}, compared with {e(fin.get('h1_2025_operating_loss'))}. Net loss was {e(fin.get('h1_2026_net_loss'))}. Of that net loss, {e(fin.get('h1_2026_fair_value'))} is the change in fair value of convertible notes, derivative liabilities, and SAFEs. The filing says those instruments are marked to market each period, so a higher enterprise valuation increases this expense. It is a non-cash mark-to-market change, not cash spent on operations. The operating result is the {e(fin.get('h1_2026_operating_loss'))} operating loss, not the {e(fin.get('h1_2026_net_loss'))} net loss. Other income (expense), net was a further loss of {e(fin.get('h1_2026_other_expense'))} in the same six months. The S-1 says that line is mostly fair-value changes on strategic investments and other financial instruments. Compute and infrastructure costs were {e(fin.get('h1_2026_compute_pct'))} of revenue, compared with {e(fin.get('h1_2025_compute_pct'))} a year earlier. Revenue for the year ended December 31, 2025 was {e(fin.get('fy2025_revenue'))}. {link}</p>
<p class="small muted">Dollar amounts are as printed in the summary consolidated statements of operations, in millions. "About" figures are the same amounts in billions, rounded half up. The 55% and 201% lines are the filing's compute and infrastructure expense as a percentage of revenue.</p>
<div class="tw"><table><thead><tr><th></th><th>Six months ended June 30, 2025</th><th>Six months ended June 30, 2026</th><th>Year ended December 31, 2025</th></tr></thead><tbody>{body}</tbody></table></div>"""

def financials_table(a):
    rows = a.get("reported_financials") or []
    if not rows:
        return ""
    body = ""
    for r in rows:
        loss = e(r["net_loss"]) if r.get("net_loss") else NA
        note = f'<br><span class="muted small">{e(r["note"])}</span>' if r.get("note") else ""
        sources = " ".join(src(s.get("source_url"), s.get("source_name")) for s in r.get("sources") or [])
        body += f"<tr><td>{e(r.get('period'))}</td><td>{e(r.get('revenue') or NA)}</td><td>{loss}{note}</td><td class='srcs'>{sources}</td></tr>"
    if a.get("s1_financials"):
        intro = "These earlier figures come from news reports. They are rounded. The S-1 table above is the filing. Q3 2026 is still a news report only."
    else:
        intro = "These figures come from news reports, not from a public S-1."
    return f"""<h2>Financials (reported)</h2>
<p class="muted">{e(intro)}</p>
<div class="tw"><table><thead><tr><th>Period</th><th>Revenue</th><th>Net loss</th><th>Sources</th></tr></thead><tbody>{body}</tbody></table></div>"""

def valuation_html(a):
    v = a.get("last_private_valuation") or {}
    html_ = ""
    if v:
        html_ += f"<p>Last confirmed private valuation: <strong>{e(v.get('value'))}</strong> ({e(v.get('label'))}, {fmt_date(v.get('date'))}) {src(v.get('source_url'), v.get('source_name'))}.</p>"
    talks = a.get("reported_valuations") or ([a["reported_valuation_talk"]] if a.get("reported_valuation_talk") else [])
    for rv in talks:
        html_ += f"<p>{e(rv.get('value'))} {dated_badge(False)} {src(rv.get('source_url'), rv.get('source_name'))}</p>"
    return f"<h2>Valuation</h2>{html_}" if html_ else ""

def canadians_exposure(a):
    if a.get("ticker") and a.get("status") in ("publicly_filed", "roadshow", "priced"):
        tick_note = f"{e(a['ticker'])}, the proposed Anthropic ticker, which is not listed yet"
    else:
        tick_note = "Anthropic, which has no ticker"
    rows = ""
    for tk in ("DXYZ", "VCX"):
        f = fund_by(tk)
        if not f:
            continue
        prem = pct(f["premium"], neutral=True) if f["premium"] is not None else NA
        brokers = "".join(f"<div>{broker_home_link(k, nm)}: {broker_cell(f['brokers'].get(k))}</div>" for k, nm in BROKER_NAMES)
        rows += f"<tr><td><a href='/company/{e(f['slug'])}/'><strong>{e(f['ticker'])}</strong></a><br><span class='muted small'>{e(f['name'])}</span></td><td>{money(f['price'])}</td><td>{prem}<br><span class='muted small'>vs last reported NAV</span></td><td class='small brk'>{brokers}</td></tr>"
    return f"""<h2>How Canadians can get exposure before a listing</h2>
<p>You cannot buy Anthropic itself yet. Two NYSE-listed funds report Anthropic holdings. You would be buying the fund, not Anthropic. The share price can sit far above or below the last reported NAV.</p>
<div class="tw"><table><thead><tr><th>Fund</th><th>Latest price</th><th>Premium / discount</th><th>Canadian brokers</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="small muted">Broker cells are symbol-search checks for these fund tickers, on the date shown. They are not a check for {tick_note}. RBC Direct Investing is not in this check. Unverified means we did not confirm it.</p>"""

def sec_block(a):
    note = edgar_note_for(a)
    checked = format_checked(a.get("edgar_checked_at"))
    if a.get("status") == "publicly_filed":
        link = s1_edgar_url(a)
        linked = f' <a href="{e(link)}" rel="noopener nofollow" target="_blank">Public S-1 on EDGAR</a>.' if link else ""
        return f"<h2>SEC filings</h2><p>{e(note)}{linked} Last checked {e(checked)}.</p>{edgar_list(a.get('cik'))}"
    return f"<h2>SEC filings</h2><p>{e(note)} Last checked {e(checked)}.</p>"

def anth_faq_when(a):
    if a.get("status") == "publicly_filed":
        when = fmt_date(confirmed_public_s1_date(a))
        parts = [f"The public S-1 was filed on {when}. That filing does not set an IPO price or a pricing date. The cover page leaves the price range blank."]
        bits = []
        for k in _unconfirmed(a):
            lab = k.get("label") or ""
            low = lab.lower()
            if "s-1" in low or "filing" in low or "confidential" in low:
                continue
            if any(w in low for w in ("roadshow", "listing", "pricing")):
                bits.append(f"{e(k.get('source_name') or 'Report')} ({fmt_date(k.get('date'))}): {e(lab)}")
        if bits:
            parts.append("Reported roadshow and listing timing, not confirmed: " + "; ".join(bits) + ".")
        return " ".join(parts)
    parts = ["No date is confirmed by the company."]
    for k in a.get("key_dates", []):
        lab = (k.get("label") or "").lower()
        if k.get("confirmed") and "confidential" in lab and "s-1" in lab:
            parts.append(f"Anthropic confirmed a confidential draft S-1 on {fmt_date(k['date'])}.")
            break
    bits = []
    for k in _unconfirmed(a):
        lab = k.get("label") or ""
        low = lab.lower()
        if any(w in low for w in ("s-1", "filing", "roadshow", "listing", "pricing")) and "confidential" not in low:
            bits.append(f"{e(k.get('source_name') or 'Report')} ({fmt_date(k.get('date'))}): {e(lab)}")
    if bits:
        parts.append("Reported timing, not confirmed: " + "; ".join(bits) + ".")
    return " ".join(parts)

def anth_faq_filed(a):
    if a.get("status") == "publicly_filed":
        link = s1_edgar_url(a)
        extra = f' <a href="{e(link)}" rel="noopener nofollow" target="_blank">Read the S-1 on EDGAR</a>.' if link else ""
        when = fmt_date(confirmed_public_s1_date(a))
        tk = e(a.get("ticker") or "n/a")
        ex = e(a.get("exchange") or "n/a")
        cik = e(a.get("cik") or "")
        return (f"Yes. Anthropic filed a public S-1 on {when}.{extra} "
                f"Proposed ticker {tk} on {ex}. The price range is not set. "
                f"CIK {cik}. Last checked {e(format_checked(a.get('edgar_checked_at')))}.")
    conf = ""
    for k in a.get("key_dates", []):
        lab = (k.get("label") or "").lower()
        if k.get("confirmed") and "confidential" in lab and "s-1" in lab:
            conf = f"Confidentially, yes (announced {fmt_date(k['date'])}). A confidential draft is not public. "
            break
    return f"{conf}{e(edgar_note_for(a))} Last checked {e(format_checked(a.get('edgar_checked_at')))}. When a public S-1 appears, it will show the ticker, exchange and financials."

def anth_faq_valuation(a):
    v = a.get("last_private_valuation") or {}
    talks = a.get("reported_valuations") or ([a["reported_valuation_talk"]] if a.get("reported_valuation_talk") else [])
    extra = " ".join(f"{e(t.get('source_name') or 'Report')} (reported): {e(t.get('value'))}." for t in talks)
    return f"The last confirmed private valuation was {e(v.get('value'))} ({e(v.get('label'))}, {fmt_date(v.get('date'))}). {extra} None of the IPO valuation talk is confirmed by the company."

def anth_faq_ipo_price():
    return ("No. Canadians should not count on buying Anthropic at the IPO price. "
            "Questrade says that in most cases a US IPO is filled in the United States and Canadian residents cannot take part. "
            "After a US listing, the usual route is a broker that offers US stocks, often in a TFSA or RRSP, with US dollars already in the account, a W-8BEN, and a limit order. Confirm the ticker in your broker's symbol search. "
            'As US context only, Fidelity says IPO participation there is for brokerage customers with at least $25,000 in retail assets, and that most of the shares go to institutions (<a href="https://www.fidelity.com/stock-trading/ipos" rel="noopener nofollow" target="_blank">Fidelity</a>). That is not a Canadian account. '
            "Today, an indirect route is DXYZ or VCX, which can trade at a premium or discount to their last reported NAV. This is general information only, not personalized advice.")

def anth_desc(a):
    conf = ""
    for k in a.get("key_dates", []):
        lab = (k.get("label") or "").lower()
        if k.get("confirmed") and "confidential" in lab and "s-1" in lab:
            conf = f"Confidential S-1 confirmed {fmt_date(k['date'])}. "
            break
    if a.get("status") == "publicly_filed":
        lead = "Anthropic's public S-1 is on EDGAR. "
    else:
        lead = filing_blurb(a) + ". "
    return (lead + conf + "Reported financials, valuation and how Canadians can get exposure.").strip()

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
<div class="stat"><span class="k">Anthropic</span><span class="v sm">{e(STATUS_LABEL[anth['status']])}</span><span class="muted small">{e(filing_blurb(anth) if anth.get('status') != 'publicly_filed' else (f"Proposed ticker {anth.get('ticker') or 'ANT'}. Price range not set."))}</span></div></div>"""
    body = f"""<section class="hero"><p class="eyebrow">AI IPO tracker for Canadian investors</p><h1>Every AI IPO, lock-up and pre-IPO fund in one place</h1>
<p class="lead">Track Anthropic, OpenAI and the rest of the AI IPO pipeline, see how recent AI listings have traded, know when insiders can sell, and compare the listed funds that hold private AI stakes, including which Canadian brokers carry them.</p>{asof_line()}{s1_box(anth)}{newsletter_cta()}{stats}</section>
<section id="pipeline"><div class="sh"><h2>IPO pipeline</h2><a href="/ipo-pipeline/">Full pipeline →</a></div>
<p class="muted">Status comes from SEC EDGAR or a company announcement. Anything marked <span class="tag rep">reported</span> comes from media reports and is not confirmed.</p>{pipeline_table()}</section>
<section id="returns"><div class="sh"><h2>AI IPO leaderboard: return since listing</h2><a href="/ai-ipo-returns/">Details →</a></div>{leaderboard_table()}</section>
<section id="lockups"><div class="sh"><h2>Lock-up expiry calendar</h2><a href="/lockup-calendar/">Calendar →</a></div><p class="muted">The dates when pre-IPO insiders can first sell. Big unlocks can weigh on a share price.</p>{lockup_table(show_past=False)}</section>
<section id="funds"><div class="sh"><h2>Listed funds with private AI stakes</h2><a href="/private-ai-funds/">Compare →</a></div>{funds_table()}</section>
{affiliates()}
<section class="grid3"><a class="card link" href="/anthropic-ipo/"><h3>Anthropic IPO</h3><p>Public S-1 filed Oct 26. Proposed ticker ANT on Nasdaq Global Select. How to buy it in Canada.</p></a>
<a class="card link" href="/how-to-buy-a-us-ipo-from-canada/"><h3>Buy a US IPO from Canada</h3><p>Allocation versus day one, brokers, TFSA, RRSP and FX costs.</p></a>
<a class="card link" href="/upcoming-ai-ipos/"><h3>Upcoming AI IPOs</h3><p>The pipeline in one list, with the Canada guides.</p></a>
<a class="card link" href="/openai-ipo/"><h3>OpenAI IPO</h3><p>The confidential S-1, the reported 2027 timeline, and the funds that hold it.</p></a>
<a class="card link" href="/how-to-buy-vcx-in-canada/"><h3>How to buy VCX in Canada</h3><p>Brokers, USD accounts, the premium to NAV and the risks.</p></a>
<a class="card link" href="/dxyz-premium-to-nav/"><h3>DXYZ premium to NAV</h3><p>The live premium/discount vs Destiny Tech100's last reported NAV.</p></a></section>
{newsletter()}"""
    schema = [{"@context": "https://schema.org", "@type": "WebSite", "name": SITE, "url": BASE + "/", "description": CFG["tagline"]},
              {"@context": "https://schema.org", "@type": "Dataset", "name": f"{SITE} AI IPO pipeline", "description": "AI IPO pipeline, returns, lock-ups and pre-IPO fund NAVs with sources", "url": BASE + "/data/", "dateModified": newest_iso(), "creator": {"@type": "Person", "name": CFG["owner"]}}]
    write("/", layout("/", f"{SITE}: AI IPO tracker, lock-ups & pre-IPO funds (Canada)", "Track the AI IPO pipeline (Anthropic, OpenAI, Databricks), AI IPO returns, lock-up expiries and listed funds holding private AI stakes (DXYZ, VCX, RVI, ARKVX), with Canadian broker info.", body, schema, priority="1.0"))

def section_pages():
    legend = "".join(f"<li>{badge(k)} {e(v)}</li>" for k, v in PIPE.get("status_legend", {}).items())
    write("/ipo-pipeline/", layout("/ipo-pipeline/", "AI IPO pipeline: who has filed, who is rumoured", "Every AI company in the IPO pipeline, from reported plans to confidential and public S-1 filings, with key dates and SEC EDGAR links.",
        f"<h1>AI IPO pipeline</h1>{asof_line()}<p>Guides: <a href='/upcoming-ai-ipos/'>upcoming AI IPOs</a>, <a href='/anthropic-ipo/'>the Anthropic IPO</a>, and <a href='/how-to-buy-a-us-ipo-from-canada/'>how to buy a US IPO from Canada</a>.</p><ul class='legend'>{legend}</ul>{pipeline_table()}{newsletter()}", priority="0.9"))
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
    if not c:
        if cik:
            return "<p class='muted'>The daily EDGAR index on this site does not list this CIK yet. Use the S-1 link above if one is shown.</p>"
        return "<p class='muted'>No public SEC registration filings on EDGAR.</p>"
    lis = "".join(f"<li>{fmt_date(f['date'])}: <a href='{e(f['url'])}' rel='noopener nofollow' target='_blank'>{e(f['form'])}</a></li>" for f in c["filings"][:10])
    return f"<ul class='filings'>{lis}</ul><p class='small'><a href='{e(c['edgar_page'])}' rel='noopener nofollow' target='_blank'>All filings on EDGAR →</a> (refreshed {e(EDGAR.get('as_of',''))})</p>"

CRA_FOLIO = "https://www.canada.ca/en/revenue-agency/services/tax/technical-information/income-tax/income-tax-folios-index/series-3-property-investments-savings-plans/series-3-property-investments-savings-plan-folio-10-registered-plans-individuals/income-tax-folio-s3-f10-c1-qualified-investments-rrsps-resps-rrifs-rdsps-tfsas.html"
FIN_EXCH = "https://www.canada.ca/en/department-finance/services/designated-stock-exchanges.html"
TREATY = "https://www.canada.ca/en/department-finance/programs/tax-policy/tax-treaties/country/united-states-america-convention-consolidated-1980-1983-1984-1995-1997-2007.html"
W8 = "https://www.irs.gov/forms-pubs/about-form-w-8-ben"
EDGAR_ANTH = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=anthropic&type=S-1"
ANTH_TITLE = "Anthropic IPO: date, valuation, and how to buy it in Canada"

def advice_note():
    return '<p class="note"><strong>Not financial advice.</strong> This is general information for people in Canada. It is not a recommendation to buy or sell any security, and it is not tax advice. IPO dates change. Anything marked reported is not confirmed by the company.</p>'

def affiliate_spot(context="buy US-listed stocks from Canada"):
    """Real referral buttons only after a URL is set. The pending slot stays neutral."""
    if live_affiliates():
        return affiliates(context)
    return ('<aside class="card aff" id="affiliate-links" data-affiliate-slot="pending">'
            '<!-- affiliate slot: set affiliates.*.url in site.config.json and set placeholder to false. Empty or placeholder URLs are not rendered as links. -->'
            '<p class="small">Broker names on this page go to each firm\'s public website. Referral links are not in use. If one is added later, it will be labelled, and the commission will be disclosed beside it. <a href="/disclosure/">How we make money</a>.</p>'
            '</aside>')

def broker_fact_cards():
    day = fmt_date(CA_BROKERS.get("as_of"))
    cards = ""
    for b in CA_BROKERS.get("items") or []:
        bits = []
        if b.get("us_stocks"):
            bits.append(f"<p>{e(b['us_stocks'])}</p>")
        if b.get("fx"):
            bits.append(f"<p><strong>Currency conversion.</strong> {e(b['fx'])}</p>")
        if b.get("usd_account"):
            bits.append(f"<p><strong>US dollars.</strong> {e(b['usd_account'])}</p>")
        if b.get("ipo"):
            bits.append(f"<p><strong>Getting shares in the offering.</strong> {e(b['ipo'])}</p>")
        srcs = " ".join(src(s.get("url"), s.get("name")) for s in b.get("sources") or [])
        cards += f'<div class="card broker"><h3>{broker_home_link(b["id"])}</h3>{"".join(bits)}<p class="small srcs">Fee pages checked {day}. {srcs}</p></div>'
    cards += f'<p class="small">{broker_home_link("ibkr")} appears in our symbol-search checks for listed funds. This page does not quote an Interactive Brokers commission or conversion rate.</p>'
    return cards

def fx_faq_answer():
    day = fmt_date(CA_BROKERS.get("as_of"))
    shorts = [b.get("fx_short") for b in (CA_BROKERS.get("items") or []) if b.get("fx_short")]
    return (f"As of {day}, from each broker's own pages: {'; '.join(shorts)}. "
            "US dollars already in the account let you buy without converting on the way in and again on the way out. "
            "Schedules change. Read the fee page before you convert a large amount.")

def registered_accounts_html():
    return f"""<h2>TFSA, RRSP and FHSA</h2>
<p>Once a common share lists on a designated stock exchange, it is a qualified investment for a TFSA, an RRSP, an FHSA and the other plans named in the CRA folio. {src(CRA_FOLIO, "CRA folio S3-F10-C1")}</p>
<p>Nasdaq and the NYSE are both on Finance Canada's designated list. {src(FIN_EXCH, "Department of Finance")}</p>
<p>That is about eligibility after the shares list. It does not mean your broker will accept a brand-new ticker in that account on the first morning. Check the symbol search. A stock that only trades over the counter is a different case. Those markets are not designated exchanges.</p>
<p>Canadian tax on growth inside a TFSA or RRSP is separate from US tax on dividends. Article X of the Canada-US tax treaty generally caps US tax on dividends paid to a Canadian resident at 15%. Article XXI(2) exempts dividends received by a Canadian pension or retirement arrangement. An RRSP is that kind of plan. A TFSA is not a pension, so that exemption does not apply to it. {src(TREATY, "Canada-US tax treaty")}</p>
<p>Brokers usually ask for Form W-8BEN so the US payer can apply the treaty rate. {src(W8, "IRS Form W-8BEN")}</p>
<p>Confirm the security and any withholding with your broker or a tax professional before you place the trade.</p>"""

def allocation_vs_market_html():
    return """<h2>Allocation versus buying on day one</h2>
<p>These are two different purchases.</p>
<p><strong>An allocation</strong> means shares from the offering, at the IPO price, before the first trade. The underwriters decide who gets them. Do not plan on getting any.</p>
<p><strong>Day one</strong> is an ordinary trade after the stock opens. You pay the market price, which can be well above or below the IPO price. You need a broker that offers US-listed stocks, the ticker in that broker's symbol search, and usually US dollars.</p>
<p>If you trade near the open, a limit order sets the most you will pay. A market order can fill far from the last price you saw.</p>"""

def passed_filing_note(a):
    if a.get("status") == "publicly_filed":
        return ""
    past = []
    for k in filing_key_dates(a):
        ds = k.get("date") or ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds) and ds < TODAY.isoformat():
            past.append(k)
    if not past:
        return ""
    bits = ", ".join(f"{fmt_date(k['date'])} ({e(short_source(k.get('source_name')))})" for k in past)
    return f"<p>Reported public-filing dates that have already passed, with no public S-1 found: {bits}. Later reported dates can still be ahead. None of them are confirmed.</p>"

def listing_section(a):
    ticker, exchange = a.get("ticker"), a.get("exchange")
    if a.get("status") in ("publicly_filed", "roadshow", "priced") and (ticker or exchange):
        ex = e(exchange) if exchange else "not filled in yet"
        tk = e(ticker) if ticker else "not filled in yet"
        price = ""
        if a.get("status") == "publicly_filed":
            price = " The cover page leaves the initial public offering price blank (between $ and $). The shares are not trading."
        return f"<p>The S-1 says Anthropic has applied to list its Class A common stock on the <strong>{ex}</strong> under the proposed symbol <strong>{tk}</strong>.{price}</p>"
    hits = []
    for k in a.get("key_dates") or []:
        low = (k.get("label") or "").lower()
        if any(w in low for w in ("nasdaq", "nyse", "ticker", "exchange")):
            hits.append(f"<li>{fmt_date(k.get('date'))} {dated_badge(bool(k.get('confirmed')))} {e(k.get('label'))} {src(k.get('source_url'), k.get('source_name'))}</li>")
    listed = "<ul>" + "".join(hits) + "</ul>" if hits else "<p>No exchange has been named in our dated sources.</p>"
    tick = f"<p>Ticker: <strong>{e(ticker)}</strong>.</p>" if ticker else "<p>Ticker: <strong>not reported</strong>. We have not found a trading symbol in a company announcement or a news report we trust.</p>"
    return tick + listed

def anth_faq_listing(a):
    if a.get("status") in ("publicly_filed", "roadshow", "priced") and (a.get("ticker") or a.get("exchange")):
        extra = " The price range is not set. ANT is proposed, and the shares are not trading yet." if a.get("status") == "publicly_filed" else ""
        return (f"The S-1 proposes the ticker {a.get('ticker') or 'n/a'} and says Anthropic has applied to list Class A common stock on the {a.get('exchange') or 'n/a'}.{extra}")
    bits = []
    for k in a.get("key_dates") or []:
        low = (k.get("label") or "").lower()
        if "nasdaq" in low or "nyse" in low or "ticker" in low:
            bits.append(f"{k.get('source_name')} ({fmt_date(k.get('date'))}): {k.get('label')}")
    return ("No ticker has been reported. " + " ".join(bits) +
            " Anthropic has not confirmed the exchange. When a public S-1 names an exchange and a ticker, this answer follows those fields.")

def anth_faq_account():
    return ("After a listing on Nasdaq or the NYSE, a common share is generally a qualified investment for a TFSA, RRSP or FHSA, because both exchanges are on Finance Canada's designated list. "
            "Your broker still has to accept the ticker. US tax on dividends can still apply inside a TFSA. The Canada-US treaty exempts dividends paid to a pension arrangement such as an RRSP. "
            "A TFSA is not a pension. This is general information, not tax advice.")

def guide_links(current):
    items = [
        ("/anthropic-ipo/", ANTH_TITLE),
        ("/how-to-buy-a-us-ipo-from-canada/", "How to buy a US IPO from Canada"),
        ("/upcoming-ai-ipos/", "Upcoming AI IPOs"),
        ("/ipo-pipeline/", "Full IPO pipeline"),
        ("/how-to-buy-vcx-in-canada/", "How to buy VCX in Canada"),
        ("/private-ai-funds/", "Listed funds with private AI stakes"),
    ]
    lis = "".join(f'<li><a href="{h}">{e(t)}</a></li>' for h, t in items if h != current)
    return f"<h2>Related on this site</h2><ul>{lis}</ul>"

def edgar_search_line(a):
    if a.get("status") == "publicly_filed":
        return ""
    return f'<p class="small">Name search on {e(format_checked(a.get("edgar_checked_at")))}: SEC company search for Anthropic, form type S-1. {src(EDGAR_ANTH, "EDGAR search")}. A confidential draft does not appear in that search. A filing under a different legal name would not appear in it either.</p>'

def anth_guide_desc(a):
    if a.get("status") == "publicly_filed":
        when = fmt_date(confirmed_public_s1_date(a))
        tk = a.get("ticker") or "ANT"
        return (f"Anthropic filed a public S-1 on {when}. Proposed ticker {tk} on Nasdaq Global Select. "
                "Price range is blank. Reported roadshow timing, and how to buy from Canada.")
    return "No public Anthropic S-1 yet. Reported timing and valuation, plus how Canadians buy a US IPO: brokers, TFSA, RRSP and FX costs."

def anth_lead(a):
    if a.get("status") != "publicly_filed":
        return "Anthropic has not set an IPO price, and the public prospectus is not on EDGAR. Below is what the company has confirmed, what reporters have said, and what someone in Canada can actually do."
    link = s1_edgar_url(a)
    linked = f'<a href="{e(link)}" rel="noopener nofollow" target="_blank">public S-1</a>' if link else "public S-1"
    when = fmt_date(confirmed_public_s1_date(a))
    tk = e(a.get("ticker") or "")
    ex = e(a.get("exchange") or "")
    return (f"Anthropic filed a {linked} on {when}. The proposed ticker is <strong>{tk}</strong>, and the company has applied to list Class A common stock on the {ex}. "
            "The cover page leaves the IPO price range blank. The figures below are from that filing. IFR's Nov 9 roadshow and Nov 20 debut are still reported, not confirmed.")

def anth_buy_first_step(a):
    tk = a.get("ticker")
    if a.get("status") in ("publicly_filed", "roadshow", "priced") and tk:
        return (f"<li><strong>The proposed ticker is {e(tk)}.</strong> It is not trading yet, and the price range is not set. "
                f"Search {e(tk)} in your broker on listing day before you move cash.</li>")
    return "<li><strong>Wait for a real ticker.</strong> None has been reported. Search the symbol in your broker before you move cash.</li>"

def anth_broker_caveat(a):
    tk = a.get("ticker")
    if a.get("status") in ("publicly_filed", "roadshow", "priced") and tk:
        return f"they are not symbol-search checks for {e(tk)}, which is proposed and not listed yet"
    return "they are not symbol-search checks for a ticker that does not exist yet"

def write_moved(old, new, label):
    doc = f"""<!doctype html><html lang="en-CA"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Page moved | {e(SITE)}</title>
<link rel="canonical" href="{e(BASE + new)}">
<meta http-equiv="refresh" content="0; url={e(new)}">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
</head><body>
<p>This page has moved. <a href="{e(new)}">{e(label)}</a>.</p>
</body></html>"""
    write(old, prefix_root_urls(doc))

def anthropic_page():
    """Reads pipeline fields. On S-1 day set status, cik, public_s1_url, ticker, exchange, edgar_checked_at."""
    a = anthropic_item()
    faq, fs = faq_block([
        ("When is the Anthropic IPO date?", anth_faq_when(a)),
        ("Has Anthropic filed an S-1?", anth_faq_filed(a)),
        ("What is Anthropic's valuation?", anth_faq_valuation(a)),
        ("What is Anthropic's ticker?", anth_faq_listing(a)),
        ("Can Canadians buy Anthropic at the IPO price?", anth_faq_ipo_price()),
        ("Can I hold Anthropic in a TFSA or RRSP?", anth_faq_account()),
        ("What does it cost to convert Canadian dollars?", fx_faq_answer()),
        ("Can Canadians buy Anthropic stock before the IPO?", "Not the company itself. ANT is a proposed ticker and is not trading yet. Indirect exposure exists through listed funds that report Anthropic holdings, such as DXYZ and VCX, if your broker offers those US-listed funds. These funds can trade at large premiums or discounts to their last reported NAV. This is general information only, not personalized advice."),
        ("Will Anthropic list on the TSX?", "The S-1 says Anthropic has applied to list Class A common stock on the Nasdaq Global Select Market under ANT. The same prospectus says the offering includes a public offering in Canada, and that the company does not currently intend to list Class A common stock on an exchange outside the United States, including Canada. Nothing in the filing describes a TSX listing."),
    ])
    body = f"""<article><h1>{e(ANTH_TITLE)}</h1>{asof_line()}
{advice_note()}
<p class="lead">{anth_lead(a)}</p>
{s1_box(a)}{edgar_search_line(a)}{passed_filing_note(a)}{newsletter_cta()}
<div class="card status">{badge(a['status'], a.get('status_confirmed', True))}<p>{linkify(a['summary'])}</p></div>
<h2>Timing</h2>
<p>Confirmed items come from Anthropic. Everything else is a news report and can move. Yahoo Finance wrote on Oct 21 that a company using the confidential process has to put the registration on EDGAR at least 15 days before a formal roadshow. That is Yahoo's description of the rule, not a date Anthropic has confirmed. {src("https://finance.yahoo.com/markets/article/anthropic-to-publicly-file-for-ipo-as-early-as-friday-sources-say-135343841.html", "Yahoo Finance")}</p>
{timeline(a)}
<h2>Exchange and ticker</h2>
{listing_section(a)}
<!-- S-1 day: in data/pipeline.json set Anthropic status, cik, public_s1_url, ticker, exchange, edgar_checked_at, then rebuild. This section, the S-1 box and the FAQ read those fields. -->
{valuation_html(a)}
{s1_financials_html(a)}
{financials_table(a)}
{sec_block(a)}
<h2>How a Canadian can buy it</h2>
<p>The same steps for any US listing are on <a href="/how-to-buy-a-us-ipo-from-canada/">how to buy a US IPO from Canada</a>. What follows is the Anthropic version.</p>
{allocation_vs_market_html()}
<h3>What that means for Anthropic</h3>
<p>There is still no deal to join. The S-1 leaves the share count and the price blank. When a broker offers the new issue, it will show in that broker's IPO or new-issue list. Opening an account does not reserve shares.</p>
<h3>Buying after it lists</h3>
<ol class="steps">{anth_buy_first_step(a)}
<li><strong>Use a broker that offers US-listed stocks.</strong> The notes below are from each firm's own pages, checked {fmt_date(CA_BROKERS.get("as_of"))}.</li>
<li><strong>Choose the account</strong> (TFSA, RRSP, FHSA or non-registered) and confirm that broker accepts the ticker there.</li>
<li><strong>Hold US dollars if you can,</strong> so you do not convert on the buy and again on the sell.</li>
<li><strong>Complete Form W-8BEN</strong> if the broker asks for it.</li>
<li><strong>Use a limit order</strong> if you trade on the first day.</li></ol>
<h2>Brokers that offer US-listed stocks</h2>
<p>These are published facts about US-listed trading and currency conversion. They are not a statement that any of these brokers will offer Anthropic shares in the IPO, and {anth_broker_caveat(a)}. {broker_home_link("rbc")} is included here because its own site describes US stock trading. It is not in our fund symbol-search table.</p>
{broker_fact_cards()}
{registered_accounts_html()}
{canadians_exposure(a)}
<h2>Listed funds that report an Anthropic holding</h2>{exposure_list('Anthropic')}
{affiliate_spot('buy US-listed funds like DXYZ and VCX')}
{faq}{guide_links('/anthropic-ipo/')}{newsletter()}</article>"""
    art = article_ld(ANTH_TITLE)
    write("/anthropic-ipo/", layout("/anthropic-ipo/", ANTH_TITLE, anth_guide_desc(a), body, [fs, art], "article", "0.9"))
    write_moved("/anthropic-ipo-date/", "/anthropic-ipo/", ANTH_TITLE)

def how_to_buy_us_ipo_page():
    faq, fs = faq_block([
        ("Can Canadians buy a US IPO at the IPO price?", "Sometimes, and you should not count on it. Questrade says that in most cases a US IPO is filled in the United States and Canadian residents cannot take part. When a deal is offered there, the minimum commitment is $5,000 and the allocation can be cut. RBC's fee schedule says new stock issues, when available, have no commission. Wealthsimple and Qtrade pages we checked do not promise a US IPO allocation. After the stock opens, you buy it like any other US-listed share."),
        ("Which Canadian brokers offer US stocks?", "Wealthsimple, Questrade, RBC Direct Investing and Qtrade each describe US-listed stock trading on their own sites. Whether a specific new ticker is enabled in your account is a symbol search, not something this page can promise."),
        ("Can I hold a US stock in a TFSA or RRSP?", anth_faq_account()),
        ("How much does currency conversion cost?", fx_faq_answer()),
        ("What if the ticker is not in my broker's search?", "Do not send money on the assumption it will appear. Search the symbol on listing day. Our fund table shows the same idea: a US listing is not the same as 'available' at every Canadian broker."),
    ])
    body = f"""<article><h1>How to buy a US IPO from Canada</h1>{asof_line()}
{advice_note()}
<p class="lead">A US initial public offering and the first day of trading are not the same purchase. This page is the practical version for someone with a Canadian brokerage account. The live example right now is <a href="/anthropic-ipo/">the Anthropic IPO</a>.</p>
{newsletter_cta("Get AI IPO filings in one email a week - Subscribe free")}
{allocation_vs_market_html()}
<h2>A workable order of steps</h2>
<ol class="steps"><li><strong>Read the prospectus when it is public.</strong> <a href="/anthropic-ipo/">Anthropic's S-1</a> is on EDGAR, with proposed ticker ANT and a blank price range. Until some other company's S-1 or F-1 is on EDGAR, that company's price, share count and ticker are not set.</li>
<li><strong>Decide whether you even want an allocation.</strong> Check the IPO or new-issue screen inside the broker you already use. If the deal is not listed, you do not have a way in at the IPO price through that firm.</li>
<li><strong>Plan on buying after the open</strong> if the allocation is not offered. That is the path most Canadians actually have.</li>
<li><strong>Pick the account</strong> and confirm a US-listed common share is accepted there. See the TFSA and RRSP notes below.</li>
<li><strong>Get the currency sorted</strong> before the morning of the listing, not during the first volatile prints.</li>
<li><strong>Search the ticker</strong> the broker shows, then use a limit order.</li></ol>
<h2>Brokers that publish US-stock access</h2>
<p>Figures are from each broker's own pages as of {fmt_date(CA_BROKERS.get("as_of"))}. They are not referral links. {e(CA_BROKERS.get("method") or "")}</p>
{broker_fact_cards()}
{registered_accounts_html()}
<h2>A note on the fund checks</h2>
<p>Elsewhere on this site, Questrade, Wealthsimple, IBKR and Qtrade are marked available, not available, or unverified for specific fund tickers such as DXYZ and VCX. Those checks were done inside a logged-in symbol search. They do not tell you whether a future IPO ticker will be there. The method is on the <a href="/private-ai-funds/">funds page</a>.</p>
{affiliate_spot("buy US-listed stocks from Canada")}
{faq}{guide_links("/how-to-buy-a-us-ipo-from-canada/")}{newsletter()}</article>"""
    title = "How to buy a US IPO from Canada"
    desc = "How Canadians can buy a US IPO: the offering versus the first trade, brokers that offer US stocks, TFSA and RRSP rules, and currency conversion costs."
    write("/how-to-buy-a-us-ipo-from-canada/", layout("/how-to-buy-a-us-ipo-from-canada/", title, desc, body, [fs, article_ld(title)], "article", "0.8"))

def upcoming_ai_ipos_page():
    a = anthropic_item()
    along = [it["name"] for it in PIPE.get("items", []) if it.get("status") in ("publicly_filed", "confidentially_filed", "roadshow")]
    along_txt = ", ".join(along) if along else "none"
    faq, fs = faq_block([
        ("Which AI IPOs are furthest along?", f"In this tracker, confidentially filed, publicly filed, or on the roadshow: {along_txt}. Reported rumours and companies with no filing are in the same table, with a different status. Withdrawn deals stay listed so the record is intact."),
        ("Has Anthropic filed a public S-1?", anth_faq_filed(a)),
        ("How does someone in Canada buy one?", "Most buyers here purchase the shares after they open on a US exchange, through a broker that offers US stocks. Getting an allocation at the IPO price is a separate, and often unavailable, step. The walkthrough is the how-to-buy guide. This is general information, not a recommendation."),
        ("Is there a Canadian company on the list?", "Cohere, based in Toronto, is on the pipeline as reported only. No filing date is confirmed."),
    ])
    body = f"""<article><h1>Upcoming AI IPOs</h1>{asof_line()}
{advice_note()}
<p class="lead">Anthropic's public S-1 is on EDGAR (proposed ticker ANT, Nasdaq Global Select Market, price range not set). This hub is for AI companies that are not yet trading, plus the guides for buying a US listing from Canada. The table is the same pipeline as the <a href="/ipo-pipeline/">tracker</a>. Every date in a row links back to its source from the company page. IFR's Nov 9 roadshow and Nov 20 debut for Anthropic are still reported, not confirmed.</p>
{newsletter_cta("Get the week's AI IPO filings - Subscribe free")}
<h2>Start here</h2>
<ul>
<li><a href="/anthropic-ipo/">{e(ANTH_TITLE)}</a></li>
<li><a href="/how-to-buy-a-us-ipo-from-canada/">How to buy a US IPO from Canada</a></li>
<li><a href="/openai-ipo/">OpenAI IPO</a></li>
<li><a href="/ipo-pipeline/">Full pipeline, with the status legend</a></li>
<li><a href="/private-ai-funds/">Listed funds that hold private AI stakes</a> (DXYZ, VCX, RVI, ARKVX)</li>
<li><a href="/how-to-buy-vcx-in-canada/">How to buy VCX in Canada</a></li>
</ul>
<h2>The pipeline</h2>
<p class="muted">Status comes from an SEC filing or a company announcement. A <span class="tag rep">reported</span> tag is a news report, not a confirmation.</p>
{pipeline_table()}
{faq}{guide_links("/upcoming-ai-ipos/")}{newsletter()}</article>"""
    title = "Upcoming AI IPOs"
    desc = "Upcoming AI IPOs for Canadian investors: Anthropic, OpenAI and the rest of the pipeline, plus guides on how to buy a US listing."
    write("/upcoming-ai-ipos/", layout("/upcoming-ai-ipos/", title, desc, body, [fs, article_ld(title)], "article", "0.8"))

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
    write("/openai-ipo/", layout("/openai-ipo/", "OpenAI IPO: date, S-1 status & how to invest (2026)", "OpenAI confidentially filed for an IPO in June 2026 and has pointed toward 2027. Status, sources, valuation and listed funds that hold OpenAI, for Canadian investors.", body, [fs, article_ld("OpenAI IPO: the confidential S-1 and the 2027 question")], "article", "0.9"))

def vcx_canada_page():
    f = fund_by("VCX"); n = f["nav"]
    brows = "".join(f"<tr><td>{broker_home_link(k, nm)}</td><td>{broker_cell(f['brokers'].get(k))}</td></tr>" for k, nm in BROKER_NAMES)
    faq, fs = faq_block([
        ("Can you buy VCX in Canada?", "VCX trades on the NYSE, so in principle any Canadian broker that offers US-listed closed-end funds can carry it. Questrade and IBKR offered it in their symbol search when checked on Oct 20, 2026; Wealthsimple did not. We have not verified Qtrade, so check the symbol search in your account."),
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
    write("/how-to-buy-vcx-in-canada/", layout("/how-to-buy-vcx-in-canada/", "How to buy VCX in Canada (Fundrise Innovation Fund)", "How Canadians can buy VCX, the NYSE-listed fund holding Anthropic, OpenAI and Databricks: brokers, USD, TFSA/RRSP, premium to NAV and risks.", body, [fs, article_ld("How to buy VCX (Fundrise Innovation Fund) in Canada")], "article", "0.9"))

def dxyz_page():
    f = fund_by("DXYZ"); n = f["nav"]
    hist = "".join(f"<tr><td>{fmt_date(h['date'])}</td><td>{money(h['value'])}</td><td class='srcs'>{src(h['source_url'], h['source_name'])}</td></tr>" for h in f.get("nav_history", []))
    faq, fs = faq_block([
        ("What is DXYZ's premium to NAV?", f"At {money(f['price'])} (latest delayed price) vs the last reported NAV of {money(n['value'])} (as of {fmt_date(n['date'])}), DXYZ is at {pct(f['premium'], neutral=True)}. A negative number is a discount."),
        ("How often does DXYZ report NAV?", "Destiny Tech100 reports NAV in its periodic SEC filings (N-CSR / N-CSRS) and quarterly results releases, so the last reported NAV is often weeks or months old."),
        ("What AI companies does DXYZ hold?", "Per its website (as of June 30, 2026): Anthropic 14.4%, SpaceX 10.6% (which now includes xAI), OpenAI 2.6%, OpenEvidence 2.1%, Shield AI 1.8%, Databricks 1.2%."),
        ("Can I buy DXYZ in Canada?", "DXYZ is NYSE-listed. It was available in Questrade's, Wealthsimple's, and IBKR's symbol search when checked on Oct 20, 2026. Availability at Qtrade is unverified on our side; check your broker's symbol search."),
    ])
    body = f"""<article><h1>DXYZ premium to NAV (Destiny Tech100)</h1>{asof_line()}
<div class="stats"><div class="stat"><span class="k">Latest price</span><span class="v">{money(f['price'])}</span><span class="muted small">{e(fmt_ts(f.get('price_time')))}</span></div>
<div class="stat"><span class="k">Last reported NAV</span><span class="v">{money(n['value'])}</span><span class="muted small">as of {fmt_date(n['date'])}</span></div>
<div class="stat"><span class="k">Premium / discount</span><span class="v">{pct(f['premium'], neutral=True)}</span><span class="muted small">vs last reported NAV</span></div></div>
<p>NAV source: {src(n['source_url'], n['source_name'])}. The premium is computed as price ÷ last reported NAV − 1. Because the NAV is months old and mostly private-company marks, the "true" premium today is unknown.</p>
<h2>Reported NAV per share history</h2><div class="tw"><table><thead><tr><th>NAV date</th><th>NAV / share</th><th>Source</th></tr></thead><tbody>{hist}</tbody></table></div>
<h2>Top AI holdings</h2><ul>{''.join(f"<li>{e(h['name'])}: {e(h['weight'])}</li>" for h in f['ai_holdings'])}</ul><p class="small">{src(f['holdings_source_url'], f['holdings_source_name'])}, as of {fmt_date(f['holdings_as_of'])}</p>
{affiliates('buy DXYZ')}{faq}{newsletter()}</article>"""
    write("/dxyz-premium-to-nav/", layout("/dxyz-premium-to-nav/", "DXYZ premium to NAV: live vs last reported NAV", "Destiny Tech100 (DXYZ) premium or discount to its last reported NAV, NAV history from SEC filings, and its Anthropic, SpaceX/xAI and OpenAI holdings.", body, [fs, article_ld("DXYZ premium to NAV (Destiny Tech100)")], "article", "0.9"))

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
            parts.append(f"<div class='card status'>{badge(it['status'], it.get('status_confirmed', True))}<p>{linkify(it.get('summary',''))}</p></div><h2>Key dates</h2>{timeline(it)}")
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
<h2>Canadian brokers</h2><div class='tw'><table><tbody>{''.join(f"<tr><td>{broker_home_link(k, nm)}</td><td>{broker_cell(f['brokers'].get(k))}</td></tr>" for k, nm in BROKER_NAMES)}</tbody></table></div><p class='small'>{e(f.get('broker_note',''))}</p>""")
        else:
            parts.append(f"<h2>Listed funds holding {e(name)}</h2>{exposure_list(name.split(' (')[0])}")
            if slug == "anthropic":
                parts.append("<p><a href='/anthropic-ipo/'>Anthropic IPO: date, valuation, and how to buy it in Canada</a></p>")
            elif slug == "openai":
                parts.append("<p>See <a href='/upcoming-ai-ipos/'>upcoming AI IPOs</a> and <a href='/how-to-buy-a-us-ipo-from-canada/'>how to buy a US IPO from Canada</a>.</p>")
            sec_html = edgar_list(it.get("cik"))
            if it.get("public_s1_url"):
                sec_html = f'<p><a href="{e(it["public_s1_url"])}" rel="noopener nofollow" target="_blank">Public S-1 on EDGAR</a> (CIK {e(it.get("cik"))}).</p>' + sec_html
            parts.append(f"<h2>SEC filings</h2>{sec_html}")
        parts.append(affiliates()); parts.append(newsletter())
        desc = (it.get("summary") or f"{name}: IPO status, price since listing, lock-ups, SEC filings and listed-fund exposure.")[:155]
        headline = f"{name} IPO: status, dates & how to invest" if not is_fund else f"{it['ticker']} ({name}): NAV, premium & holdings"
        write(f"/company/{slug}/", layout(f"/company/{slug}/", headline, desc, "<article>" + "".join(parts) + "</article>", [article_ld(headline)], priority="0.6"))

def static_pages():
    write("/about/", layout("/about/", "About", f"About {SITE}", f"<article><h1>About {e(SITE)}</h1><p>{e(SITE)} is an independent tracker of AI IPOs and pre-IPO exposure, built in {e(CFG['location'])} for investors, with a focus on what Canadians can actually access.</p><p>Owner: {e(CFG['owner'])}.</p><p>The data is kept in open JSON files and refreshed by scripts; every number links to its source. If you spot an error, tell us and we will fix it.</p>{newsletter()}</article>", priority="0.3"))
    write("/disclaimer/", layout("/disclaimer/", "Disclaimer & affiliate disclosure", "Not financial advice. Affiliate disclosure.", f"<article><h1>Disclaimer</h1><p><strong>Not financial advice.</strong> All content is general information only and is not investment, tax or legal advice, nor an offer or solicitation to buy or sell any security. IPO timing and terms reported in the media are frequently wrong or change. Prices are delayed and may be inaccurate. Past performance is not indicative of future results. Consult a registered professional.</p><h2>Affiliate disclosure</h2><p>Some links may earn us a commission if you open an account. This does not influence the data or which brokers we say carry a fund. See <a href='/disclosure/'>how we make money</a>.</p>{newsletter()}</article>", priority="0.2"))
    srcs = "".join(f"<li>{x}</li>" for x in ["SEC EDGAR submissions API &amp; full-text search (filings, IPO prices from Form 424B4, lock-up terms)", "Company announcements (Anthropic, OpenAI, Waymo)", "Fund websites and filings (Destiny, Fundrise, Robinhood Ventures, ARK Funds)", "Renaissance Capital AI IPO tracker (pipeline candidates, AI ratings)", "Yahoo Finance public chart endpoint (delayed prices), Stooq fallback", "News reports (Reuters, Bloomberg, CNBC, IFR) for reported items, always labelled 'reported'"])
    write("/methodology/", layout("/methodology/", "Methodology & sources", "How the AI IPO data is sourced, verified and refreshed.", f"""<article><h1>Methodology &amp; sources</h1><ul>{srcs}</ul>
<h2>Rules</h2><ul><li>No invented numbers. Unknown values are shown as n/a.</li><li>Status is 'confirmed' only when it comes from an SEC filing or the company itself; media items are labelled 'reported'.</li><li>Lock-up dates come from the prospectus. When the prospectus gives "N days after the date of this prospectus", we compute the date and label it 'computed'.</li><li>Premium/discount is always vs the <em>last reported</em> NAV, shown with its date.</li><li>Broker availability stays 'unverified' until confirmed in the broker's own symbol search, with the check date recorded.</li></ul>
<h2>Refresh</h2><p>Prices: every market day. EDGAR filings and fund NAV checks: daily. Reported news: reviewed by an editor or AI agent, with sources. The Anthropic public-S-1 "last checked" time is <code>edgar_checked_at</code> in pipeline.json (SEC blocks the GitHub-hosted refresh). On the day the public S-1 appears, set that row's status to publicly_filed, and fill in cik, public_s1_url, ticker and exchange from the filing. The Anthropic guide reads those fields.</p>{newsletter()}</article>""", priority="0.3"))
    # data index
    files = "".join(f"<li><a href='/data/{n}'>{n}</a></li>" for n in DATA_FILES)
    write("/data/", layout("/data/", "Open data (JSON)", "Download the AI IPO pipeline, returns, lock-ups and fund NAV data as JSON.", f"<article><h1>Open data</h1><p>The JSON files behind this site. Free to use with attribution.</p><ul>{files}</ul>{newsletter()}</article>", priority="0.3"))
    write("/disclosure/", layout("/disclosure/", "How we make money", "How AI IPO Watch may earn referral commissions, and what that does not change.", f"""<article><h1>How we make money</h1>
<ul><li>This site may earn referral commissions from some brokers and financial services linked on the site, at no extra cost to readers.</li>
<li>Opinions are our own and not those of any broker.</li>
<li>Commissions never change the data, or which brokers we say carry a fund.</li>
<li>Everything here is general information only, not investment advice.</li>
<li>We are not registered with any securities regulator.</li></ul>
<p>Affiliate links are off until a real URL is set in the site config. Pages that show one also show a short commission note.</p>
<p>See also the <a href="/disclaimer/">disclaimer</a>.</p>
<h2>Privacy</h2>
<p>We use GoatCounter, a privacy-friendly analytics tool that doesn't use cookies or track you across sites, to count page views.</p>
{newsletter()}</article>""", priority="0.2"))
    (OUT / "404.html").write_text(layout("/404.html", "Page not found", "Page not found", "<h1>Page not found</h1><p><a href='/'>Back to the tracker</a></p>" + newsletter()))
    PAGES.pop()  # don't list 404 in sitemap

def assets_and_seo():
    shutil.copytree(ROOT / "src" / "assets", OUT / "assets", dirs_exist_ok=True)
    (OUT / "data").mkdir(exist_ok=True)
    for n in DATA_FILES:
        if (ROOT / "data" / n).exists(): shutil.copy(ROOT / "data" / n, OUT / "data" / n)
    lastmod = TODAY.isoformat()
    urls = "".join(f"<url><loc>{BASE}{p}</loc><lastmod>{lastmod}</lastmod><priority>{pr}</priority></url>" for p, pr in PAGES)
    (OUT / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n")
    (OUT / ".nojekyll").write_text("")
    # Apex custom domain. www is a DNS CNAME to the GitHub Pages host.
    # Actions deploys only keep the custom domain if this file is in the artifact.
    (OUT / "CNAME").write_text("ipowatch.ca\n")

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
    if urlparse(BASE).hostname == "ipowatch.ca":
        published = [home, (OUT / "sitemap.xml").read_text(), robots]
        published += [p.read_text() for p in OUT.rglob("*.html")]
        blob = "\n".join(published)
        if "/ai-ipo-watch/" in blob or "github.io" in blob:
            bad.append("old github.io /ai-ipo-watch URL still in published HTML, sitemap, or robots.txt")
        if (OUT / "CNAME").read_text().strip() != "ipowatch.ca":
            bad.append("CNAME must be ipowatch.ca")
    if bad:
        raise SystemExit("subpath check failed:\n" + "\n".join(bad))
    anth = (OUT / "anthropic-ipo" / "index.html").read_text()
    guide = (OUT / "how-to-buy-a-us-ipo-from-canada" / "index.html").read_text()
    hub = (OUT / "upcoming-ai-ipos" / "index.html").read_text()
    moved = (OUT / "anthropic-ipo-date" / "index.html").read_text()
    disc = (OUT / "disclosure" / "index.html").read_text()
    sm = (OUT / "sitemap.xml").read_text()
    # Structural only. Do not pin dates or "not filed" copy: filing day is a data edit.
    checks = {
        "s1 box": "S-1 filed?" in home and "S-1 filed?" in anth and "Public S-1 on EDGAR:" in anth and "Last checked" in anth,
        "old oct 26 copy": "public S-1 reported for Oct 26" not in home and "public filing reported for Oct 26" not in anth,
        "financials": "Financials (reported)" in anth and "Financials from the S-1" in anth and "$80,748 million" in anth and "72,388 million" in anth,
        "s1 filed copy": "000162828026067168" in anth and ">ANT<" in anth and "price range" in anth.lower() and "What is Anthropic's ticker?" in anth and "the public prospectus is not on EDGAR" not in anth and "which has no ticker" not in anth and "None has been reported" not in anth and "Nasdaq Global Select" in hub and "Proposed ticker ANT" in home and "not set.." not in anth and "sx1.htm." not in anth,
        "exposure": "How Canadians can get exposure" in anth and "Can Canadians buy Anthropic at the IPO price?" in anth,
        "cta": "Get the S-1 breakdown the day it's filed - Subscribe free" in home and "Get the S-1 breakdown the day it's filed - Subscribe free" in anth,
        "subscribe nav": ">Subscribe</a>" in home,
        "disclosure": "How we make money" in disc and "not registered with any securities regulator" in disc,
        "no placeholder buttons": 'href="#"' not in home and 'href="#"' not in anth,
        "ws hidden unless linked": (WS_OPINION in anth) == ("data-affiliate=\"wealthsimple\"" in anth),
        "article dates": '"datePublished"' in anth and '"dateModified"' in anth,
        "updated": "Updated " in home and " MT" in home,
        "impact verification": "<meta name='impact-site-verification' value='0bb4882c-bc98-4a99-8bdc-d1fdd926ec95'>" in home,
        "goatcounter": '<script data-goatcounter="https://ipowatch.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>' in home and '<script data-goatcounter="https://ipowatch.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>' in anth,
        "privacy note": "We use GoatCounter, a privacy-friendly analytics tool that doesn't use cookies or track you across sites, to count page views." in disc,
        "guide canonicals": all(f'href="{BASE}{p}"' in page for p, page in (
            ("/anthropic-ipo/", anth), ("/how-to-buy-a-us-ipo-from-canada/", guide), ("/upcoming-ai-ipos/", hub))),
        "guide sitemap": all(f"<loc>{BASE}{p}</loc>" in sm for p in ("/anthropic-ipo/", "/how-to-buy-a-us-ipo-from-canada/", "/upcoming-ai-ipos/")),
        "old slug redirected": f'href="{BASE}/anthropic-ipo/"' in moved and "http-equiv=\"refresh\"" in moved and f"<loc>{BASE}/anthropic-ipo-date/</loc>" not in sm,
        "faq schema": all('"FAQPage"' in page for page in (anth, guide, hub)),
        "twitter site": 'name="twitter:site" content="@TickerHotTakes"' in anth,
        "newsletter on guides": all('id="newsletter"' in page and "Not financial advice." in page for page in (anth, guide, hub)),
        "homepage guide links": all(h in home for h in ("/anthropic-ipo/", "/how-to-buy-a-us-ipo-from-canada/", "/upcoming-ai-ipos/")),
        "affiliate slot neutral": 'data-affiliate-slot="pending"' in anth and 'data-affiliate-slot="pending"' in guide and "Referral links are not in use." in anth,
        "broker homepages": "https://www.wealthsimple.com/en-ca" in anth and "https://www.rbcdirectinvesting.com/" in guide and "https://www.qtrade.ca/en/investor.html" in guide,
    }
    for name in ("methodology", "data", "disclaimer"):
        checks[f"newsletter {name}"] = 'id="newsletter"' in (OUT / name / "index.html").read_text()
    checks["newsletter 404"] = 'id="newsletter"' in (OUT / "404.html").read_text()
    if not live_affiliates() and 'data-affiliate=' in home + anth:
        checks["affiliates hidden"] = False
    missed = [k for k, ok in checks.items() if not ok]
    if missed:
        raise SystemExit("content check failed:\n" + "\n".join(missed))

def main():
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir()
    home(); section_pages(); anthropic_page(); how_to_buy_us_ipo_page(); upcoming_ai_ipos_page(); openai_page(); vcx_canada_page(); dxyz_page(); company_pages(); static_pages(); assets_and_seo()
    assert_subpath()
    print(f"Built {len(PAGES)} pages into {OUT}")

if __name__ == "__main__":
    main()
