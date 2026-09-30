#!/usr/bin/env python3
"""OPEN federal sole-source notices: the ones a dealer can still answer -> data/open_notices.jsonl.

The rest of this index mines purchases that already happened. This file catches them
before they happen. A federal buyer who means to skip competition must post a Special
Notice ("Notice of Intent to Sole Source"), a Presolicitation, or a Sources Sought
("brand name or equal") on SAM.gov, and leave it open for responses. Anyone who can
supply the item may answer the contracting officer by the response deadline, through the
channel the notice itself names. A surplus/obsolete parts dealer holding the exact part
is precisely who that window exists for.

Steps, each cached so a re-run costs nothing:

  1. LIST. Keyed SAM.gov search (active notices only), one call per title phrase in
     QUERIES, posted in the last WINDOW_DAYS with a response deadline today or later
     (`rdlfrom`). Pages cached under data/cache/sam/open/<date>/. The key's daily quota
     is ~10 search calls (reset 00:00 UTC), so a day's listing is 4-5 calls.
  2. KEEP types Special Notice / Presolicitation / Sources Sought whose deadline is still
     ahead, whose title or description uses sole-source / brand-name / intent language,
     and whose PSC is equipment (scripts/ingest_sam.is_equipment; a notice with no PSC is
     kept and left to the model).
  3. READ each notice's description and up to two attachments off sam.gov's KEYLESS
     backend (scripts/ingest_sam: cached_get, attachments_for, attachment_text), so the
     key's quota is spent only on the listing.
  4. EXTRACT with scripts/extract.py's own schema, prompt and cache (slug "open-sam").
     A notice already extracted as "federal-sam" reuses that reply at $0. BUDGET_USD caps
     the fresh spend; the run stops before a call that would cross it.
  5. MATCH. data/supply/*.jsonl by scripts/join_supply.join (manufacturer AND printed
     catalog number); the dealers' own sitemaps by scripts/supply_dealers.candidates, each
     candidate page fetched once and re-checked with join_supply.match; and the brand
     lines each dealer in outreach/dealers/prospects.csv carries
     (scripts/dealer_evidence: SITE_BRANDS, SITE_COUNTS, sitemap brand counts).

Contracting-officer names, emails and phones are public on every SAM.gov notice, but the
index is a public repo: they go to outreach/open_contacts.jsonl (gitignored) and never
into data/open_notices.jsonl or the page, which links to the notice instead.

Usage: scripts/ingest_sam_open.py [--budget 15] [--no-extract]
"""
import argparse
import csv
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract as X  # noqa: E402
from ingest_sam import (PUBLIC, SEARCH, UA, Throttled, agency, api_key, attachment_text, attachments_for,  # noqa: E402
                        cached_get, is_equipment, strip_html)

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "sam"
OPEN = CACHE / "open"
OUT = ROOT / "data" / "open_notices.jsonl"
CONTACTS = ROOT / "outreach" / "open_contacts.jsonl"   # gitignored: CO contact stays local
PROSPECTS = ROOT / "outreach" / "dealers" / "prospects.csv"
SLUG = "open-sam"
WINDOW_DAYS = 120
BUDGET_USD = 15.0
QUERIES = {"sole-source": "sole source", "single-source": "single source", "brand-name": "brand name", "intent": "intent to"}
TYPES = {"Special Notice", "Presolicitation", "Sources Sought"}
# A brand-name solicitation is not a notice of intent, but it is the same window: a dealer can quote the named brand.
BRAND_TYPES = {"Combined Synopsis/Solicitation", "Solicitation"}
BRAND_TITLE = re.compile(r"brand[\s-]?name", re.I)
LANG = re.compile(r"sole[\s-]?source|single[\s-]?source|brand[\s-]?name|only (one|known) (responsible )?source|"
                  r"intent to (award|negotiate|sole|procure|purchase|issue)|other than full and open|6\.302|13\.106-1|"
                  r"13\.501|proprietary|\bOEM\b|original equipment manufacturer", re.I)
DEALER_NAMES = {"radwell": "Radwell", "eltra": "Eltra Trade", "mroelectric": "MRO Electric", "kempston": "Kempston Controls",
                "artisantg": "Artisan Technology Group", "bidonequipment": "Bid on Equipment", "dosupply": "DO Supply",
                "euautomation": "EU Automation", "axcontrol": "AX Control", "iac": "Industrial Automation Co."}


# ---------------------------------------------------------------- 1-2. list and keep

def search(key: str, qname: str, phrase: str, frm: str, to: str, rdl: str, day: str) -> list[dict]:
    rows, offset = [], 0
    while True:
        p = OPEN / day / f"{qname}-{offset}.json"
        if p.exists():
            d = json.loads(p.read_text())
        else:
            r = requests.get(SEARCH, params={"api_key": key, "postedFrom": frm, "postedTo": to, "rdlfrom": rdl,
                                             "title": phrase, "limit": 1000, "offset": offset},
                             headers={"User-Agent": UA, "Accept": "application/json"}, timeout=120)
            if r.status_code == 429 or (r.status_code >= 400 and re.search(r"rate|limit|quota|throttl", r.text, re.I)):
                raise Throttled(f"HTTP {r.status_code}: {r.text[:300].replace(key, '<key>')}")
            if not r.ok:  # never let requests print the URL: it carries the key
                sys.exit(f"SAM search '{phrase}': HTTP {r.status_code} {r.text[:300].replace(key, '<key>')}")
            d = r.json()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(d))
        got = d.get("opportunitiesData") or []
        rows += got
        offset += 1000
        print(f"  search '{phrase}': {len(got)} rows of {d.get('totalRecords')}", flush=True)
        if not got or offset >= int(d.get("totalRecords") or 0):
            return rows


def deadline(n: dict) -> datetime | None:
    s = n.get("responseDeadLine") or ""
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- 5. dealers

def dealer_brands() -> dict[str, set[str]]:
    """slug -> canonical BRANDS names the dealer's own site says it carries. Radwell's catalog is
    20M+ parts across every brand, so it carries all of them (dealer_evidence.lookup_todo does the same)."""
    import dealer_evidence as D
    out = {}
    slugs = [r["slug"] for r in csv.DictReader(PROSPECTS.open())] if PROSPECTS.exists() else list(DEALER_NAMES)
    for s in slugs:
        if s == "radwell":
            out[s] = set(D.BRANDS)
        elif s in D.SITE_COUNTS:
            out[s] = set(D.SITE_COUNTS[s][1])
        elif s in D.SITE_BRANDS:
            out[s] = set(D.SITE_BRANDS[s][1])
        elif s in D.SITEMAP:
            p = CACHE / "open" / f"brands-{s}.json"   # counting a 900k-URL sitemap takes a while: once per dealer
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({b: n for b, n in D.catalog_brand_counts(s).items() if n}))
            out[s] = set(json.loads(p.read_text()))
    return out


def is_part(r: dict) -> bool:
    """A physical thing a dealer could ship. build_site.is_physical is tuned to council-packet wording and drops
    "Pawl Set ... spare part" and a Lockheed "Cable Assembly" (2026-09-30), so here only services, vehicles and
    software are out, and the one mixed class (SCADA/controls/software) defers to is_physical."""
    from build_site import SOFTWARE_WORDS, is_physical
    cls = r.get("equipment_class") or ""
    if cls in ("service/maintenance contract", "vehicle/fleet"):
        return False
    if SOFTWARE_WORDS.search(" ".join(str(r.get(k) or "") for k in ("part", "manufacturer", "model"))):
        return False
    return is_physical(r) if cls == "SCADA/controls/software" else True


def sitemap_makers(makers: set[str]) -> dict[str, dict[str, int]]:
    """dealer slug -> {manufacturer: product URLs naming it} for the dealers whose sitemaps are on disk. A URL names
    a maker when every distinctive word of it (join_supply.mfr_words) is in the URL's maker segment, or in the
    product slug when the URL has no maker segment. Covers makers outside dealer_evidence.BRANDS (Evoqua, Lockheed)."""
    import supply_dealers as S
    from urllib.parse import unquote
    from join_supply import mfr_words
    want = {m: {w for w in mfr_words(m) if not w.isdigit()} for m in makers}
    want = {m: w for m, w in want.items() if w}
    out = {}
    for slug, cfg in S.DEALERS.items():
        if not want or not (S.CACHE / slug / "sitemaps").exists():
            continue
        c = dict.fromkeys(want, 0)
        for u in S.product_urls(slug, cfg, False):
            mt = cfg["product"].search(u)
            if not mt:
                continue
            g = mt.groupdict()
            words = set(re.findall(r"[a-z0-9]+", unquote(g.get("maker") or g.get("slug") or "").lower()))
            for m, w in want.items():
                if w <= words:
                    c[m] += 1
        out[slug] = {m: n for m, n in c.items() if n}
    return out


def brand_of(r: dict) -> list[str]:
    import dealer_evidence as D
    return [b for b in D.BRANDS if D.is_brand(r, b)]


def catalog_hits(records: list[dict]) -> dict[str, list[dict]]:
    """record id -> dealer product pages carrying the record's printed catalog number, by the join's rule."""
    import supply_dealers as S
    from join_supply import match, record_tokens
    want: dict[str, list[dict]] = {}
    for r in records:
        for t in record_tokens(r):
            want.setdefault(t, []).append(r)
    out: dict[str, list[dict]] = {}
    if not want:
        return out
    for slug, cfg in S.DEALERS.items():
        if not (S.CACHE / slug / "sitemaps").exists():
            continue
        for u in S.product_urls(slug, cfg, False):
            recs = S.candidates(u, cfg, want)
            if not recs:
                continue
            p = S.CACHE / slug / "pages" / f"{S.key(u)}.json"
            if p.exists():
                c = json.loads(p.read_text())
            else:
                page = S.cached(S.CACHE / slug / "pages" / f"{S.key(u)}.html", u)
                if page is None:
                    continue
                c = {"url": u, "fetched": date.today().isoformat(), "html": page}
                p.write_text(json.dumps(c))
                (S.CACHE / slug / "pages" / f"{S.key(u)}.html").unlink(missing_ok=True)
            row = S.parse(c["html"], u, slug, cfg, c["fetched"])
            for r in recs:
                if row and match(r, row):
                    out.setdefault(r["id"], []).append({"source": slug, "title": row["title"], "price": row["price"],
                                                        "url": u, "seen_at": row["seen_at"]})
    return out


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=BUDGET_USD)
    ap.add_argument("--no-extract", action="store_true", help="list and read only; report what extraction would cost")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    day = date.today().isoformat()
    frm, to = (date.today() - timedelta(days=WINDOW_DAYS)).strftime("%m/%d/%Y"), date.today().strftime("%m/%d/%Y")

    notices, key = {}, api_key()
    try:
        for qname, phrase in QUERIES.items():
            for n in search(key, qname, phrase, frm, to, to, day):
                notices.setdefault(n["noticeId"], n)
    except Throttled as e:
        print(f"THROTTLED by SAM.gov ({e}); continuing with the {len(notices)} notices listed so far")
    listed = len(notices)
    live = [n for n in notices.values() if (n.get("type") in TYPES or (n.get("type") in BRAND_TYPES and BRAND_TITLE.search(n.get("title") or "")))
            and (deadline(n) or now) > now
            and str(n.get("active")).lower() == "yes"]
    eq = [n for n in live if not n.get("classificationCode") or is_equipment(n)]
    print(f"listed {listed}; open Special Notice/Presolicitation/Sources Sought {len(live)}; equipment PSC (or none) {len(eq)}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        pubs = list(pool.map(lambda n: cached_get(CACHE / "notice" / f"{n['noticeId']}.json", PUBLIC.format(n["noticeId"])), eq))
    with ThreadPoolExecutor(max_workers=6) as pool:
        atts = list(pool.map(lambda n: [x for x in map(attachment_text, attachments_for(n["noticeId"])) if x], eq))

    matters, meta = [], {}
    for n, pub, att in zip(eq, pubs, atts):
        desc = strip_html(" ".join(x.get("body") or "" for x in (pub.get("description") or []) if isinstance(x, dict)))[:8000]
        hay = f"{n.get('title')}\n{desc}\n" + "\n".join(x["text"][:4000] for x in att)
        if not LANG.search(hay):
            continue
        lines = [f"Federal notice ({n.get('type')}), {n.get('fullParentPathName')}", f"Title: {n.get('title')}",
                 f"Solicitation number: {n.get('solicitationNumber')}",
                 f"PSC: {n.get('classificationCode')}; NAICS: {n.get('naicsCode')}", "Description: " + (desc or "(none)")]
        m = {"matter_id": n["noticeId"], "title": n.get("title") or "", "intro_date": (n.get("postedDate") or "")[:10],
             "file": n.get("solicitationNumber"), "url": f"https://sam.gov/opp/{n['noticeId']}/view",
             "agency": agency(n), "text": "\n".join(lines), "attachments": att}
        matters.append(m)
        meta[n["noticeId"]] = n
    print(f"sole-source / brand-name language: {len(matters)} notices to extract")

    # ---- 4. extract, reusing federal-sam replies and capping fresh spend
    X.load_env()
    import anthropic
    client = anthropic.Anthropic()
    cdir = X.CACHE / "extract" / X.DEFAULT_MODEL
    spent, n_fresh, n_reused, outs = 0.0, 0, 0, {}
    todo = []
    for m in matters:
        mine, fed = cdir / f"{SLUG}-{m['matter_id']}.json", cdir / f"federal-sam-{m['matter_id']}.json"
        if not mine.exists() and fed.exists():
            shutil.copy(fed, mine)
            n_reused += 1
        if mine.exists():
            outs[m["matter_id"]] = json.loads(mine.read_text())
        else:
            todo.append(m)
    # Estimate before spending: input ~ chars/3.5 tokens, output ~1,200 tokens (the federal-sam run's mean).
    est = sum(len(X.build_content(m)[0][-1]["text"]) / 3.5 * 3e-6 + 1200 * 15e-6 for m in todo)
    print(f"extract: {len(outs)} cached ({n_reused} reused from federal-sam), {len(todo)} fresh, estimated ${est:.2f}")
    if a.no_extract:
        return
    if est > a.budget:
        sys.exit(f"STOP: estimated ${est:.2f} is over the ${a.budget:.2f} budget; nothing was spent")
    with ThreadPoolExecutor(max_workers=6) as pool:
        for m, out in zip(todo, pool.map(lambda m: X.extract_matter(client, X.DEFAULT_MODEL, SLUG, m), todo)):
            outs[m["matter_id"]] = out
            spent += out["usage"]["in"] * 3e-6 + out["usage"]["out"] * 15e-6
            n_fresh += 1
    print(f"extract: {n_fresh} fresh model calls, ${spent:.2f}")

    # ---- flatten to records in the index's own shape, so the join and the physical test apply unchanged
    from join_supply import join, load_listings
    records = []
    for m in matters:
        for i, r in enumerate(outs.get(m["matter_id"], {}).get("records", [])):
            r = {**r, "id": f"{SLUG}-{m['matter_id']}-{i}", "notice_id": m["matter_id"]}
            r["is_physical"] = is_part(r)
            records.append(r)
    phys = [r for r in records if r["is_physical"]]
    supply = join(phys, load_listings())
    catalog = catalog_hits(phys)
    carries = dealer_brands()
    lists = sitemap_makers({r["manufacturer"] for r in phys if r.get("manufacturer")})

    rows, contacts = [], []
    for m in matters:
        n = meta[m["matter_id"]]
        parts = []
        for r in (r for r in phys if r["notice_id"] == m["matter_id"]):
            brands = brand_of(r)
            dealers = []
            for s, carried in carries.items():
                pages = [x for x in catalog.get(r["id"], []) if x["source"] == s]
                if pages:
                    dealers.append({"slug": s, "name": DEALER_NAMES.get(s, s), "why": "catalog", "url": pages[0]["url"],
                                    "price": pages[0]["price"]})
                elif set(brands) & carried:
                    dealers.append({"slug": s, "name": DEALER_NAMES.get(s, s), "why": "brand", "brand": sorted(set(brands) & carried)[0]})
                elif lists.get(s, {}).get(r.get("manufacturer"), 0) >= 3:  # one or two slugs is a coincidence, not a line
                    dealers.append({"slug": s, "name": DEALER_NAMES.get(s, s), "why": "listings",
                                    "n": lists[s][r["manufacturer"]]})
            dealers.sort(key=lambda d: (d["why"] != "catalog", -d.get("n", 0)))
            parts.append({k: r.get(k) for k in ("manufacturer", "model", "part", "part_numbers", "quantity", "equipment_class",
                                                  "is_obsolete", "sole_source_vendor", "reason")}
                         | {"supply": supply.get(r["id"], []), "dealers": dealers})
        if not parts:
            continue
        dl = deadline(n)
        pathn = [s.strip().title() for s in (n.get("fullParentPathName") or "").split(".") if s.strip()]
        row = {"notice_id": m["matter_id"], "title": n.get("title"), "type": n.get("type"), "agency": m["agency"],
               "office": pathn[-1] if pathn else "", "posted": m["intro_date"], "deadline": n.get("responseDeadLine"),
               "deadline_date": dl.date().isoformat() if dl else None, "solicitation": n.get("solicitationNumber"),
               "psc": n.get("classificationCode"), "sam_url": m["url"], "parts": parts,
               "has_part_number": any(p["part_numbers"] for p in parts),
               "has_dealer": any(p["dealers"] or p["supply"] for p in parts)}
        row["brokerable"] = row["has_part_number"] and row["has_dealer"]
        rows.append(row)
        contacts.append({"notice_id": m["matter_id"], "deadline": n.get("responseDeadLine"), "title": n.get("title"),
                         "sam_url": m["url"], "point_of_contact": n.get("pointOfContact") or []})
    rows.sort(key=lambda r: r["deadline"] or "9999")
    OUT.write_text("".join(json.dumps(r) + "\n" for r in rows))
    if CONTACTS.parent.exists():
        CONTACTS.write_text("".join(json.dumps(c) + "\n" for c in sorted(contacts, key=lambda c: c["deadline"] or "")))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} open notices buying a physical part, "
          f"{sum(r['has_part_number'] for r in rows)} print a part number, {sum(r['has_dealer'] for r in rows)} have a candidate dealer, "
          f"{sum(r['brokerable'] for r in rows)} both; {sum(bool(p['supply']) for r in rows for p in r['parts'])} parts in supply listings, "
          f"{sum(any(d['why'] == 'catalog' for d in p['dealers']) for r in rows for p in r['parts'])} on a dealer catalog page")


if __name__ == "__main__":
    main()
