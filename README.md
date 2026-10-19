# AI IPO Watch (working name) — MVP

Static website tracking AI IPOs and pre-IPO exposure for investors, with a Canadian angle.
Owner: Anze Benko (Edmonton, AB). Newsletter working name: **AI Float Weekly**.

## Quick start
```bash
./scripts/refresh_all.sh                 # refresh prices + fund NAV checks + EDGAR, then build
# Links are rooted at /ai-ipo-watch/ so the preview host must serve that prefix:
mkdir -p /tmp/ai-ipo-watch-preview
ln -sfn "$(pwd)/public" /tmp/ai-ipo-watch-preview/ai-ipo-watch
python3 -m http.server 8080 --directory /tmp/ai-ipo-watch-preview
# preview at http://localhost:8080/ai-ipo-watch/
```
No dependencies beyond Python 3.9+ (standard library only). Optional: `scripts/screenshot.py` needs Playwright
(`python3 -m venv .venv && .venv/bin/pip install playwright`) and uses the system Chrome.

## Change the site name / URL / newsletter / affiliate links
Everything brand-related is in **`site.config.json`** (site_name, base_url, newsletter_form_action, affiliate URLs).
After editing, run `python3 scripts/make_og.py && python3 scripts/build.py` (regenerates the OG image too).

## Layout
```
site.config.json        one place for name, domain, newsletter action, affiliate URLs
data/pipeline.json      IPO pipeline (status, key dates with confirmed/reported flag, sources)   [curated]
data/ipos.json          recent AI listings: IPO price from 424B4, listing type                   [curated]
data/lockups.json       lock-up terms from prospectuses (dates computed at build)               [curated]
data/funds.json         DXYZ/VCX/RVI/ARKVX: NAV + date + source, AI holdings, broker status     [curated + ARKVX auto]
data/prices.json        latest delayed prices (+ first-day open for direct listings)            [generated]
data/edgar.json         SEC filings per CIK + watchlist search for unlisted filers              [generated]
data/fund_alerts.json   newer fund filings than the stored NAV date -> needs review              [generated]
scripts/refresh_prices.py   Yahoo Finance chart endpoint (free), Stooq fallback; keeps last good value, flags stale
scripts/refresh_funds.py    ARKVX NAV from ark-funds.com; EDGAR check for newer N-CSR/N-CSRS/NPORT-P
scripts/refresh_edgar.py    SEC submissions API + EDGAR full-text watchlist (Anthropic, OpenAI, ...)
scripts/build.py            generator: data -> public/ (HTML, sitemap.xml, robots.txt, /data/*.json)
scripts/make_og.py          renders src/assets/og-default.png with headless Chrome
scripts/screenshot.py       full-page screenshot (Playwright + system Chrome)
scripts/refresh_all.sh      run everything
src/assets/                 style.css, app.js, favicon.svg, og-default.png
public/                     build output — this folder is what you deploy
AGENTS.md                   rules for the AI agent that maintains the data
```

## Deploy
GitHub Pages: https://anzebenko-maker.github.io/ai-ipo-watch/ via `.github/workflows/refresh.yml`.

The workflow runs on every push to `main`, on manual dispatch, and daily at 22:30 UTC. Each run refreshes prices, ARK Venture NAV, and the SEC EDGAR watch, rebuilds `public/`, commits any changed `data/*.json` back to `main`, and deploys. A failed refresh does not block deploying the last good data. `public/` is gitignored; Actions builds it.

The EDGAR User-Agent is the repository variable `EDGAR_UA`, or `AI IPO Watch anzebenko-maker@users.noreply.github.com` when that variable is unset.

`actions/configure-pages` is called with `enablement: true`, but the default `GITHUB_TOKEN` usually cannot turn Pages on. If the first deploy fails, set **Settings → Pages → Build and deployment → Source** to **GitHub Actions**, then re-run the workflow.
