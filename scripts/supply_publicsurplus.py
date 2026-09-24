#!/usr/bin/env python3
"""PublicSurplus: public-agency surplus auctions -> data/supply/publicsurplus.jsonl.

Reads the public search results page (server-rendered HTML, no login). Only
the title, price, state and auction number are on the results page, so
manufacturer and model stay null and the join reads the title.

robots.txt (www.publicsurplus.com, checked 2026-09-24): `User-agent: *` only
disallows /images/. No crawl delay is set for us; we wait 5s anyway, the same
as the delay it sets for bingbot.
"""
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from supply_common import Cache, queries, write_listings  # noqa: E402

SOURCE = "publicsurplus"
SEARCH = "https://www.publicsurplus.com/sms/all/browse/search"
MFR_PAGES = 3
BLOCK = re.compile(r'<div class="auction-item" id="(\d+)searchGrid">(.*?)(?=<div class="auction-item" id=|\Z)', re.S)
TITLE = re.compile(r'title="#\d+ - ([^"]*)"')
PRICE = re.compile(r'id="val_\d+searchGrid">\s*\$([\d,]+(?:\.\d\d)?)')
STATE = re.compile(r'<span class="auction-item-state">\s*([A-Z]{2})\s*</span>')


def parse(page: str, seen: str) -> list[dict]:
    out = []
    for auc, block in BLOCK.findall(page):
        t = TITLE.search(block)
        if not t:
            continue
        p, s = PRICE.search(block), STATE.search(block)
        out.append({"source": SOURCE, "title": html.unescape(t.group(1)).strip(), "manufacturer": None, "model": None,
                    "part_number": None, "price": float(p.group(1).replace(",", "")) if p else None,
                    "currency": "USD", "url": f"https://www.publicsurplus.com/sms/auction/view?auc={auc}",
                    "seen_at": seen, "location": s.group(1) if s else None})
    return out


def main():
    cache = Cache(SOURCE, delay=5.0)
    qs = queries()
    out = []
    for i, q in enumerate(qs):
        pages = MFR_PAGES if " " in q or q.isalpha() else 1
        for page in range(pages):
            try:
                text, seen = cache.get("GET", SEARCH, params={"posting": "y", "keyWord": q, "page": page})
            except Exception as e:
                print(f"  {q!r} p{page}: {e}", file=sys.stderr)
                break
            rows = parse(text, seen)
            new = [r for r in rows if r["url"] not in {o["url"] for o in out}]
            out += new
            if not new:  # past the last page the site repeats or empties
                break
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(qs)} queries, {len(out)} rows", file=sys.stderr)
    kept = write_listings(SOURCE, out)
    print(f"publicsurplus: {len(kept)} listings from {len(qs)} queries ({cache.fetches} fetched, {cache.hits} cached)")


if __name__ == "__main__":
    main()
