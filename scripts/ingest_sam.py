#!/usr/bin/env python3
"""Federal: sole-source, brand-name and J&A notices on SAM.gov -> data/matters/federal-sam.json.

A federal buyer who will not compete a purchase must say so on SAM.gov: a Justification
(J&A, notice type "u") after award, or a Special Notice / presolicitation "intent to sole
source" before it. Unlike a council packet, a J&A usually names the manufacturer and the
part, which is why this source exists here.

Sources. Only the first needs the key:

    GET https://api.sam.gov/opportunities/v2/search?api_key=K&postedFrom=&postedTo=&limit=1000&offset=N
        (+ ptype=u, or title=<phrase>)  -- ACTIVE notices. Keyed and rate limited per key.
    GET https://sam.gov/api/prod/fileextractservices/v1/api/download/Contract%20Opportunities/
        Archived%20Data/FY2026_archived_opportunities.csv?privacy=Public
        -- ARCHIVED notices, SAM.gov's public bulk extract (~0.5 GB per fiscal year of archive
           date), full description as a column. No key.
    GET https://sam.gov/api/prod/opps/v2/opportunities/<noticeId>
        -- the public notice page's own backend: description HTML for an active notice. No key.
    GET https://sam.gov/api/prod/opps/v3/opportunities/<noticeId>/resources
    GET https://sam.gov/api/prod/opps/v3/opportunities/resources/files/<resourceId>/download
        -- the attachment list and each file (a redirect to S3). No key.

Why the archive: search returns only active notices. Over a 12-month window it gave 1,609,
and 586 of its 785 J&As were posted in the final month (2026-09-25) — a notice leaves search
when it is archived. The archive rows get the same filter the search queries apply (type
Justification, or a title saying sole source, single source or brand name) and are merged
by noticeId. So the key's daily quota is spent only on the listing, about one call per
1,000 active notices; the key's own per-notice `description` URL (noticedesc) is never used.

The key is read from the MAIN checkout's .env.local (worktrees don't have it) and is never
printed, logged or cached: cached pages are response bodies, and SAM.gov does not echo it.
Throttled (HTTP 429, or a 4xx body saying rate/limit/quota)? The script prints the server's
message, carries on with the archive and the cache, and a re-run resumes the listing.

Pre-filter, no model: keep a notice only if its PSC (classificationCode) is a numeric goods
code (groups 10-99) outside the consumable groups/classes below, or a J-class code
(maintenance and repair OF equipment). Services, R&D, construction, food, drugs, fuel and
software never cost a call.

Usage: scripts/ingest_sam.py [--days 364] [--limit N]
"""
import argparse
import csv
import html
import io
import json
import re
import sys
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import pdfplumber
import requests

ROOT = Path(__file__).resolve().parent.parent
ENV = Path.home() / "Desktop/the-google-of-obsolete-infrastructure-parts/.env.local"
SEARCH = "https://api.sam.gov/opportunities/v2/search"
BULK = ("https://sam.gov/api/prod/fileextractservices/v1/api/download/Contract%20Opportunities/Archived%20Data/"
        "{}_archived_opportunities.csv?privacy=Public")
PUBLIC = "https://sam.gov/api/prod/opps/v2/opportunities/{}"
RESOURCES = "https://sam.gov/api/prod/opps/v3/opportunities/{}/resources"
FILE = "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/{}/download"
CACHE = ROOT / "data" / "cache" / "sam"
PCACHE = ROOT / "data" / "cache" / "pdf"
UA = "Mozilla/5.0 (obsolete-parts-index; public records research)"
HAL = {"User-Agent": UA, "Accept": "application/hal+json"}  # sam.gov's own backend answers 406 to application/json

# The listing queries. A notice found by several is kept once (by noticeId).
QUERIES = {
    "ja": {"ptype": "u"},                    # Justification (J&A): every one is a non-competed award
    "sole-source": {"title": "sole source"},
    "single-source": {"title": "single source"},
    "brand-name": {"title": "brand name"},
}
TITLE_RE = re.compile(r"sole[- ]source|single[- ]source|brand[- ]name", re.I)  # the same filter, for archive rows

# PSC groups that are goods but not equipment (subsistence, clothing, fuel, office supplies, raw
# materials, hand tools/hardware bins, furniture ...). 65 is kept but its drug classes are not; 70 is
# kept but software (7030 / 7A2x) is not.
SKIP_PSC_GROUPS = {"51", "52", "53", "54", "55", "56", "68", "71", "72", "73", "75", "76", "77", "78", "79", "80",
                   "81", "83", "84", "85", "87", "88", "89", "91", "93", "94", "95", "96", "99"}
SKIP_PSC_CLASSES = {"6505", "6508", "6510", "6515", "6532", "6550", "7030", "7A20", "7A21"}
WANT_ATT = re.compile(r"j\s*&\s*a|justif|sole|single|brand|intent|\bnoi\b|notice|spec|statement of (work|need)|\bsow\b"
                      r"|\bson\b|salient|limited|\blsj\b|exception|determination", re.I)
ATT_MAX_CHARS = 12_000       # per attachment text layer handed to the model
ATT_MAX_BYTES = 8_000_000    # a bigger attachment is a drawing set or a manual: skip
ATT_PER_NOTICE = 2


class Throttled(Exception):
    pass


def api_key() -> str:
    for line in ENV.read_text().splitlines():
        if line.startswith("SAM_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit(f"SAM_API_KEY not found in {ENV}")


def search_page(key: str, qname: str, q: dict, frm: str, to: str, offset: int) -> dict:
    p = CACHE / "search" / f"{qname}-{frm.replace('/', '')}-{to.replace('/', '')}-{offset}.json"
    if p.exists():
        return json.loads(p.read_text())
    r = requests.get(SEARCH, params={"api_key": key, "postedFrom": frm, "postedTo": to, "limit": 1000, "offset": offset, **q},
                     headers={"User-Agent": UA, "Accept": "application/json"}, timeout=120)
    if r.status_code == 429 or (r.status_code >= 400 and re.search(r"rate|limit|quota|throttl", r.text, re.I)):
        raise Throttled(f"HTTP {r.status_code}: {r.text[:400].replace(key, '<key>')}")
    r.raise_for_status()
    d = r.json()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
    return d


def list_active(key: str, frm: str, to: str) -> tuple[dict, bool, int]:
    """Every active notice from every search query, by noticeId. Returns (notices, complete, new_api_calls)."""
    notices = {}
    count = lambda: len(list((CACHE / "search").glob("*.json"))) if (CACHE / "search").exists() else 0
    before, complete = count(), True
    try:
        for qname, q in QUERIES.items():
            offset, total = 0, None
            while total is None or offset < total:
                d = search_page(key, qname, q, frm, to, offset)
                total = int(d.get("totalRecords") or 0)
                rows = d.get("opportunitiesData") or []
                for n in rows:
                    notices.setdefault(n["noticeId"], {**n, "_query": qname})
                print(f"  search {qname}: offset {offset}, {len(rows)} rows of {total}", flush=True)
                if not rows:
                    break
                offset += 1000
    except Throttled as e:
        print(f"THROTTLED by SAM.gov: {e}")
        complete = False
    return notices, complete, count() - before


def list_archived(frm: date, to: date) -> dict:
    """Archived notices posted in the window that pass the query filter, shaped like search rows."""
    csv.field_size_limit(sys.maxsize)
    out = {}
    fy = lambda d: d.year + (d.month >= 10)
    for y in range(fy(frm), fy(to) + 2):  # archive date can run past the post date
        p = CACHE / "bulk" / f"FY{y}_archived.csv"
        if not p.exists() or p.stat().st_size < 1000:
            p.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(BULK.format(f"FY{y}"), headers={"User-Agent": UA}, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(p, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
        n_rows = 0
        with open(p, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                n_rows += 1
                posted = (row.get("PostedDate") or "")[:10]
                if not (frm.isoformat() <= posted <= to.isoformat()):
                    continue
                if row.get("Type") != "Justification" and not TITLE_RE.search(row.get("Title") or ""):
                    continue
                aw = {"awardee": {"name": row["Awardee"]}, "amount": row.get("Award$")} if row.get("Awardee") else None
                out[row["NoticeId"]] = {
                    "noticeId": row["NoticeId"], "title": row.get("Title"), "solicitationNumber": row.get("Sol#"),
                    "fullParentPathName": ".".join(x for x in (row.get("Department/Ind.Agency"), row.get("Sub-Tier"), row.get("Office")) if x),
                    "postedDate": posted, "type": row.get("Type"), "classificationCode": row.get("ClassificationCode"),
                    "naicsCode": row.get("NaicsCode"), "officeAddress": {"state": row.get("State")},
                    "placeOfPerformance": {"state": {"code": row.get("PopState")}}, "uiLink": row.get("Link"),
                    "award": aw, "_desc": row.get("Description") or "", "_query": "archive"}
        print(f"  archive FY{y}: {n_rows} rows read, {len(out)} matching so far", flush=True)
    return out


def is_equipment(n: dict) -> bool:
    psc = (n.get("classificationCode") or "").upper()
    if psc.startswith("J"):                       # maintenance/repair of equipment (J010..J099)
        return True
    if len(psc) != 4 or not psc[:2].isdigit():    # services, R&D, construction start with a letter
        return False
    return psc[:2] not in SKIP_PSC_GROUPS and psc not in SKIP_PSC_CLASSES and 10 <= int(psc[:2]) <= 99


# A part-number-shaped token (letters AND digits joined by a dash: "1756-L83E"), or a P/N, part number, model or NSN label.
PN_RE = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]+(?:-[A-Z0-9]+)+\b|\bP/?N\b|part (number|no)|\bmodel\b|\bNSN\b", re.I)
OBSOLETE_RE = re.compile(r"obsolete|discontinued|no longer (manufactured|made|available|supported)|end[- ]of[- ]life|replacement part|spare part|\bOEM\b", re.I)


def priority(n: dict) -> int:
    """Which notices the extraction budget reaches first: the ones most likely to print a part number.
    4 = a part-number token in the title/description, +2 = goods (not a J repair code), +1 = a J&A or obsolescence words.
    The J&A's own text is often only in its attachment, which is why a J&A without a token still outranks the rest."""
    hay = f"{n.get('title') or ''} {n.get('_desc') or ''}"
    goods = not (n.get("classificationCode") or "").upper().startswith("J")
    return 4 * bool(PN_RE.search(hay)) + 2 * goods + (n.get("type") == "Justification" or bool(OBSOLETE_RE.search(hay)))


def cached_get(p: Path, url: str) -> dict:
    """GET sam.gov's keyless backend once; {} (uncached, so a re-run retries) on a transient failure."""
    if p.exists():
        return json.loads(p.read_text())
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HAL, timeout=60)
            d = {} if r.status_code == 404 else (r.raise_for_status() or r.json())
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(d))
            return d
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    return {}


def attachments_for(nid: str) -> list[dict]:
    """Up to ATT_PER_NOTICE readable public files, the ones named like a justification or spec first."""
    d = cached_get(CACHE / "resources" / f"{nid}.json", RESOURCES.format(nid))
    links = []
    for grp in (d.get("_embedded") or {}).get("opportunityAttachmentList") or []:
        for x in grp.get("attachments") or []:
            if x.get("type") == "file" and x.get("accessStatus", "public") == "public" and x.get("deletedFlag") != "1":
                links.append({"name": x.get("name") or "", "url": FILE.format(x["resourceId"]), "rid": x["resourceId"],
                              "size": int(x.get("size") or 0)})
    ok = [x for x in links if x["size"] <= ATT_MAX_BYTES and re.search(r"\.(pdf|docx)$", x["name"], re.I)]
    ok.sort(key=lambda x: (not WANT_ATT.search(x["name"]), x["size"]))
    return ok[:ATT_PER_NOTICE]


def strip_html(s: str) -> str:
    s = re.sub(r"<(br|/p|/li|/tr|/h\d)[^>]*>", "\n", s or "", flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def docx_text(b: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        x = z.read("word/document.xml").decode("utf8", "replace")
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", x)))


def attachment_text(link: dict) -> dict | None:
    """Download one file once; its text layer is cached as data/cache/pdf/sam-<resourceId>.json. {name,url,text} or None."""
    meta = PCACHE / f"sam-{link['rid']}.json"
    if meta.exists():
        m = json.loads(meta.read_text())
    else:
        m = {"name": link["name"], "kind": "", "text": ""}
        try:
            r = requests.get(link["url"], headers={"User-Agent": UA}, timeout=120)
            b = r.content
            if r.status_code != 200:
                m["kind"] = f"http {r.status_code}"
            elif b.startswith(b"%PDF"):
                with pdfplumber.open(io.BytesIO(b)) as pdf:
                    m["text"] = "\n".join((pg.extract_text() or "") for pg in pdf.pages[:12])
                m["kind"] = "pdf" if len(m["text"].strip()) > 200 else "pdf-scanned"
            elif b.startswith(b"PK"):
                m["text"], m["kind"] = docx_text(b), "docx"
            else:
                m["kind"] = "other"
        except Exception as e:  # noqa: BLE001 - a broken attachment is a notice without it
            m["kind"] = f"error {type(e).__name__}"
            return None  # uncached: retry next run
        meta.write_text(json.dumps(m))
    text = re.sub(r"[ \t]+", " ", m.get("text") or "").strip()
    return {"name": m["name"], "url": link["url"], "text": text[:ATT_MAX_CHARS]} if text else None


def agency(n: dict) -> str:
    segs = [s.strip() for s in (n.get("fullParentPathName") or "").split(".") if s.strip()]
    name = (segs[1] if len(segs) > 1 else segs[0]) if segs else "Federal agency"
    name = re.sub(r"\s*\([A-Z0-9&-]+\)$", "", name)
    name = re.sub(r"^(.*), (DEPARTMENT|DEPT) OF( THE)?$", r"\2 of\3 \1", name)
    small = {"of", "the", "and", "for", "on", "in"}
    return " ".join(w.lower() if w.lower() in small and i else w.capitalize() for i, w in enumerate(name.split()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=364, help="window ending today (the search API allows at most 1 year)")
    ap.add_argument("--limit", type=int, default=0, help="max equipment notices to fetch/write (0 = all)")
    a = ap.parse_args()
    PCACHE.mkdir(parents=True, exist_ok=True)
    # The window is pinned at the first run so re-runs hit the cache instead of the quota.
    win = CACHE / "window.json"
    if not win.exists():
        to = date.today()
        win.parent.mkdir(parents=True, exist_ok=True)
        win.write_text(json.dumps({"from": (to - timedelta(days=a.days)).strftime("%m/%d/%Y"), "to": to.strftime("%m/%d/%Y")}))
    w = json.loads(win.read_text())
    notices, complete, calls = list_active(api_key(), w["from"], w["to"])
    n_active = len(notices)
    for nid, n in list_archived(datetime.strptime(w["from"], "%m/%d/%Y").date(), datetime.strptime(w["to"], "%m/%d/%Y").date()).items():
        notices.setdefault(nid, n)
    print(f"window {w['from']}-{w['to']}: {n_active} active (search API, {calls} new keyed calls, "
          f"{'complete' if complete else 'INCOMPLETE: re-run to resume'}) + {len(notices) - n_active} archived = {len(notices)} notices")
    keep = sorted((n for n in notices.values() if is_equipment(n)), key=lambda n: (priority(n), n.get("postedDate") or ""), reverse=True)
    print(f"physical equipment by PSC: {len(keep)}; priority tiers {sorted(Counter(map(priority, keep)).items(), reverse=True)}")
    if a.limit:
        keep = keep[: a.limit]
    with ThreadPoolExecutor(max_workers=6) as pool:
        pubs = list(pool.map(lambda n: {} if "_desc" in n else cached_get(CACHE / "notice" / f"{n['noticeId']}.json", PUBLIC.format(n["noticeId"])), keep))
    with ThreadPoolExecutor(max_workers=6) as pool:
        atts = list(pool.map(lambda n: [x for x in map(attachment_text, attachments_for(n["noticeId"])) if x], keep))
    matters, n_desc, n_att = [], 0, 0
    for n, pub, att in zip(keep, pubs, atts):
        desc = strip_html(n.get("_desc") or " ".join(x.get("body") or "" for x in pub.get("description") or []))[:8000]
        n_desc += bool(desc); n_att += bool(att)
        pop = n.get("placeOfPerformance") or {}
        state = ((n.get("officeAddress") or {}).get("state") or (pop.get("state") or {}).get("code") or "")[:2]
        lines = [f"Federal notice ({n.get('type')}), {n.get('fullParentPathName')}", f"Title: {n.get('title')}",
                 f"Solicitation number: {n.get('solicitationNumber')}", f"PSC: {n.get('classificationCode')}; NAICS: {n.get('naicsCode')}"]
        aw = n.get("award") or {}
        if (aw.get("awardee") or {}).get("name"):
            lines.append(f"Award: {aw['awardee']['name']} {aw.get('amount') or ''}".strip())
        lines.append("Description: " + (desc or "(none)"))
        matters.append({
            "matter_id": n["noticeId"], "title": n.get("title") or "", "intro_date": (n.get("postedDate") or "")[:10],
            "file": n.get("solicitationNumber"), "url": n.get("uiLink") or f"https://sam.gov/opp/{n['noticeId']}/view",
            "agency": agency(n), "state": state, "text": "\n".join(lines), "attachments": att,
        })
    out = ROOT / "data" / "matters" / "federal-sam.json"
    out.write_text(json.dumps({"platform": "federal-sam", "agency": "Federal agency", "state": "", "matters": matters}, indent=1))
    print(f"wrote {out.relative_to(ROOT)}: {len(matters)} notices, {n_desc} with a description, {n_att} with attachment text")


if __name__ == "__main__":
    main()
