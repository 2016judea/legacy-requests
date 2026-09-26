#!/usr/bin/env python3
"""The dealer sales kit: for each surplus/obsolete parts dealer, the index rows that are
evidence of demand for what that dealer sells. Writes outreach/dealers/.

Every number in the kit is computed here, from data/records.jsonl, the dealers' own
catalogs, and SAM.gov. Nothing is typed into a draft by hand.

WHAT IT COMPUTES, per dealer in outreach/dealers/prospects.csv:

  (a) Exact catalog matches. A dealer listing and an index record that the supply join's
      own rule pairs (scripts/join_supply.match: same maker, same printed catalog number).
      Sources: data/supply/<slug>.jsonl for the six dealers whose sitemaps we read
      (scripts/supply_dealers.py), and outreach/dealers/lookups/<slug>.json for dealers
      behind Cloudflare, where each index part number was typed into the dealer's own
      site search in a real browser (see LOOKUPS below).
  (b) Brand-level demand. The dealer's top 3 manufacturers, then for each: index records,
      distinct agencies, dollars where the filing states a price, and 3 example rows.
      "Top" means by the dealer's own volume: product URLs per brand in its sitemap, or
      the per-brand counts its site prints (SITE_COUNTS). A dealer with neither is ranked
      by index demand among the brands its site lists (SITE_BRANDS). Only brands with at
      least MIN_RECORDS index records qualify, so the pitch never rests on one filing.
  (c) OPEN federal notices. SAM.gov's search API returns only active notices; we query it
      for sole-source / single-source / brand-name / intent titles posted in the last
      WINDOW_DAYS, plus one title query per brand, keep notices whose response deadline
      is today or later, read each one's description off sam.gov's keyless backend, and
      keep those that name the brand AND carry sole-source or brand-name language.

BRAND MATCHING. A record belongs to a brand when its manufacturer field matches the
brand's pattern. Two exclusions, both learned on this data: GE's jet-engine and medical
lines are not what an automation dealer sells (a single DLA J&A lists 40 T700 helicopter
engine parts under "General Electric"), and vehicles are never parts (join_supply rule 0).

Run: .venv/bin/python scripts/dealer_evidence.py            # everything
     .venv/bin/python scripts/dealer_evidence.py --lookups  # write the browser lookup list only
The SAM key is read by scripts/ingest_sam.py's api_key() and never printed.
"""
import csv
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import unquote

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from join_supply import match, norm, record_tokens  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outreach" / "dealers"
CACHE = ROOT / "data" / "cache" / "sam" / "dealer_kit"
SUPPLY_CACHE = ROOT / "data" / "cache" / "supply"
TODAY = date.today()
WINDOW_DAYS = 120
MIN_RECORDS = 5
PRICE = 500  # the test price, stated once in each draft
SITE = "https://the-google-of-obsolete-infrastructu.vercel.app"
SUBSTACK = "https://aidanjude.substack.com/p/hidden-market-arbitrage"

# canonical name -> (manufacturer pattern, exclusion pattern on part/model/title/manufacturer or None)
BRANDS = {
    "Allen-Bradley": (r"allen[\s-]?bradley|rockwell", None),
    "Siemens": (r"\bsiemens\b", r"health"),
    "ABB": (r"\babb\b", None),
    "Schneider Electric": (r"schneider|square[\s-]?d\b|modicon|telemecanique", None),
    "GE": (r"general electric|\bge\b", r"health|aircraft|aviation|engine|t700|helicopter|appliance|\bmri\b|imaging|radiology"),
    "Fanuc": (r"fanuc", None),
    "Yaskawa": (r"yaskawa", None),
    "Mitsubishi Electric": (r"mitsubishi", None),
    "Omron": (r"\bomron\b", None),
    "Honeywell": (r"honeywell", None),
    "Emerson": (r"emerson|rosemount|micro motion", None),
    "Eaton": (r"\beaton\b|cutler[\s-]?hammer", None),
    "Endress+Hauser": (r"endress", None),
    "Yokogawa": (r"yokogawa", None),
    "Hach": (r"\bhach\b", None),
    "Badger Meter": (r"badger meter", None),
    "Tektronix": (r"tektronix", None),
    "Keysight / Agilent": (r"keysight|agilent", None),
    "National Instruments": (r"national instruments", None),
    "Opto 22": (r"opto\s?22", None),
    "Liebert / Vertiv": (r"liebert|vertiv", None),
    "Parker": (r"\bparker\b", None),
    "Reliance Electric": (r"reliance electric", None),
    "Woodward": (r"woodward", None),
    "Danfoss": (r"danfoss", None),
    "Bosch Rexroth": (r"rexroth", None),
    "Sick": (r"\bsick\b", None),
    "Phoenix Contact": (r"phoenix contact", None),
    "Lenze": (r"lenze", None),
    "Control Techniques": (r"control techniques", None),
    "Fuji Electric": (r"fuji electric", None),
    "Toshiba": (r"toshiba", None),
    "Beckman Coulter": (r"beckman", None),
    "Thermo Fisher": (r"thermo\s?fisher|thermo scientific|thermo electron", None),
    "Waukesha": (r"waukesha", None),
    "Flygt / Xylem": (r"flygt|xylem", None),
    "Cummins": (r"cummins", None),
    "Caterpillar": (r"caterpillar", None),
    "Trane": (r"\btrane\b", None),
    "Leica": (r"\bleica\b", None),
    "Baumer": (r"baumer", None),
    "Pepperl+Fuchs": (r"pepperl", None),
    "Burkert": (r"b[uü]rkert", None),
}

# What each dealer's own site says it carries, read 2026-09-25 in a real browser.
SITE_BRANDS = {
    "radwell": ("https://www.radwell.com/en-US/ (home-page brand tiles)",
                ["Siemens", "Sick", "Honeywell", "Mitsubishi Electric", "Omron", "ABB", "GE", "Fanuc",
                 "Schneider Electric", "Parker", "Bosch Rexroth"]),
    "mroelectric": ("https://www.mroelectric.com/sitemaps/manufacturers.xml and the site footer",
                    ["ABB", "Control Techniques", "Fanuc", "Schneider Electric", "Siemens", "Yaskawa", "Lenze"]),
    "axcontrol": ("https://www.axcontrol.com/ (product lines on the home page)",
                  ["GE", "Reliance Electric", "Woodward", "Parker", "Fuji Electric"]),
    "iac": ("https://www.industrialautomationco.com/ (featured brand) and /pages/manufacturers (authorized lines)",
            ["Siemens", "Fuji Electric", "Toshiba"]),
}
# Per-brand counts the dealer prints about itself, read 2026-09-25.
SITE_COUNTS = {
    "dosupply": ("https://www.dosupply.com/ (Manufacturers block: items per brand)",
                 {"Allen-Bradley": 48300, "Siemens": 8700, "Mitsubishi Electric": 8500, "Fanuc": 7200,
                  "Schneider Electric": 6200, "Omron": 5100, "Yaskawa": 4000, "Eaton": 3100, "GE": 1900,
                  "Honeywell": 928, "Lenze": 428, "ABB": 346, "Control Techniques": 336}),
    "euautomation": ("https://www.euautomation.com/us/manufacturers (Top manufacturers in the US: parts in stock)",
                     {"Siemens": 1065620, "Bosch Rexroth": 493006, "ABB": 451759, "Schneider Electric": 297699,
                      "Omron": 237169, "Phoenix Contact": 234137, "Sick": 193009, "Mitsubishi Electric": 50839}),
}
# Dealers whose sitemap we hold: key into scripts/supply_dealers.DEALERS.
SITEMAP = {"eltra", "mroelectric", "kempston", "artisantg", "bidonequipment"}
# Dealers whose catalog was searched part-number by part-number in a browser.
LOOKUPS = {"dosupply", "euautomation", "radwell", "iac", "mroelectric"}

# A dealer sells hardware: software licences and service contracts are not its business.
NOT_PARTS = re.compile(r"software|licen[cs]e|subscription|star[\s-]?ccm|preventive maintenance|maintenance and repair|"
                       r"\bservices?\b|training|imaging|radiology", re.I)
SOLE_LANG = re.compile(r"sole[\s-]source|single[\s-]source|brand[\s-]name|only one (responsible )?source|"
                       r"intent to (award|negotiate|sole)|other than full and open|j&a|justification", re.I)


# ---------------------------------------------------------------- records and brands

def load_records() -> list[dict]:
    return [json.loads(l) for l in (ROOT / "data" / "records.jsonl").read_text().splitlines() if l.strip()]


def brand_rx(name: str):
    inc, exc = BRANDS[name]
    return re.compile(inc, re.I), (re.compile(exc, re.I) if exc else None)


def is_brand(record: dict, name: str) -> bool:
    if re.search(r"vehicle|fleet", record.get("equipment_class") or "", re.I):
        return False
    inc, exc = brand_rx(name)
    if not inc.search(record.get("manufacturer") or ""):
        return False
    if exc:
        hay = " ".join(str(record.get(k) or "") for k in ("manufacturer", "part", "model", "title"))
        if exc.search(hay):
            return False
    return True


def demand(records: list[dict], name: str) -> dict:
    rows = [r for r in records if is_brand(r, name)]
    priced = [r["price_usd"] for r in rows if isinstance(r.get("price_usd"), (int, float)) and r["price_usd"] >= 100]
    # Examples: a printed part number first, then a stated price, then the newest filing.
    ex = sorted(rows, key=lambda r: (not r.get("part_numbers"), r.get("price_usd") is None, str(r.get("date") or "")),
                reverse=False)
    ex = sorted(ex[:40], key=lambda r: (bool(r.get("part_numbers")), r.get("price_usd") is not None, str(r.get("date") or "")),
                reverse=True)
    seen, examples = set(), []
    for r in ex:
        k = (r["agency"], r.get("model"), r.get("part"))
        if k in seen:
            continue
        seen.add(k)
        examples.append(r)
        if len(examples) == 3:
            break
    return {"brand": name, "records": len(rows), "agencies": len({r["agency"] for r in rows}),
            "priced_records": len(priced), "dollars": round(sum(priced), 2),
            "federal": sum(1 for r in rows if r["id"].startswith("federal")), "examples": examples}


# ---------------------------------------------------------------- dealer catalogs

def sitemap_urls(slug: str) -> list[str]:
    from supply_dealers import DEALERS, product_urls
    return product_urls(slug, DEALERS[slug], False)


def catalog_brand_counts(slug: str) -> Counter:
    """Product URLs per brand in the dealer's sitemap. Kempston's URL has a maker segment;
    the others carry the maker in the slug."""
    from supply_dealers import DEALERS
    pat = DEALERS[slug]["product"]
    rxs = {b: brand_rx(b)[0] for b in BRANDS}
    c = Counter()
    for u in sitemap_urls(slug):
        m = pat.search(u)
        if not m:
            continue
        g = m.groupdict()
        text = unquote(g.get("maker") or g.get("slug") or g.get("pn") or "")
        text = re.sub(r"[^A-Za-z0-9]+", " ", text)
        for b, rx in rxs.items():
            if rx.search(text):
                c[b] += 1
    return c


def top_brands(slug: str, records: list[dict], dem: dict) -> tuple[list[str], str, dict]:
    ok = lambda b: dem[b]["records"] >= MIN_RECORDS
    if slug in SITE_COUNTS:
        src, counts = SITE_COUNTS[slug]
        ranked = sorted((b for b in counts if ok(b)), key=lambda b: -counts[b])
        return ranked[:3], f"ranked by the per-brand counts printed at {src}", counts
    if slug in SITEMAP and slug not in SITE_BRANDS:
        counts = catalog_brand_counts(slug)
        ranked = sorted((b for b in counts if ok(b)), key=lambda b: -counts[b])
        return ranked[:3], "ranked by product URLs per brand in the dealer's own sitemap", dict(counts)
    src, listed = SITE_BRANDS[slug]
    ranked = sorted((b for b in listed if ok(b)), key=lambda b: -dem[b]["records"])
    return ranked[:3], f"brands listed at {src}, ranked by index records (the site prints no counts)", {}


def exact_matches(slug: str, records: list[dict]) -> list[dict]:
    listings = []
    f = ROOT / "data" / "supply" / f"{slug}.jsonl"
    if f.exists():
        listings += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    lk = OUT / "lookups" / f"{slug}.json"
    if lk.exists():
        for q in json.loads(lk.read_text()).get("results", []):
            # A search-results page is not a listing; only a product page is.
            # A search-results page is not a listing; only a product page is. And the product
            # page's own identifier (last URL segment, option codes after "+" cut as the join
            # does) must BE the part number: a Yaskawa "p1000" family page or an "N6744B/760CAL"
            # calibrated variant is not the part the agency bought.
            for L in q.get("listings", []):
                if "/search" in L["url"].lower() or re.search(r"search results|advanced search", L["title"], re.I):
                    continue
                seg = unquote(L["url"].rstrip("/").split("/")[-1].split("?")[0])
                L = {**L, "_key": norm(re.split(r"\+|-PLUS-", seg, flags=re.I)[0])}
                listings.append(L)
    out, seen = [], set()
    for L in listings:
        for r in records:
            if (r["id"], L["url"]) in seen:
                continue
            if "_key" in L and L["_key"] not in record_tokens(r):
                continue
            how = "join rule" if match(r, L) else ("join rule, brand alias" if alias_match(r, L) else None)
            if how:
                seen.add((r["id"], L["url"]))
                out.append({"record": r, "listing": L, "how": how})
    best = {}
    for m in out:  # one listing per index record: the priced one if any
        k = m["record"]["id"]
        if k not in best or (best[k]["listing"].get("price") is None and m["listing"].get("price") is not None):
            best[k] = m
    return list(best.values())


def alias_match(r: dict, L: dict) -> bool:
    """The join's part-number rule, with the maker test widened to one BRANDS family:
    Radwell files the Altivar ATV630D15M3 under "SQUARE D", a Schneider Electric brand."""
    toks = record_tokens(r)
    if not toks or not (toks & {norm(L.get("part_number") or "")} | toks & {norm(w) for w in re.split(r"[\s|]+", L.get("title") or "")}):
        return False
    return any(is_brand(r, b) and brand_rx(b)[0].search(L.get("title") or "") for b in BRANDS)


def lookup_todo(records: list[dict]) -> dict:
    """Index part numbers to type into each Cloudflare dealer's site search: printed catalog
    numbers on records of a brand the dealer carries."""
    todo = {}
    for slug in sorted(LOOKUPS):
        carried = set(SITE_COUNTS.get(slug, ("", {}))[1]) | set(SITE_BRANDS.get(slug, ("", []))[1])
        if slug == "radwell":  # Radwell's catalog is 20M+ parts across every brand
            carried = set(BRANDS)
        q = {}
        for r in records:
            if not r.get("part_numbers") or not any(is_brand(r, b) for b in carried):
                continue
            for pn in r["part_numbers"]:
                base = str(pn).split("+")[0].strip()
                if norm(base) in record_tokens(r):
                    q.setdefault(base, []).append(r["id"])
        todo[slug] = [{"q": k, "records": v} for k, v in sorted(q.items())]
    return todo


# ---------------------------------------------------------------- SAM.gov open notices

def sam_search(key: str, name: str, params: dict) -> list[dict]:
    frm = (TODAY - timedelta(days=WINDOW_DAYS)).strftime("%m/%d/%Y")
    to = TODAY.strftime("%m/%d/%Y")
    p = CACHE / "search" / f"{TODAY.isoformat()}-{re.sub(r'[^a-z0-9]+', '-', name.lower())}.json"
    if p.exists():
        return json.loads(p.read_text())
    from ingest_sam import SEARCH, UA
    rows, offset = [], 0
    while True:
        r = requests.get(SEARCH, params={"api_key": key, "postedFrom": frm, "postedTo": to, "limit": 1000,
                                         "offset": offset, **params}, headers={"User-Agent": UA}, timeout=120)
        if r.status_code == 429 or not r.ok:
            raise Throttled(f"SAM search {name}: HTTP {r.status_code} {r.text[:200].replace(key, '<key>')}")
        d = r.json()
        got = d.get("opportunitiesData") or []
        rows += got
        offset += 1000
        if not got or offset >= int(d.get("totalRecords") or 0):
            break
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    return rows


class Throttled(Exception):
    pass


# When the key's daily quota is spent, fall back to the newest search snapshot on disk: the
# pages scripts/ingest_sam.py cached (active notices only, same queries). Their date is reported.
SNAPSHOTS = [ROOT / "data" / "cache" / "sam" / "search",
             Path.home() / "Desktop/the-google-of-obsolete-infrastructure-parts/.claude/worktrees/agent-a54d3062d81ee8bdf/data/cache/sam/search"]


def snapshot_rows() -> tuple[list[dict], str]:
    for d in SNAPSHOTS:
        files = sorted(d.glob("*.json")) if d.exists() else []
        if files:
            rows = [n for f in files for n in (json.loads(f.read_text()).get("opportunitiesData") or [])]
            when = date.fromtimestamp(max(f.stat().st_mtime for f in files)).isoformat()
            return rows, f"SAM.gov search snapshot of {when} ({len(files)} cached query pages); the key's daily quota was spent"
    return [], "no SAM.gov data: quota spent and no snapshot on disk"


def notice_text(nid: str) -> str:
    from ingest_sam import PUBLIC, cached_get, strip_html
    d = cached_get(CACHE / "notice" / f"{nid}.json", PUBLIC.format(nid))
    desc = d.get("description") or []
    if isinstance(desc, list):
        desc = " ".join(str(x.get("body") or "") for x in desc if isinstance(x, dict))
    return strip_html(str(desc))


def open_notices(brands: set[str]) -> dict[str, list[dict]]:
    from ingest_sam import api_key
    key = api_key()
    queries = {"sole source": {"title": "sole source"}, "single source": {"title": "single source"},
               "brand name": {"title": "brand name"}, "intent": {"title": "intent"}}
    for b in brands:
        for word in re.split(r"\s*/\s*", b):
            queries[f"brand {word}"] = {"title": word}
    notices, source = {}, f"SAM.gov search API, {TODAY.isoformat()}, posted in the last {WINDOW_DAYS} days"
    done = 0
    try:
        for name, params in queries.items():
            for n in sam_search(key, name, params):
                notices.setdefault(n["noticeId"], n)
            done += 1
    except Throttled as e:
        print(f"  {e}; adding the snapshot on disk")
        rows, snap = snapshot_rows()
        source = (f"SAM.gov search API {TODAY.isoformat()} ({done} of {len(queries)} queries before the key's daily "
                  f"quota ran out), plus the {snap.split(';')[0]}")
        for n in rows:
            notices.setdefault(n["noticeId"], n)
    live = [n for n in notices.values()
            if (n.get("responseDeadLine") or "")[:10] >= TODAY.isoformat() and str(n.get("active")).lower() == "yes"]
    out = defaultdict(list)
    for n in live:
        text = f"{n.get('title') or ''}\n{notice_text(n['noticeId'])}"
        if not SOLE_LANG.search(text) or NOT_PARTS.search(n.get("title") or ""):
            continue
        for b in brands:
            inc, exc = brand_rx(b)
            if inc.search(text) and not (exc and exc.search(text[:400])):
                out[b].append({"noticeId": n["noticeId"], "title": n.get("title"), "type": n.get("type"),
                               "agency": (n.get("fullParentPathName") or "").split(".")[-1].title(),
                               "service": ((n.get("fullParentPathName") or "").split(".") + [""])[1].title(),
                               "department": (n.get("fullParentPathName") or "").split(".")[0].title(),
                               "posted": n.get("postedDate"), "deadline": (n.get("responseDeadLine") or "")[:10],
                               "solicitation": n.get("solicitationNumber"),
                               "url": f"https://sam.gov/opp/{n['noticeId']}/view",
                               "snippet": snippet(text, inc)})
    for b in out:
        out[b].sort(key=lambda x: x["deadline"])
    return dict(out), len(notices), len(live), source


def snippet(text: str, rx) -> str:
    m = rx.search(text)
    if not m:
        return ""
    s = text[max(0, m.start() - 120): m.end() + 160]
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- rendering

def money(v) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) and v >= 100 else "not stated"


def row_line(r: dict) -> str:
    pn = ", ".join(r.get("part_numbers") or []) or (r.get("model") or "none printed")
    return (f"| {r.get('date') or ''} | {r['agency']} ({r.get('state') or ''}) | {r.get('manufacturer') or ''} | "
            f"{(r.get('part') or '')[:70]} | {pn[:60]} | {money(r.get('price_usd'))} | "
            f"[filing]({r.get('legistar_url') or r.get('source_url')}) |")


def evidence_md(d: dict) -> str:
    p = d["prospect"]
    L = [f"# {p['dealer']}: matched evidence", "",
         f"Generated {TODAY.isoformat()} by `scripts/dealer_evidence.py` from `data/records.jsonl` "
         f"({d['index_records']:,} records, {d['index_agencies']} agencies). Every number below is computed there.", "",
         "## (a) Exact catalog matches", ""]
    if d["exact"]:
        L += ["| their listing | price | index record | agency | date | price paid | part number |", "|---|---|---|---|---|---|---|"]
        for m in d["exact"]:
            r, l = m["record"], m["listing"]
            L.append(f"| [{l['title']}]({l['url']}) | {money(l.get('price'))} | {(r.get('part') or '')[:60]} | "
                     f"{r['agency']} ({r.get('state') or ''}) | {r.get('date')} | {money(r.get('price_usd'))} | "
                     f"{', '.join(r.get('part_numbers') or []) or r.get('model')} |")
    else:
        L.append(f"None. {d['exact_note']}")
    L += ["", "## (b) Brand-level demand", "", f"Top brands: {d['top_how']}.", ""]
    for b in d["brands"]:
        L += [f"### {b['brand']}", "",
              f"- Index records: **{b['records']}**, from **{b['agencies']}** agencies ({b['federal']} federal).",
              f"- Dollars where the filing states a price: **{money(b['dollars'])}** across {b['priced_records']} records.",
              "", "| date | agency | maker | part | part number | price paid | source |", "|---|---|---|---|---|---|---|"]
        L += [row_line(r) for r in b["examples"]] + [""]
    L += ["## (c) Open federal sole-source / brand-name notices", "", f"Source: {d['sam_source']}.", ""]
    if d["notices"]:
        L += ["| brand | notice | agency | type | response deadline |", "|---|---|---|---|---|"]
        for n in d["notices"]:
            L.append(f"| {n['brand']} | [{n['title']}]({n['url']}) | {n['agency']} ({n['department']}) | {n['type']} | **{n['deadline']}** |")
    else:
        L.append(f"None open today for {', '.join(b['brand'] for b in d['brands'])} "
                 f"({d['sam_seen']} notices read, {d['sam_open']} still open).")
    return "\n".join(L) + "\n"


def lead_row(d: dict) -> dict:
    """The one concrete row a draft opens on: the exact catalog match with the largest price
    paid (the part the dealer lists), else the top brand's best example."""
    if d["exact"]:
        printed = lambda m: any(norm(str(x).split("+")[0]) == (m["listing"].get("_key") or norm(m["listing"].get("part_number") or ""))
                                or norm(str(x).split("+")[0]) in {norm(w) for w in re.split(r"[\s|]+", m["listing"].get("title") or "")}
                                for x in m["record"].get("part_numbers") or [])
        m = max(d["exact"], key=lambda m: (printed(m), isinstance(m["record"].get("price_usd"), (int, float)),
                                           m["record"].get("price_usd") or 0))
        return {"kind": "exact", "record": m["record"], "listing": m["listing"], "brand": None}
    b = d["brands"][0]
    return {"kind": "brand", "record": b["examples"][0], "listing": None, "brand": b}


def first_name(p: dict) -> str:
    return p["named_person"].split()[0] if p.get("named_person") else ""


def maker(r: dict) -> str:
    m = re.sub(r",?\s+(inc\.?|llc|corporation|corp\.?|company|co\.)$", "", (r.get("manufacturer") or "").strip(), flags=re.I)
    return re.sub(r",?\s+(inc\.?|llc)$", "", m, flags=re.I)


def short_part(r: dict, listing: dict | None = None) -> str:
    pn = None
    if listing:  # name the number the dealer actually lists
        key = listing.get("_key") or norm(listing.get("part_number") or "")
        pn = next((x for x in r.get("part_numbers") or [] if norm(str(x).split("+")[0]) == key), None)
        pn = pn and str(pn).split("+")[0]
    if listing and not pn and listing.get("part_number") and norm(listing["part_number"]) in record_tokens(r):
        pn = listing["part_number"]
    pn = pn or ((r.get("part_numbers") or [None])[0] and str(r["part_numbers"][0]).split("+")[0])
    what = (r.get("part") or "").split(",")[0].split("(")[0].strip()
    what = what[:44].rsplit(" ", 1)[0] if len(what) > 44 else what
    return f"{maker(r)} {pn}" if pn else f"{maker(r)} {what}".strip()


def when(iso: str) -> str:
    d = date.fromisoformat(iso)
    return "today" if d == TODAY else d.strftime("%b %-d")


def paid(r: dict) -> str:
    v = r.get("price_usd")
    return f" for {money(v)}" if isinstance(v, (int, float)) and v >= 100 else ""


def drafts_md(d: dict) -> str:
    p, lead = d["prospect"], lead_row(d)
    r, lst = lead["record"], lead["listing"]
    fn = first_name(p) or "Hi"
    brands = [b["brand"] for b in d["brands"]]
    blist = ", ".join(brands[:-1]) + " and " + brands[-1] if len(brands) > 1 else brands[0]
    tot = d["brand_total"]
    year = str(r.get("date") or "")[:4]
    who = r["agency"]
    if lead["kind"] == "exact":
        hook = f"{who} bought {short_part(r, lst)} sole-source{paid(r)} in {year}. You list the same part."
        more = f"{tot['records']} filings from {tot['agencies']} agencies name {blist}."
    else:
        b = lead["brand"]
        hook = f"{who} bought {short_part(r)} sole-source{paid(r)} in {year}."
        more = f"{b['records']} filings from {b['agencies']} agencies name {b['brand']}."
    ask = f"Worth ${PRICE} for the full list of those buyers?"
    li = f"{fn}, {hook} {more} I built the index: {SUBSTACK} {ask}"
    for alt in (f"{fn}, {hook} {more} {SUBSTACK} {ask}", f"{fn}, {hook} {SUBSTACK} {ask}", f"{hook} {SUBSTACK} {ask}"):
        if len(li) <= 300:
            break
        li = alt
    n = d["notices"][0] if d["notices"] else None
    open_line = (f" One is open now: a {n['brand']} brand-name notice from the {n['service'] or n['department']}, "
                 f"responses due {when(n['deadline'])}." if n else "")
    form = (f"Hi {first_name(p) or 'there'},\n\n"
            f"{hook}\n\n"
            f"I built an index of public sole-source filings. {d['index_records']:,} so far, from {d['index_agencies']} "
            f"agencies, city councils up to the DLA. Each names the maker, the part and the price, because the buyer "
            f"had to write down why nobody else could sell it.\n\n"
            f"On {blist}: {tot['records']} filings from {tot['agencies']} agencies.{open_line}\n\n"
            f"The offer is one report. Every agency purchase on the brands you carry, with filing, date and price, "
            f"plus the federal notices still open. ${PRICE}.\n\n"
            f"Would your sales team work that list?\n\n"
            f"{SITE}\n{SUBSTACK}\n\n"
            f"Best,\nAidan")
    ev = []
    for m in sorted(d["exact"], key=lambda m: -(m["record"].get("price_usd") or 0))[:3]:
        ev.append((m["record"], m["listing"]))
    for b in d["brands"]:
        for x in b["examples"]:
            if len(ev) < 3 and all(x["id"] != e[0]["id"] for e in ev):
                ev.append((x, None))
    rows = "\n".join(
        f"| {x['agency']} | {x.get('date')} | {short_part(x, l)} | {money(x.get('price_usd'))}"
        f"{' (whole order, ' + str(len(x['part_numbers'])) + ' parts)' if len(x.get('part_numbers') or []) > 1 and x.get('price_usd') else ''} | "
        f"{'listed at ' + money(l.get('price')) if l and l.get('price') else ('listed' if l else 'a brand you carry')} |"
        for x, l in ev)
    mailer = (f"**{p['named_person']}**, {p['title']}  \n{p['dealer']}  \n{p['mailing_address']}\n\n---\n\n"
              f"# {tot['agencies']} public agencies bought {blist} from a single source.\n\n"
              f"They had to write down why. The filings name the maker, the part and the price, and they are public. "
              f"I index them: {d['index_records']:,} sole-source filings from {d['index_agencies']} agencies, "
              f"federal and local.\n\n"
              f"| agency | date | part | paid | at {p['dealer']} |\n|---|---|---|---|---|\n{rows}\n\n"
              + (f"**Open now:** a {n['brand']} brand-name notice from the {n['service'] or n['department']}, "
                 f"responses due {n['deadline']}. [{n['title']}]({n['url']})\n\n" if n else "")
              + f"**The report.** Every agency purchase on the brands you carry: filing, date, price paid, part number "
              f"where printed, plus federal notices still open. ${PRICE}, one time.\n\n"
              f"Which of those buyers already knows you have the part?\n\n"
              f"Aidan  \n{SITE}  \n{SUBSTACK}\n")
    return (f"# Drafts: {p['dealer']}\n\n"
            f"To: {p['named_person']}, {p['title']}. Generated {TODAY.isoformat()} by `scripts/dealer_evidence.py`; "
            f"every number is computed there.\n\n"
            f"## Touch 1, day 0: LinkedIn ({len(li)} characters)\n\nProfile: {p['linkedin_url']}\n\n{li}\n\n"
            f"## Touch 2, day 7: contact form ({len(form.split())} words)\n\n"
            f"Form: {p['contact_form_url'] or '(none verified: use sales@ on their site)'}\n\n{form}\n\n"
            f"## Touch 3, day 14: one-page mailer\n\n{mailer}")


def main():
    records = load_records()
    prospects = list(csv.DictReader((OUT / "prospects.csv").open()))
    if "--lookups" in sys.argv:
        (OUT / "lookups").mkdir(parents=True, exist_ok=True)
        todo = lookup_todo(records)
        (OUT / "lookups" / "todo.json").write_text(json.dumps(todo, indent=1))
        for k, v in todo.items():
            print(f"{k}: {len(v)} part numbers to look up")
        return
    dem = {b: demand(records, b) for b in BRANDS}
    per = {}
    for p in prospects:
        slug = p["slug"]
        top, how, counts = top_brands(slug, records, dem)
        ex = exact_matches(slug, records)
        if slug in SITEMAP:
            n = len(sitemap_urls(slug))
            note = f"The join's rule found no pairing across {n:,} product URLs in their sitemap."
        elif (OUT / "lookups" / f"{slug}.json").exists():
            lk = json.loads((OUT / "lookups" / f"{slug}.json").read_text())
            note = f"{len(lk.get('results', []))} index part numbers were typed into their site search; none matched."
        else:
            note = "Their catalog sits behind Cloudflare and was not searched."
        per[slug] = {"prospect": p, "top_how": how, "catalog_counts": {b: counts.get(b) for b in top},
                     "brands": [dem[b] for b in top], "exact": ex, "exact_note": note}
    all_brands = {b["brand"] for d in per.values() for b in d["brands"]}
    notices, seen, live, sam_source = open_notices(all_brands)
    agencies = len({r["agency"] for r in records})
    summary = []
    for slug, d in per.items():
        d["notices"] = [{"brand": b["brand"], **n} for b in d["brands"] for n in notices.get(b["brand"], [])]
        d["notices"].sort(key=lambda n: n["deadline"])
        d["sam_seen"], d["sam_open"], d["sam_source"] = seen, live, sam_source
        d["index_records"], d["index_agencies"] = len(records), agencies
        rows = [r for r in records if any(is_brand(r, b["brand"]) for b in d["brands"])]
        d["brand_total"] = {"records": len(rows), "agencies": len({r["agency"] for r in rows})}
        (OUT / f"dealer_{slug}.md").write_text(evidence_md(d))
        (OUT / f"drafts_{slug}.md").write_text(drafts_md(d))
        summary.append({"slug": slug, "dealer": d["prospect"]["dealer"], "named": bool(d["prospect"]["named_person"]),
                        "exact_matches": len(d["exact"]), "top_brands": [b["brand"] for b in d["brands"]],
                        "brand_records": d["brand_total"]["records"], "open_notices": len(d["notices"])})
        print(f"{slug:15} exact={len(d['exact'])} brands={[b['brand'] + ':' + str(b['records']) for b in d['brands']]} "
              f"notices={len(d['notices'])} li_chars={len(drafts_md(d).split('## Touch 1')[1].split(chr(10))[4])}")
    (OUT / "evidence.json").write_text(json.dumps({"generated": TODAY.isoformat(), "sam_notices_read": seen,
                                                   "sam_open": live, "sam_source": sam_source, "open_by_brand": notices, "dealers": summary},
                                                  indent=1, default=str))
    tokens = OUT / "tokens.csv"
    if not tokens.exists():  # a ledger: never regenerated over sent rows
        with tokens.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["token", "class", "slug", "organisation", "named_person", "touch", "channel", "target",
                        "planned_day", "status", "drafted", "sent_at", "proof", "reply_kind", "reply_on", "reply_note"])
            import hashlib
            for p in prospects:
                for touch, ch, tgt, day in [(1, "linkedin", p["linkedin_url"], 0), (2, "contact_form", p["contact_form_url"], 7),
                                            (3, "mail", p["mailing_address"], 14)]:
                    tok = hashlib.sha1(f"dealers-{p['slug']}-{touch}".encode()).hexdigest()[:8]
                    w.writerow([tok, "dealers", p["slug"], p["dealer"], p["named_person"], touch, ch, tgt, day, "draft",
                                TODAY.isoformat(), "", "", "", "", ""])
    tot_named = sum(1 for s in summary if s["named"])
    print(f"named {tot_named}/{len(summary)}; exact matches {sum(s['exact_matches'] for s in summary)}; "
          f"SAM notices read {seen}, open {live}; open brand notices {sum(len(v) for v in notices.values())}")


if __name__ == "__main__":
    main()
