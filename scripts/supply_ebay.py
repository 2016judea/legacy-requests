#!/usr/bin/env python3
"""eBay asking prices and photos for the index's part numbers -> data/supply/ebay.jsonl.

Browse API, application token (client-credentials grant, no user login):

    POST https://api.ebay.com/identity/v1/oauth2/token   (Basic <client_id:client_secret>, scope api_scope)
    GET  https://api.ebay.com/buy/browse/v1/item_summary/search?q=<part number>&limit=200

Needs EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in .env.local (a production keyset from
developer.ebay.com/my/keys). Without them this script prints why and writes nothing, so `make supply`
still runs. Sold/completed prices are NOT in the Browse API (that is the gated Marketplace Insights
API), so every eBay row is an ASKING price; the page labels it that way.

Queries are the index's part numbers only (supply_common.queries, the ones with a digit): a maker's
name alone returns tens of thousands of unrelated listings on eBay. 5,000 calls a day on the free tier.
Every response is cached under data/cache/supply/ebay/ and never re-fetched.

Status 2026-10-01: the developer-account registration ends on an hCaptcha, which is Aidan's click
(browser-as-aidan skill, gate 1). The form was filled; keys come after it.
"""
import base64
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from supply_common import Cache, queries, write_listings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def creds() -> tuple[str, str] | None:
    env = {}
    f = ROOT / ".env.local"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    if env.get("EBAY_CLIENT_ID") and env.get("EBAY_CLIENT_SECRET"):
        return env["EBAY_CLIENT_ID"], env["EBAY_CLIENT_SECRET"]
    return None


def app_token(cid: str, secret: str) -> str:
    r = requests.post(TOKEN_URL, data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
                      headers={"Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode(),
                               "Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def listing(it: dict, seen: str) -> dict | None:
    price = (it.get("price") or {})
    try:
        value = float(price["value"]) if price.get("currency") == "USD" else None
    except (KeyError, ValueError):
        value = None
    img = (it.get("image") or {}).get("imageUrl") or next((x.get("imageUrl") for x in it.get("thumbnailImages") or [] if x.get("imageUrl")), None)
    loc = it.get("itemLocation") or {}
    where = ", ".join(x for x in (loc.get("city"), loc.get("stateOrProvince")) if x) or loc.get("country")
    if not it.get("itemWebUrl"):
        return None
    return {"source": "ebay", "title": it.get("title") or "", "manufacturer": None, "model": None, "part_number": None,
            "price": value, "currency": "USD" if value is not None else None, "url": it["itemWebUrl"], "seen_at": seen,
            "location": where or None, "image": img, "posted": (it.get("itemCreationDate") or "")[:10] or None,
            "category": (it.get("categories") or [{}])[0].get("categoryId")}


def main():
    c = creds()
    if not c:
        print("ebay: no EBAY_CLIENT_ID / EBAY_CLIENT_SECRET in .env.local; skipped (register at developer.ebay.com/my/keys)")
        return
    token = app_token(*c)
    cache = Cache("ebay", 0.3)
    parts = [q for q in queries() if re.search(r"\d", q)]
    out: dict[str, dict] = {}
    for n, q in enumerate(parts, 1):
        try:
            body, seen = cache.get("GET", SEARCH, params={"q": q, "limit": 200}, headers={"Authorization": f"Bearer {token}",
                                                                                           "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        except Exception as e:
            print(f"  {q!r}: {e}", file=sys.stderr)
            continue
        for it in (json.loads(body).get("itemSummaries") or []):
            l = listing(it, seen)
            if l and l["url"] not in out:
                out[l["url"]] = l
        if n % 100 == 0:
            print(f"  {n}/{len(parts)} queries, {len(out)} listings", flush=True)
    rows = write_listings("ebay", list(out.values()))
    print(f"ebay: {len(rows)} listings from {len(parts)} part-number queries, {sum(1 for r in rows if r['image'])} with a photo ({date.today().isoformat()})")


if __name__ == "__main__":
    main()
