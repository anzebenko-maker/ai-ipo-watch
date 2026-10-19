#!/usr/bin/env bash
# One-shot refresh: prices -> fund NAV checks -> EDGAR filings/watchlist -> rebuild site.
# Safe to run from cron or CI. Each step fails soft so one bad source never blanks the site.
set -u
cd "$(dirname "$0")/.."
export EDGAR_UA="${EDGAR_UA:-AI IPO Watch anzebenko-maker@users.noreply.github.com}"   # override with a real contact email
python3 scripts/refresh_prices.py || echo "WARN: price refresh failed (previous prices kept)"
python3 scripts/refresh_funds.py  || echo "WARN: fund refresh failed"
python3 scripts/refresh_edgar.py  || echo "WARN: EDGAR refresh failed"
python3 scripts/build.py
echo "Review data/fund_alerts.json and the ALERT lines above for anything needing a manual/agent update."
