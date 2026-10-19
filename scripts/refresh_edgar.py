#!/usr/bin/env python3
"""Refresh SEC EDGAR filing links for every company in data/pipeline.json and data/ipos.json
that has a `cik`. Writes data/edgar.json. Free, no API key. SEC asks for a descriptive
User-Agent with contact info: set EDGAR_UA env var (e.g. "AI IPO Watch you@yourdomain.com")."""
import json, os, sys, time, urllib.request, urllib.parse, datetime, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = os.environ.get("EDGAR_UA", "AI IPO Watch anzebenko-maker@users.noreply.github.com")
FORMS = {"S-1", "S-1/A", "F-1", "F-1/A", "424B4", "424B1", "DRS", "DRS/A", "RW", "EFFECT", "N-2", "N-2/A", "N-CSR", "N-CSRS", "NPORT-P"}

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def ciks():
    out = {}
    for fn in ("pipeline.json", "ipos.json", "funds.json"):
        p = ROOT / "data" / fn
        if not p.exists():
            continue
        for row in json.loads(p.read_text())["items"]:
            if row.get("cik"):
                out[str(int(row["cik"]))] = row.get("name")
    return out

def main():
    result = {"as_of": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
              "source": "https://www.sec.gov/cgi-bin/browse-edgar (submissions API data.sec.gov)", "companies": {}}
    for cik, name in ciks().items():
        try:
            d = get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        except Exception as e:
            print("ERR", cik, name, e, file=sys.stderr); continue
        r = d["filings"]["recent"]
        filings = []
        for i, form in enumerate(r["form"]):
            if form in FORMS:
                acc = r["accessionNumber"][i]
                doc = r["primaryDocument"][i]
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}" if doc else \
                      f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
                filings.append({"form": form, "date": r["filingDate"][i], "url": url})
        result["companies"][cik] = {"name": d.get("name"), "tickers": d.get("tickers"),
            "edgar_page": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik):010d}",
            "filings": filings[:25]}
        print(f"{name}: {len(filings)} relevant filings")
        time.sleep(0.25)  # stay well under SEC's 10 req/s limit
    # Watch list: pipeline companies without a CIK yet (e.g. confidential filers like Anthropic/OpenAI).
    # EDGAR full-text search for their legal name in registration forms. A hit = review and update pipeline.json.
    result["watch"] = {}
    pipe = json.loads((ROOT / "data" / "pipeline.json").read_text())["items"]
    since = (datetime.date.today() - datetime.timedelta(days=120)).isoformat()
    for row in pipe:
        if row.get("cik") or not row.get("legal_name"):
            continue
        q = urllib.parse.quote(f'"{row["legal_name"]}"')
        url = (f"https://efts.sec.gov/LATEST/search-index?q={q}&forms=S-1,S-1/A,F-1,F-1/A,424B4"
               f"&dateRange=custom&startdt={since}&enddt={datetime.date.today().isoformat()}")
        try:
            hits = get(url).get("hits", {}).get("hits", [])
        except Exception as e:
            result["watch"][row["slug"]] = {"error": str(e)}; continue
        own = [h["_source"] for h in hits if any(row["name"].lower() in n.lower() for n in h["_source"].get("display_names", []))]
        result["watch"][row["slug"]] = {"query": row["legal_name"], "own_filings_found": [
            {"filer": s_["display_names"][0], "form": s_["form"], "date": s_["file_date"], "adsh": s_["adsh"]} for s_ in own[:5]],
            "mentions_in_other_filings": len(hits) - len(own)}
        if own:
            print(f"ALERT: {row['name']} appears as a filer of {own[0]['form']} on {own[0]['file_date']} - update pipeline.json")
        time.sleep(0.3)
    (ROOT / "data" / "edgar.json").write_text(json.dumps(result, indent=1))

if __name__ == "__main__":
    main()
