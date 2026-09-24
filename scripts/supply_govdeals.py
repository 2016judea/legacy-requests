#!/usr/bin/env python3
"""GovDeals: government surplus auctions -> data/supply/govdeals.jsonl.

Uses the same anonymous search call the public search page at
govdeals.com/en/search makes (POST maestro.lqdt1.com/search/list with the
site's public page key, no login). It returns structured `makebrand` and
`model`, which is why GovDeals is the cheapest real source: the join gets a
model field instead of guessing from a title.

robots.txt (www.govdeals.com, checked 2026-09-24): search is allowed,
Crawl-delay 5 — honoured below. maestro.lqdt1.com serves no robots.txt.
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from supply_common import Cache, queries, write_listings  # noqa: E402

SOURCE = "govdeals"
API = "https://maestro.lqdt1.com/search/list"
# Public values the govdeals.com front end ships in its own JS bundle.
PAGE_KEY = "af93060f-337e-428c-87b8-c74b5837d6cd"
ROWS = 96
MFR_PAGES = 3  # a maker's name can return hundreds; the part-number queries catch the rest
HEADERS = {"x-api-key": PAGE_KEY, "x-user-id": "-1", "Origin": "https://www.govdeals.com",
           "Referer": "https://www.govdeals.com/", "Content-Type": "application/json"}


def body(q: str, page: int) -> dict:
    return {"categoryIds": "", "businessId": "GD", "searchText": q, "isQAL": False, "locationId": None,
            "model": "", "makebrand": "", "auctionTypeId": None, "page": page, "displayRows": ROWS,
            "sortField": "bestfit", "sortOrder": "desc", "requestType": "search", "responseStyle": "productsOnly",
            "facets": [], "facetsFilter": [], "timeType": "", "sellerTypeId": None, "accountIds": []}


def listing(a: dict, seen: str) -> dict:
    loc = ", ".join(x for x in (a.get("locationCity"), a.get("locationState")) if x) or None
    return {"source": SOURCE, "title": (a.get("assetShortDescription") or "").strip(),
            "manufacturer": a.get("makebrand") or None, "model": a.get("model") or None, "part_number": None,
            "price": a.get("currentBid") if a.get("currentBid") else None, "currency": a.get("currencyCode") or "USD",
            "url": f"https://www.govdeals.com/asset/{a['assetId']}/{a['accountId']}", "seen_at": seen,
            "location": f"{loc} ({a['companyName']})" if a.get("companyName") and loc else loc}


def main():
    cache = Cache(SOURCE, delay=5.0)
    qs = queries()
    out = []
    for i, q in enumerate(qs):
        pages = MFR_PAGES if " " in q or q.isalpha() else 1
        for page in range(1, pages + 1):
            headers = {**HEADERS, "x-api-correlation-id": str(uuid.uuid4()), "x-ecom-session-id": str(uuid.uuid4())}
            try:
                text, seen = cache.get("POST", API, json=body(q, page), headers=headers)
            except Exception as e:  # one bad query must not sink the run
                print(f"  {q!r} p{page}: {e}", file=sys.stderr)
                break
            res = json.loads(text).get("assetSearchResults") or []
            out += [listing(a, seen) for a in res if a.get("assetId") and a.get("assetShortDescription")]
            if len(res) < ROWS:
                break
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(qs)} queries, {len(out)} rows", file=sys.stderr)
    kept = write_listings(SOURCE, out)
    print(f"govdeals: {len(kept)} listings from {len(qs)} queries ({cache.fetches} fetched, {cache.hits} cached)")


if __name__ == "__main__":
    main()
