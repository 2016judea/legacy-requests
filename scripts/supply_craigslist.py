#!/usr/bin/env python3
"""Craigslist asking prices for the index's makers and part numbers -> data/supply/craigslist.jsonl.

Craigslist has no nationwide search and dropped RSS in 2023, but its own front end reads
a public JSON endpoint, one call per (area, query), up to 360 results each, no key:

    https://sapi.craigslist.org/web/v8/postings/search/full?batch=<areaId>-0-360-0-0&cc=US&lang=en&query=<q>&searchPath=sss

The listing rows are positional arrays (see `decode_item`): posting id and posted date are
offsets from `decode.minPostingId` / `decode.minPostedDate`, images are "3:<key>" and live at
images.craigslist.org/<key>_600x450.jpg, and the universal posting URL is
www.craigslist.org/view/d/<slug>/<viewKey>. Area ids come from reference.craigslist.org/Areas.

Probed 2026-10-01: curl with a browser User-Agent gets 200 everywhere; the HTML search page 403s.
Every response is cached under data/cache/supply/craigslist/ and never re-fetched (delete to refresh).

Queries: every maker and part-number token the index holds (supply_common.queries), the makers
across AREAS, the part numbers across the biggest PART_AREAS only, plus a short list of generic
equipment words so a person can search for a thing the agencies never filed. Listings whose title
holds no part-number-shaped token are kept too (they still carry a photo and an asking price) but
only ones with a token can become an item on /worth.
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from supply_common import Cache, queries, write_listings  # noqa: E402

API = "https://sapi.craigslist.org/web/v8/postings/search/full"
# hostname -> AreaID (reference.craigslist.org/Areas, read 2026-10-01)
AREAS = {"newyork": 3, "losangeles": 7, "chicago": 11, "houston": 23, "dallas": 21, "phoenix": 18, "philadelphia": 17,
         "sanantonio": 53, "sandiego": 8, "sfbay": 1, "austin": 15, "seattle": 2, "denver": 13, "boston": 4, "atlanta": 14,
         "miami": 20, "detroit": 22, "minneapolis": 19, "portland": 9, "lasvegas": 26, "orlando": 39, "tampa": 37,
         "stlouis": 29, "baltimore": 34, "washingtondc": 10, "charlotte": 41, "pittsburgh": 33, "cleveland": 27,
         "sacramento": 12, "kansascity": 30, "indianapolis": 45, "columbus": 42, "milwaukee": 47, "nashville": 32,
         "inlandempire": 104, "orangecounty": 103, "raleigh": 36, "saltlakecity": 56, "cincinnati": 35, "jacksonville": 80}
PART_AREAS = ["newyork", "losangeles", "chicago", "houston", "dallas", "sfbay", "phoenix", "seattle"]
GENERIC = ["plc", "vfd", "variable frequency drive", "servo drive", "servo motor", "centrifuge", "switchgear", "transformer",
           "circuit breaker", "contactor", "generator", "air compressor", "oscilloscope", "spectrum analyzer", "flow meter",
           "pressure transmitter", "hmi panel", "control panel", "pump motor", "submersible pump", "gearbox", "ups battery backup",
           "network switch", "two way radio", "chlorine analyzer", "water meter", "lab incubator", "microscope", "autoclave",
           "pipette", "thermal camera", "hydraulic pump", "welder", "cnc", "forklift battery charger", "soft starter",
           "encoder", "actuator", "valve positioner", "turbidimeter"]
DELAY = 0.4
WORKERS = 3  # one worker did ~1 call/s (16,328 calls = 5 hours); three keep it under two. Back off if 403s appear.
# CategoryID -> abbreviation (reference.craigslist.org/Categories, saved 2026-10-01): item[2] is the category id,
# and /worth keeps only equipment categories, so a "Stryker" boat never becomes a Stryker hospital bed's price.
CATEGORIES = {c["CategoryID"]: c["Abbreviation"] for c in json.loads((Path(__file__).resolve().parent.parent / "data" / "craigslist_categories.json").read_text())}


def decode_item(it: list, dec: dict, area: str) -> dict | None:
    if not isinstance(it, list) or len(it) < 5 or not isinstance(it[-1], str):
        return None
    pid = dec["minPostingId"] + it[0]
    posted = datetime.fromtimestamp(dec["minPostedDate"] + it[1], tz=timezone.utc).date().isoformat()
    price = it[3] if isinstance(it[3], (int, float)) and it[3] > 0 else None
    loc = None
    try:
        li = int(str(it[4]).split("~")[0].split(":")[0])
        loc = dec["locations"][li]  # [kind, hostname, subarea]
        loc = f"{loc[1]}/{loc[2]}" if isinstance(loc, list) else None
    except (ValueError, IndexError, TypeError):
        pass
    view_key = slug = None
    images: list[str] = []
    for x in it[5:-1]:
        if isinstance(x, list) and x:
            if x[0] == 13 and len(x) > 1:
                view_key = x[1]
            elif x[0] == 6 and len(x) > 1:
                slug = x[1]
            elif x[0] == 4:
                images = [f"https://images.craigslist.org/{s.split(':', 1)[1]}_600x450.jpg" for s in x[1:] if isinstance(s, str) and ":" in s]
    if not (slug and view_key):
        return None
    cat = CATEGORIES.get(it[2]) if isinstance(it[2], int) else None
    return {"source": "craigslist", "title": it[-1], "manufacturer": None, "model": None, "part_number": None, "category": cat,
            "price": float(price) if price is not None else None, "currency": "USD",
            "url": f"https://www.craigslist.org/view/d/{slug}/{view_key}", "seen_at": None,
            "location": loc or area, "image": images[0] if images else None, "posted": posted, "_pid": pid}


def search(cache: Cache, area: str, q: str) -> list[dict]:
    url = f"{API}?batch={AREAS[area]}-0-360-0-0&cc=US&lang=en&query={quote(q)}&searchPath=sss"
    try:
        body, seen = cache.get("GET", url)
    except Exception as e:  # a 4xx/5xx on one query must not stop the run; nothing is cached for it
        print(f"  {area} {q!r}: {e}", file=sys.stderr)
        return []
    try:
        d = json.loads(body)["data"]
    except (ValueError, KeyError):
        return []
    out = []
    for it in d.get("items") or []:
        l = decode_item(it, d.get("decode") or {}, area)
        if l:
            l["seen_at"] = seen
            out.append(l)
    return out


def main():
    cache = Cache("craigslist", DELAY)
    qs = queries()
    makers = [q for q in qs if not re.search(r"\d", q)]
    parts = [q for q in qs if re.search(r"\d", q)]
    plan = [(a, q) for q in makers + GENERIC for a in AREAS] + [(a, q) for q in parts for a in PART_AREAS]
    print(f"craigslist: {len(makers)} makers + {len(GENERIC)} generic x {len(AREAS)} areas, {len(parts)} part numbers x {len(PART_AREAS)} areas = {len(plan)} calls")
    listings: dict[int, dict] = {}
    caches = [Cache("craigslist", DELAY) for _ in range(WORKERS)]  # one delay clock per worker
    with ThreadPoolExecutor(WORKERS) as pool:
        for n, found in enumerate(pool.map(lambda job: search(caches[job[0] % WORKERS], job[1][0], job[1][1]), enumerate(plan)), 1):
            for l in found:
                pid = l.pop("_pid")
                if pid not in listings:
                    listings[pid] = l
            if n % 500 == 0 or n == len(plan):
                print(f"  {n}/{len(plan)} calls, {len(listings)} listings, {sum(c.fetches for c in caches)} fetched, {sum(c.hits for c in caches)} cached", flush=True)
                write_listings("craigslist", list(listings.values()))
    out = write_listings("craigslist", list(listings.values()))
    with_img = sum(1 for l in out if l.get("image"))
    priced = sum(1 for l in out if l.get("price"))
    print(f"craigslist: {len(out)} listings, {priced} priced, {with_img} with a photo ({date.today().isoformat()})")


if __name__ == "__main__":
    main()
