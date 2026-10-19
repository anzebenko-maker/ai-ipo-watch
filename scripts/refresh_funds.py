#!/usr/bin/env python3
"""Refresh fund NAV data where it can be done safely and automatically.

- ARKVX: daily NAV from ARK's public fund page API + top holdings CSV (official ARK sources).
- DXYZ / VCX / RVI: NAVs are quarterly and arrive in SEC filings (N-CSR, N-CSRS, NPORT-P,
  424B prospectus supplements). This script does NOT guess a NAV. It checks EDGAR for any
  filing newer than the NAV date stored in data/funds.json and writes data/fund_alerts.json
  so a human or AI agent can read the filing and update funds.json with a source link.
"""
import json, re, os, csv, io, time, datetime, pathlib, urllib.request
ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
SEC_UA = os.environ.get("EDGAR_UA", "AI IPO Watch anzebenko-maker@users.noreply.github.com")
NAV_FORMS = {"N-CSR", "N-CSRS", "NPORT-P", "424B2", "424B3", "424B5", "8-K"}

def get(url, ua=WEB_UA):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")

def arkvx(fund):
    j = json.loads(get("https://www.ark-funds.com/api/venture/nav-historical-change/1009"))
    view = j.get("view", "")
    nav = re.search(r"NAV\s*<span>\s*\$([\d.,]+)", re.sub(r"\s+", " ", view))
    asof = re.search(r"As of (\d{2}/\d{2}/\d{4})", view)
    if nav and asof:
        m, d, y = asof.group(1).split("/")
        fund["nav"].update({"value": float(nav.group(1).replace(",", "")), "date": f"{y}-{m}-{d}", "verified": True})
        print("ARKVX NAV", fund["nav"]["value"], fund["nav"]["date"])
    try:
        rows = list(csv.DictReader(io.StringIO(get("https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_VENTURE_FUND_ARKVX_HOLDINGS.csv"))))
        if rows:
            print("ARKVX holdings CSV columns:", list(rows[0].keys())[:8], "(top holdings list left for review)")
    except Exception as e:
        print("ARKVX holdings CSV not fetched:", e)

def edgar_alerts(fund):
    cik = fund.get("cik")
    if not cik:
        return []
    d = json.loads(get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", SEC_UA))
    r = d["filings"]["recent"]; out = []
    for i, form in enumerate(r["form"]):
        if form in NAV_FORMS and r["filingDate"][i] > fund["nav"]["date"]:
            acc = r["accessionNumber"][i].replace("-", "")
            out.append({"form": form, "filed": r["filingDate"][i], "period": r["reportDate"][i],
                        "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{r['primaryDocument'][i]}"})
    time.sleep(0.3)
    return out

def main():
    p = ROOT / "data" / "funds.json"
    data = json.loads(p.read_text())
    alerts = {}
    for f in data["items"]:
        try:
            if f["ticker"] == "ARKVX":
                arkvx(f)
            else:
                a = [x for x in edgar_alerts(f) if x["form"] in ("N-CSR", "N-CSRS", "NPORT-P") and (x["period"] or "") > f["nav"]["date"]]
                if a:
                    alerts[f["ticker"]] = {"current_nav_date": f["nav"]["date"], "newer_filings": a,
                                           "action": "Read the filing, update nav.value/date/source_url in data/funds.json"}
        except Exception as e:
            print("ERR", f["ticker"], e)
    data["as_of"] = datetime.date.today().isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    (ROOT / "data" / "fund_alerts.json").write_text(json.dumps({"checked": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "alerts": alerts}, indent=1))
    print("alerts:", list(alerts) or "none")

if __name__ == "__main__":
    main()
