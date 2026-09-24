#!/usr/bin/env python3
"""Surplus/refurb industrial dealers: does a dealer list the exact part an agency
said only one supplier could sell?

One file per dealer, data/supply/<dealer>.jsonl, in the contract documented in
scripts/join_supply.py. A row is written only when join_supply.match() pairs it
with at least one index record — manufacturer AND part number — so every line
in these files is a hit, never a near miss.

HOW. No dealer search endpoint is used. Each dealer publishes a sitemap whose
product URLs carry the part number (and usually the maker); the sitemaps are
downloaded once and matched locally against the part-number tokens in the
records' model field. Only candidate product pages are fetched, then parsed
(JSON-LD Product, else og: meta) and re-checked with the join's own rule.

DEALERS. Each was checked on 2026-09-24: robots.txt allows the sitemap and the
product path, and the site answers without a login or challenge.
Not covered, and why (all read off a curl that day):
  radwell.com, plccenter.com (Radwell), euautomation.com, dosupply.com,
  pdfsupply.com, plchardware.com, 1sourcecomponents.com: Cloudflare challenge.
  industrialautomationco.com: robots.txt disallows /search, and its Shopify
    handles are not the part number (hc-sf202 is the HC-SFS202), so there is
    no allowed lookup short of crawling 14,000+ sitemaps.
  wiautomation.com: robots.txt disallows /search and publishes no sitemap.
  precision-elec.com: sitemap points at a dead third-party host.

Cache: data/cache/supply/<dealer>/ — sitemaps under sitemaps/ (gitignored,
large, refreshable), product pages under pages/ (kept; a cached page is never
re-fetched). Delay between live requests: DELAY seconds; none of the six
dealers' robots.txt sets a crawl-delay.

MEASURED 2026-09-24: 1,160,456 product URLs across six dealers, 1 row. The
index's hardware is mostly OEM-direct parts (SEEPEX rotors, Ovivo drives,
Foxboro transmitter configs) or a series name ("PowerFlex 755"), and a dealer
catalog keyed by full catalog number carries neither. Recall grows with
records that state a full catalog number, not with more dealers.

Run: .venv/bin/python scripts/supply_dealers.py [--refresh-sitemaps]
"""
import gzip
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from join_supply import FIELDS, match, mfr_words, part_tokens, validate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "supply"
OUT = ROOT / "data" / "supply"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
DELAY = 1.5

# How each dealer's product URL carries the part number. `pn` returns the URL
# pieces that together are the part number; `maker` returns the piece naming
# the maker, or None when the URL does not say (then the page must).
DEALERS = {
    "mroelectric": {
        "sitemaps": ["https://www.mroelectric.com/sitemaps/products.xml"],
        "product": re.compile(r"/product/(?P<pn>[^/?#]+)$"),
        "location": "Waxhaw, NC",
    },
    "kempston": {
        "index": "https://www.kempstoncontrols.com/sitemaps/us/sitemapindex.xml",
        "product": re.compile(r"kempstoncontrols\.com/(?P<pn>[^/]+)/(?P<maker>[^/]+)/sku/\d+$"),
        "location": None,
    },
    "artisantg": {
        "index": "https://www.artisantg.com/sitemaps_index.xml",
        "product": re.compile(r"artisantg\.com/(?:[A-Za-z]+/)?\d+-\d+/(?P<slug>[^/?#]+)$"),
        "location": "Champaign, IL",
    },
    "bidonequipment": {
        "index": "https://www.bid-on-equipment.com/sitemap.xml",
        "product": re.compile(r"/\d+~(?P<slug>[^/]+)\.htm$"),
        "location": None,
    },
    "eltra": {
        "index": "https://eltra-trade.com/sitemap.xml",
        "product": re.compile(r"eltra-trade\.com/products/(?P<slug>[^/?#]+)$"),
        "location": None,
    },
    "aotewell": {
        "sitemaps": ["https://www.aotewell.com/product-sitemap.xml"],
        "product": re.compile(r"aotewell\.com/stock/(?P<slug>[^/?#]+)$"),
        "location": None,
    },
}

_last = [0.0]


def fetch(url: str) -> bytes:
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body


def cached(path: Path, url: str, refresh=False) -> str | None:
    if path.exists() and not refresh:
        return path.read_text()
    try:
        text = fetch(url).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        print(f"  ! {url}: {e}", file=sys.stderr)
        return None
    if "<title>Just a moment...</title>" in text:
        print(f"  ! {url}: challenge page, skipped", file=sys.stderr)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def locs(xml: str) -> list[str]:
    return [html.unescape(u.strip()) for u in re.findall(r"<loc>([^<]+)</loc>", xml or "")]


def product_urls(slug: str, cfg: dict, refresh: bool) -> list[str]:
    d = CACHE / slug / "sitemaps"
    maps = list(cfg.get("sitemaps", []))
    if "index" in cfg:
        maps += locs(cached(d / "index.xml", cfg["index"], refresh))
    urls = []
    for m in maps:
        urls += locs(cached(d / f"{key(m)}.xml", m, refresh))
    return urls


def slug_tokens(text: str, max_n: int = 7) -> set[str]:
    """Every run of 1..max_n consecutive URL pieces, separators dropped."""
    pieces = [p for p in re.split(r"[^A-Za-z0-9]+", text) if p]
    out = set()
    for i in range(len(pieces)):
        for n in range(1, max_n + 1):
            if i + n <= len(pieces):
                out.add("".join(pieces[i:i + n]).upper())
    return out


def wanted(records: list[dict]) -> dict[str, list[dict]]:
    """Part token -> the records whose model field carries it."""
    out: dict[str, list[dict]] = {}
    for r in records:
        if r.get("manufacturer") and r.get("model"):
            for t in part_tokens(r["model"]):
                out.setdefault(t, []).append(r)
    return out


def candidates(url: str, cfg: dict, want: dict[str, list[dict]]) -> list[dict]:
    m = cfg["product"].search(url)
    if not m:
        return []
    g = m.groupdict()
    if "pn" in g:  # the URL segment IS the part number: it must equal a token exactly
        pn = re.sub(r"[^A-Z0-9]", "", urllib.request.unquote(g["pn"]).upper())
        recs = want.get(pn, [])
        if g.get("maker"):
            maker = set(re.findall(r"[a-z0-9]+", urllib.request.unquote(g["maker"]).lower()))
            maker |= {re.sub(r"[^a-z0-9]", "", urllib.request.unquote(g["maker"]).lower())}
            recs = [r for r in recs if mfr_words(r["manufacturer"]) & maker]
        return recs
    slug = urllib.request.unquote(g["slug"])
    words = set(re.findall(r"[a-z0-9]+", slug.lower()))
    hits = []
    for t in slug_tokens(slug) & want.keys():
        hits += [r for r in want[t] if mfr_words(r["manufacturer"]) & words]
    return hits


def jsonld_products(page: str) -> list[dict]:
    out = []
    for blob in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(blob.strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                if "@graph" in d:
                    stack += d["@graph"]
                t = d.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    out.append(d)
            elif isinstance(d, list):
                stack += d
    return out


def meta(page: str, prop: str) -> str | None:
    m = re.search(rf'<meta[^>]+(?:property|name|itemprop)=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']*)', page, re.I)
    if not m:
        m = re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name|itemprop)=["\']{re.escape(prop)}["\']', page, re.I)
    return html.unescape(m.group(1)).strip() if m else None


def num(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def parse(page: str, url: str, dealer: str, cfg: dict, seen: str) -> dict | None:
    title = maker = model = pn = price = currency = None
    for p in jsonld_products(page):
        title = title or p.get("name")
        b = p.get("brand") or p.get("manufacturer")
        maker = maker or (b.get("name") if isinstance(b, dict) else b)
        model = model or (p.get("model") if isinstance(p.get("model"), str) else None)
        pn = pn or p.get("mpn") or p.get("sku")
        offers = p.get("offers")
        offers = offers if isinstance(offers, list) else [offers] if offers else []
        for o in offers:
            if isinstance(o, dict):
                v = num(o.get("price") or o.get("lowPrice"))
                if v and price is None:
                    price, currency = v, o.get("priceCurrency") or "USD"
    title = title or meta(page, "og:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
        title = m and re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
    if price is None:
        price = num(meta(page, "product:price:amount") or meta(page, "price"))
        currency = (meta(page, "product:price:currency") or meta(page, "priceCurrency") or "USD") if price else None
    if not title:
        return None
    s = lambda v: re.sub(r"\s+", " ", html.unescape(str(v))).strip() if v else None
    return {"source": dealer, "title": s(title), "manufacturer": s(maker), "model": s(model), "part_number": s(pn),
            "price": price, "currency": currency if price else None, "url": url, "seen_at": seen,
            "location": cfg.get("location")}


def main():
    refresh = "--refresh-sitemaps" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    records = [json.loads(l) for l in (ROOT / "data" / "records.jsonl").read_text().splitlines() if l.strip()]
    want = wanted(records)
    OUT.mkdir(parents=True, exist_ok=True)
    total_rows, total_parts = 0, set()
    for dealer, cfg in DEALERS.items():
        if only and dealer not in only:
            continue
        urls = product_urls(dealer, cfg, refresh)
        cands = {u: recs for u in urls if (recs := candidates(u, cfg, want))}
        rows, parts = [], set()
        for u, recs in sorted(cands.items()):
            p = CACHE / dealer / "pages" / f"{key(u)}.json"
            if p.exists():
                c = json.loads(p.read_text())
            else:
                page = cached(CACHE / dealer / "pages" / f"{key(u)}.html", u)
                if page is None:
                    continue
                c = {"url": u, "fetched": date.today().isoformat(), "html": page}
                p.write_text(json.dumps(c))
                (CACHE / dealer / "pages" / f"{key(u)}.html").unlink(missing_ok=True)
            row = parse(c["html"], u, dealer, cfg, c["fetched"])
            if not row or validate(row):
                continue
            hit = [r for r in recs if match(r, row)]
            if hit:
                rows.append({k: row.get(k) for k in FIELDS})
                parts |= {(r["manufacturer"], r["model"]) for r in hit}
        path = OUT / f"{dealer}.jsonl"
        if rows:
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        elif path.exists():
            path.unlink()
        total_rows += len(rows)
        total_parts |= parts
        print(f"{dealer}: {len(urls)} product urls, {len(cands)} candidates, {len(rows)} rows, {len(parts)} index parts")
    print(f"dealers: {total_rows} rows, {len(total_parts)} distinct index make+model")


if __name__ == "__main__":
    main()
