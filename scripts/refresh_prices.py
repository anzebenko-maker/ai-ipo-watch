#!/usr/bin/env python3
"""Refresh latest prices for every ticker in data/ipos.json and data/funds.json.
Free source: Yahoo Finance public chart endpoint (no key). Fallback: Stooq CSV.
Writes data/prices.json. Never invents a value: failures are stored as null with an error."""
import json, sys, time, urllib.request, urllib.error, datetime, pathlib, csv, io
ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0"  # Yahoo rate-limits some full browser UA strings; the short form works

def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                time.sleep(3 * (i + 1)); continue
            if e.code == 429 and "query1." in url:
                url = url.replace("query1.", "query2."); continue
            raise

def yahoo(sym):
    d = json.loads(fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"))
    res = d["chart"]["result"][0]; m = res["meta"]
    price = m.get("regularMarketPrice")
    ts = m.get("regularMarketTime")
    if price is None:
        raise ValueError("no price")
    return {"price": round(float(price), 4), "currency": m.get("currency"),
            "price_time": datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if ts else None,
            "exchange": m.get("fullExchangeName"), "source": "Yahoo Finance chart API",
            "source_url": f"https://finance.yahoo.com/quote/{sym}"}

def stooq(sym):
    s = sym.lower().replace(".hk", ".hk") if "." in sym else sym.lower() + ".us"
    rows = list(csv.DictReader(io.StringIO(fetch(f"https://stooq.com/q/l/?s={s}&f=sd2t2ohlcv&h&e=csv"))))
    c = rows[0].get("Close")
    if not c or c == "N/D":
        raise ValueError("no stooq price")
    return {"price": float(c), "currency": None, "price_time": f"{rows[0]['Date']}T{rows[0]['Time']}",
            "source": "Stooq", "source_url": f"https://stooq.com/q/?s={s}"}

def first_open(sym):
    """Opening price on the first trading day (used for direct listings, which have no IPO price)."""
    d = json.loads(fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"))
    ftd = d["chart"]["result"][0]["meta"].get("firstTradeDate")
    if not ftd:
        return None
    h = json.loads(fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={ftd}&period2={ftd + 5*86400}&interval=1d"))
    r = h["chart"]["result"][0]
    opens = r["indicators"]["quote"][0]["open"]
    for t, o in zip(r.get("timestamp", []), opens):
        if o:
            return {"first_open": round(float(o), 4), "first_trade_date": datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d")}
    return None

def tickers():
    out = {}
    for fn in ("ipos.json", "funds.json"):
        for row in json.loads((ROOT / "data" / fn).read_text())["items"]:
            sym = row.get("price_symbol") or row.get("ticker")
            if sym:
                out[row["ticker"]] = (sym, row.get("listing_type"))
    return out

def main():
    old_path = ROOT / "data" / "prices.json"
    old = json.loads(old_path.read_text()).get("prices", {}) if old_path.exists() else {}
    prices = {}
    for tk, (sym, ltype) in tickers().items():
        errors = []
        for fn in (yahoo, stooq):
            try:
                prices[tk] = fn(sym); break
            except Exception as e:
                errors.append(f"{fn.__name__}: {e}")
        else:
            prev = old.get(tk, {})
            if prev.get("price") is not None:
                # keep last good quote, clearly flagged as stale (never fabricate)
                prices[tk] = dict(prev, stale=True, errors=errors)
            else:
                prices[tk] = {"price": None, "errors": errors}
        if ltype == "direct_listing" and "first_open" in old.get(tk, {}):
            prices[tk].setdefault("first_open", old[tk]["first_open"])
            prices[tk].setdefault("first_trade_date", old[tk].get("first_trade_date"))
        elif ltype == "direct_listing":
            try:
                fo = first_open(sym)
                if fo:
                    prices[tk].update(fo)
            except Exception as e:
                prices[tk]["first_open_error"] = str(e)
        print(tk, prices[tk].get("price"), prices[tk].get("price_time"))
        time.sleep(0.4)
    out = {"as_of": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "note": "Delayed quotes from free public endpoints. Not for trading.", "prices": prices}
    (ROOT / "data" / "prices.json").write_text(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
