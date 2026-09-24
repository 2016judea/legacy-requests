#!/usr/bin/env python3
"""Florida: every "Single Source" notice on the Vendor Bid System -> data/matters/state-fl.json.

Section 287.057(3)(c), F.S. makes a state agency post its intent to buy from a single
source on MyFloridaMarketPlace for 15 business days. The public search is a JSON API
behind the Angular app (no login):

    POST /mfmp/pub/search/bids          {"type": ["10"], "page": n, "pageSize": 100, ...}
    GET  /mfmp/pub/search/bids/detail?id=<advertisementId>
    GET  /mfmp/bids/detail/attachment/download?attachmentId=<id>   (needs Accept: application/json,
                                                                     else it serves the SPA's HTML)

Most notices attach the standard form PUR 7776, "Description of Intended Single Source
Purchase", whose labelled fields (Commodity or Service Required, Quantity or Term,
Intended source, Estimated Dollar Amount, Justification ...) are parsed with regexes
here. The model then only sees those few fields, not the whole PDF.

Pre-filter, no model: a notice goes to extraction only if one of its UNSPSC commodity
codes is in a physical-equipment segment (KEEP_SEGMENTS: vehicles, power, electrical,
fluid/HVAC, lab and test instruments, traffic/security, industrial machinery ...) or an
equipment-repair class. IT, software, drugs, food, publications, furniture and every
service-only notice never cost a call: of 2,367 notices, 871 pass (2026-09-24).

Everything fetched is cached under data/cache/json/state-fl/ and data/cache/pdf/ and
never re-fetched. Usage: scripts/ingest_state_fl.py [--limit N]
"""
import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pdfplumber
import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://vendor.myfloridamarketplace.com/mfmp"
PAGE_URL = "https://vendor.myfloridamarketplace.com/search/bids/detail/{}"
JCACHE = ROOT / "data" / "cache" / "json" / "state-fl"
PCACHE = ROOT / "data" / "cache" / "pdf"
H = {"User-Agent": "Mozilla/5.0 (obsolete-parts-index; public records research)", "Accept": "application/json",
     "Content-Type": "application/json"}
SINGLE_SOURCE = "10"

# UNSPSC segments that are physical equipment: 20 mining/well, 21 farm, 22 construction
# machinery, 23 industrial machinery, 24 material handling, 25 vehicles, 26 power generation,
# 27 tools, 30 structures, 31 manufacturing components, 32 electronic components, 39 electrical,
# 40 fluid/gas/HVAC, 41 lab and measuring instruments, 45 AV/imaging, 46 security/traffic/fire,
# 47 cleaning, 48 service-industry machinery. Plus repair classes: 7215 building-systems
# maintenance, 73 industrial repair, 8111220 hardware maintenance.
KEEP_SEGMENTS = {"20", "21", "22", "23", "24", "25", "26", "27", "30", "31", "32", "39", "40", "41", "45", "46", "47", "48"}
REPAIR_CLASSES = ("7215", "73", "8111220")

FIELDS = [  # (key, label regex) in the order they appear on PUR 7776
    ("short_description", r"Short description of the commodity or service desired:"),
    ("_contact", r"\bCONTACT\s+Name:"),   # buyer's name/phone/email: dropped, not needed
    ("commodity", r"Commodity or Service Required[^:]*:"),
    ("quantity", r"Quantity or Term[^:]*:"),
    ("requestor", r"Requestor[^:]*:"),
    ("requirements", r"Performance and/or Design Requirements[^:]*\):|Performance and/or Design Requirements[^:]*:"),
    ("intended_source", r"Intended source[^:]*:"),
    ("amount", r"Estimated Dollar Amount[^:]*:"),
    ("justification", r"Justification for single source acquisition[^:]*\):|Justification for single source acquisition[^:]*:"),
    ("_end", r"Approved By:|Authorized Signature|PUR 7776 \(rev"),
]


def get_json(method: str, path: str, **kw):
    for attempt in range(4):
        try:
            r = requests.request(method, BASE + path, headers=H, timeout=60, **kw)
            r.raise_for_status()
            return r.json()
        except Exception:  # noqa: BLE001 - retry, then give up on this one notice
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def list_notices() -> list[dict]:
    crit = {"pageSize": 100, "type": [SINGLE_SOURCE], "status": [], "agency": [], "adNumber": "",
            "agencyAdvertisementNumber": "", "title": "", "publishedDate": "", "openDate": "", "endDate": "",
            "commodityCodes": [], "intendsToParticipate": "", "assignee": ""}
    total = int(get_json("POST", "/pub/search/bids/count", json=crit))
    out, page = [], 1
    while len(out) < total:
        rows = get_json("POST", "/pub/search/bids", json={**crit, "page": page})
        if not rows:
            break
        out += rows; page += 1
    print(f"VBS single-source notices listed: {len(out)} of {total}")
    return out


def detail(ad_id) -> dict:
    p = JCACHE / f"{ad_id}.json"
    if p.exists():
        return json.loads(p.read_text())
    d = get_json("GET", "/pub/search/bids/detail", params={"id": ad_id})
    p.write_text(json.dumps(d))
    return d


def form_doc(d: dict) -> dict | None:
    """The PUR 7776 notice form among the attachments, else the first PDF."""
    pdfs = [x for x in d.get("docs") or [] if str(x.get("fileName", "")).lower().endswith(".pdf")]
    for x in pdfs:
        if re.search(r"7776|single source|sole source|notice", f"{x.get('description')} {x.get('fileName')}", re.I):
            return x
    return pdfs[0] if pdfs else None


def pdf_text(att_id) -> str:
    pdf, txt = PCACHE / f"state-fl-{att_id}.pdf", PCACHE / f"state-fl-{att_id}.txt"
    if txt.exists():
        return txt.read_text()
    if not pdf.exists():
        r = requests.get(BASE + "/bids/detail/attachment/download", params={"attachmentId": att_id}, headers=H, timeout=120)
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            txt.write_text(""); return ""
        pdf.write_bytes(r.content)
    try:
        with pdfplumber.open(pdf) as p:
            text = "\n".join((pg.extract_text() or "") for pg in p.pages[:6])
    except Exception:  # noqa: BLE001 - a broken PDF is a notice with no form
        text = ""
    txt.write_text(text)
    return text


def parse_form(text: str) -> dict:
    """PUR 7776's labelled fields. Missing labels are simply absent."""
    hits = []
    for key, lab in FIELDS:
        m = re.search(lab, text, re.I)
        if m:
            hits.append((m.start(), m.end(), key))
    hits.sort()
    out = {}
    for i, (s, e, key) in enumerate(hits):
        if key.startswith("_"):
            continue
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        v = re.sub(r"\s+", " ", text[e:nxt]).strip()
        if v:
            out[key] = v[:1500]
    return out


def wants_model(d: dict) -> bool:
    codes = [str(c.get("id", "")) for c in d.get("commodityCodes") or []]
    return any(c[:2] in KEEP_SEGMENTS for c in codes) or any(c.startswith(REPAIR_CLASSES) for c in codes)


def boiler_free(desc: str) -> str:
    """The VBS description is one agency sentence followed by pages of registration boilerplate."""
    desc = re.split(r"All Bidders, Proposers|All prospective|For services contracts", desc or "")[0]
    return re.sub(r"\s+", " ", desc).strip()[:1500]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    JCACHE.mkdir(parents=True, exist_ok=True); PCACHE.mkdir(parents=True, exist_ok=True)
    rows = list_notices()
    if a.limit:
        rows = rows[: a.limit]
    with ThreadPoolExecutor(max_workers=4) as pool:
        details = list(pool.map(lambda r: detail(r["advertisementId"]), rows))
    keep = [d for d in details if not d.get("withdrawn") and wants_model(d)]
    print(f"details: {len(details)}; physical equipment by commodity code: {len(keep)}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        texts = list(pool.map(lambda d: pdf_text(form_doc(d)["attachmentId"]) if form_doc(d) else "", keep))
    matters, n_form = [], 0
    for d, text in zip(keep, texts):
        f = parse_form(text)
        n_form += bool(f.get("justification") or f.get("intended_source"))
        codes = "; ".join(f"{c.get('id')} {c.get('value')}" for c in d.get("commodityCodes") or [])
        lines = [f"Notice of intended single-source purchase, {d.get('agency')}", f"Title: {d.get('title')}",
                 f"Agency number: {d.get('agencyAdNumber')}", f"Commodity codes: {codes}", f"Posting: {boiler_free(d.get('description'))}"]
        lines += [f"{k.replace('_', ' ').title()}: {v}" for k, v in f.items()]
        if not f and text.strip():
            lines.append("Attached notice text: " + re.sub(r"\s+", " ", text)[:4000])
        matters.append({
            "matter_id": str(d["advertisementId"]), "title": d.get("title") or "",
            "intro_date": (d.get("publishedDate") or d.get("openDate") or "")[:10],
            "file": d.get("agencyAdNumber") or d.get("uniqueName"), "url": PAGE_URL.format(d["advertisementId"]),
            "agency": re.sub(r"\s*\([A-Z&]+\)$", "", d.get("agency") or "State of Florida"),
            "text": "\n".join(lines), "attachments": [],
        })
    out = ROOT / "data" / "matters" / "state-fl.json"
    out.write_text(json.dumps({"platform": "state-fl", "agency": "State of Florida", "state": "FL", "matters": matters}, indent=1))
    print(f"wrote {out.relative_to(ROOT)}: {len(matters)} notices, {n_form} with a parsed PUR 7776 form")


if __name__ == "__main__":
    main()
