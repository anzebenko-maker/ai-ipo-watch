# Rules for AI agents maintaining AI IPO Watch data

1. **Never invent numbers.** Every value needs a real source URL and an as-of date. Unknown = `null` (renders as n/a).
2. **Confirmed vs reported.** `confirmed: true` only for SEC filings or the company's own announcement. Media reports
   (Reuters, Bloomberg, IFR, CNBC...) are `confirmed: false` and must say "(reported)" in the label.
   Pipeline `status: "reported"` = only media reports exist.
3. **Status transitions** (pipeline.json): reported → confidentially_filed (company Rule 135 notice) → publicly_filed
   (S-1/F-1 on EDGAR; add `cik`) → roadshow (S-1/A with price range) → priced (424B4). When priced, add the company to
   ipos.json with `offer_price` from the 424B4 cover, and add its lock-up terms to lockups.json.
4. **Lock-ups:** copy the prospectus wording. If it says "N days after the date of this prospectus", store
   `prospectus_date` + `days` and leave `date` null — build.py computes and labels it "computed".
5. **Fund NAVs:** only update `nav.value/date` from the fund's filing or website. Premium is always "vs last reported NAV".
6. **Brokers:** keep `"unverified"` unless confirmed in the broker's own symbol search; then set
   `{"status": "available"|"not_available", "checked": "YYYY-MM-DD", "how": "..."}`.
7. After edits: `python3 scripts/build.py`. Check `data/fund_alerts.json` and ALERT lines from `refresh_edgar.py`.

## Daily loop
```
./scripts/refresh_all.sh
# then: read ALERTs / fund_alerts.json, open the linked filings, update the curated JSON, rebuild
```
## Analytics
Every page loads GoatCounter from the shared layout (`https://ipowatch.goatcounter.com/count`, script `//gc.zgo.at/count.js`). It does not use cookies or track people across sites. The privacy note is on `/disclosure/`. Do not add another analytics script.

Watch items right now (Oct 21, 2026): Anthropic public S-1 (reported as early as Oct 23, Yahoo, or Oct 26, IFR). When it lands, set Anthropic `status` to `publicly_filed`, add `cik` and `public_s1_url`, and set `edgar_checked_at`. SpaceX Q3 results date (earnings-linked lock-up release), Cerebras Q3 earnings date (lock-up end), Sep 30 NAVs for DXYZ/VCX/RVI.
