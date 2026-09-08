#!/usr/bin/env python3
"""Turn ingested matters into structured equipment records with Claude.

One call per matter: the matter's own text plus the text of every PDF
attachment (scanned PDFs with no text layer are sent as documents so the
model reads the image). Output is validated against RECORD_SCHEMA. Every
model response is cached under data/cache/extract/<model>/ and never re-run.

Usage: scripts/extract.py [--model M] [--limit N] [client ...]
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import anthropic
import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
CLIENTS = {c["slug"]: c for c in json.loads((ROOT / "clients.json").read_text())}
DEFAULT_MODEL = "claude-sonnet-5"
MAX_TEXT_CHARS = 150_000        # per matter, all documents concatenated
MAX_SCAN_PAGES = 25             # a scanned PDF longer than this is skipped
KEYWORD_RE = re.compile(
    r"\b(sole[- ]source|single[- ]source|proprietary|obsolete|no longer (manufactured|made|supported|available)"
    r"|discontinued|OEM|original equipment manufacturer|emergency replacement|spare parts|replacement parts|lead[- ]time)\b",
    re.I)

RECORD_SCHEMA = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "manufacturer": {"type": ["string", "null"], "description": "OEM / brand of the equipment, e.g. 'Flygt', 'Siemens', 'Patterson'. Null if not stated."},
                    "model": {"type": ["string", "null"], "description": "Model, series or part number as printed, e.g. 'MAA 12X10', 'CENTRiCAL'. Null if not stated."},
                    "part": {"type": "string", "description": "What was bought or maintained, in the document's own words, under 120 characters."},
                    "quantity": {"type": ["string", "null"]},
                    "price_usd": {"type": ["number", "null"], "description": "Dollar amount stated for this item. Null if none."},
                    "lead_time": {"type": ["string", "null"], "description": "Stated lead time, verbatim, e.g. '25 weeks'."},
                    "sole_source_vendor": {"type": ["string", "null"], "description": "The vendor / distributor named as the only source."},
                    "reason": {"type": "string", "description": "Verbatim short quote (under 200 chars) from the document stating why no alternative exists or why this vendor was chosen."},
                    "equipment_class": {"type": "string", "enum": ["pump", "valve", "motor/drive", "electrical/switchgear/transformer", "generator", "instrumentation/calibration", "SCADA/controls/software", "vehicle/fleet", "HVAC", "treatment process (membrane/centrifuge/UV/chemical feed)", "pipe/fitting", "communications/radio", "other equipment", "service/maintenance contract"]},
                    "installed_location": {"type": ["string", "null"], "description": "Plant, facility or site named for this item, if any."},
                    "is_obsolete": {"type": "boolean", "description": "True only if the document says the equipment or part is obsolete, discontinued, no longer manufactured, or end-of-life."},
                },
                "required": ["manufacturer", "model", "part", "quantity", "price_usd", "lead_time", "sole_source_vendor", "reason", "equipment_class", "installed_location", "is_obsolete"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["records"],
    "additionalProperties": False,
}

SYSTEM = """You extract structured records of EQUIPMENT and PARTS from municipal procurement documents (sole-source justifications, OEM sole-source lists, purchase approvals, bid waivers).

Rules:
- One record per distinct piece of equipment, part, or equipment-maintenance item that the document says was bought, approved, waived from bidding, or added to a sole-source list.
- Only physical equipment, parts, and the software/maintenance/service contracts that keep specific named equipment running. SKIP professional services (legal, actuarial, consulting, staffing, training, advertising, insurance, real estate, grants, general construction contracts with no named equipment).
- Copy names, model numbers and prices exactly as printed. Never invent a manufacturer, model or price; use null when the document does not state it. If a line names only a vendor (e.g. a distributor), put it in sole_source_vendor and set manufacturer to the OEM only if the document names one.
- `reason` must be a verbatim quote from the document, not a paraphrase.
- If the document contains no qualifying equipment, return {"records": []}.
"""


def load_env():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        for line in (Path.home() / "Desktop/bricks/.env").read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"')


def pdf_text(path: Path) -> tuple[str, int]:
    """Text layer of a PDF and its page count, cached beside the PDF as .txt / .pages."""
    txt, pages = path.with_suffix(".txt"), path.with_suffix(".pages")
    if txt.exists() and pages.exists():
        return txt.read_text(), int(pages.read_text() or 0)
    try:
        with pdfplumber.open(path) as p:
            n = len(p.pages)
            text = "\n".join((pg.extract_text() or "") for pg in p.pages[:60])
    except Exception:  # noqa: BLE001 - a broken PDF is a skipped PDF
        text, n = "", 0
    txt.write_text(text); pages.write_text(str(n))
    return text, n


def build_content(matter: dict) -> tuple[list, dict]:
    """Return the content blocks for one matter and a summary of what went in."""
    parts = [f"AGENCY MATTER {matter['file']} — {matter['title']}\nIntroduced {matter['intro_date']}\n\n{matter['text']}"]
    blocks = []
    info = {"pdfs_text": 0, "pdfs_scanned": 0, "pdfs_skipped": 0}
    for a in matter["attachments"]:
        p = ROOT / a["path"]
        if not p.exists() or p.stat().st_size == 0:
            continue
        text, n = pdf_text(p)
        if n and len(text.strip()) / n >= 200:
            parts.append(f"\n\n===== ATTACHMENT: {a['name']} ({a['url']}) =====\n{text}")
            info["pdfs_text"] += 1
        elif 0 < n <= MAX_SCAN_PAGES:
            blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                          "data": base64.b64encode(p.read_bytes()).decode()},
                           "title": a["name"] or "attachment"})
            info["pdfs_scanned"] += 1
        else:
            info["pdfs_skipped"] += 1
    text = "".join(parts)[:MAX_TEXT_CHARS]
    blocks.append({"type": "text", "text": text + "\n\nExtract every qualifying equipment/part record from the matter text and the attachments above."})
    return blocks, info


def extract_matter(client, model: str, slug: str, matter: dict) -> dict:
    cache = CACHE / "extract" / model / f"{slug}-{matter['matter_id']}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    blocks, info = build_content(matter)
    try:
        resp = client.messages.create(
            model=model, max_tokens=16000, system=SYSTEM,
            messages=[{"role": "user", "content": blocks}],
            output_config={"format": {"type": "json_schema", "schema": RECORD_SCHEMA}},
        )
    except anthropic.RequestTooLargeError:
        # Too many scanned PDFs as base64 documents (Broward, 2026-09-07). Retry on the text layer alone.
        info["pdfs_scanned_dropped"] = info.pop("pdfs_scanned", 0)
        blocks = [b for b in blocks if b["type"] == "text"]
        resp = client.messages.create(
            model=model, max_tokens=16000, system=SYSTEM,
            messages=[{"role": "user", "content": blocks}],
            output_config={"format": {"type": "json_schema", "schema": RECORD_SCHEMA}},
        )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"records": []}
    out = {"records": data.get("records", []), "info": info, "stop_reason": resp.stop_reason,
           "usage": {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}, "model": model}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=1))
    return out


def qualifies(matter: dict) -> bool:
    """Send a matter to the model only if it, or one of its PDFs, uses sole-source language."""
    hay = (matter.get("title") or "") + "\n" + (matter.get("text") or "")
    if KEYWORD_RE.search(hay):
        return True
    for a in matter["attachments"]:
        p = ROOT / a["path"]
        if p.exists() and p.stat().st_size and KEYWORD_RE.search(pdf_text(p)[0]):
            return True
    return False


COMPETITIVE_RE = re.compile(
    r"\b(informal bid|formal bid|specification no|request for (proposals?|bids?|quotes?)|rfp|rfq|ifb|sourcewell|naspo|buyboard"
    r"|omnia|cooperative (contract|purchas\w*)|piggyback|lowest responsi\w*|competitive(ly)? (bid|procure)\w*)\b", re.I)
SOLE_RE = re.compile(
    r"sole[- ]source|single[- ]source|proprietary|\bOEM\b|original equipment|obsolete|no longer|discontinued"
    r"|only (authorized|approved|known|available|qualified)|limited vendors|no other (vendor|supplier|source)|exclusive", re.I)


def is_sole_source(r: dict) -> bool:
    """OCSD's monthly 'approved purchases AND additions to the sole source list' mixes competitively bid
    items (Informal Bid, Specification No., Sourcewell/NASPO cooperative contracts) into the same table.
    A row whose stated reason is a bid or a cooperative contract, with no sole-source language, is not ours."""
    reason = r.get("reason") or ""
    return not (COMPETITIVE_RE.search(reason) and not SOLE_RE.search(reason))


def dedupe(records: list[dict]) -> list[dict]:
    """The same purchase is often filed twice (committee, then board). Keep the first."""
    seen, out = set(), []
    for r in records:
        key = (r["client"], (r.get("manufacturer") or "").lower(), (r.get("model") or "").lower(),
               (r.get("part") or "").lower()[:60], r.get("price_usd"))
        if key in seen:
            continue
        seen.add(key); out.append(r)
    return out


def write_store(records: list[dict]):
    db = ROOT / "data" / "records.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    cols = ["id", "agency", "state", "client", "date", "matter_id", "matter_file", "title", "manufacturer", "model", "part",
            "quantity", "price_usd", "lead_time", "sole_source_vendor", "reason", "equipment_class", "installed_location",
            "is_obsolete", "source_url", "legistar_url", "extract_model"]
    con.execute(f"CREATE TABLE records ({', '.join(cols)})")
    con.executemany(f"INSERT INTO records VALUES ({','.join('?' * len(cols))})",
                    [tuple(r.get(c) for c in cols) for r in records])
    con.commit(); con.close()
    with open(ROOT / "data" / "records.jsonl", "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=0, help="max matters per client (0 = all)")
    ap.add_argument("--dry", action="store_true", help="only report what would be sent")
    ap.add_argument("--workers", type=int, default=6, help="parallel model calls (each result is cached, so a crash loses nothing)")
    ap.add_argument("clients", nargs="*")
    a = ap.parse_args()
    load_env()
    client = anthropic.Anthropic()
    slugs = a.clients or [p.stem for p in sorted((ROOT / "data" / "matters").glob("*.json"))]
    all_records, tok_in, tok_out = [], 0, 0
    for slug in slugs:
        d = json.loads((ROOT / "data" / "matters" / f"{slug}.json").read_text())
        meta = CLIENTS.get(slug, {"agency": slug, "state": ""})
        matters = [m for m in d["matters"] if qualifies(m)]
        if a.limit:
            matters = matters[: a.limit]
        n_rec = 0
        if a.dry:
            for m in matters:
                _, info = build_content(m); print(slug, m["matter_id"], info)
            continue
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            outs = list(pool.map(lambda m: extract_matter(client, a.model, slug, m), matters))
        for m, out in zip(matters, outs):
            tok_in += out["usage"]["in"]; tok_out += out["usage"]["out"]
            src = m["attachments"][0]["url"] if m["attachments"] else m["legistar_url"]
            for i, r in enumerate(out["records"]):
                r = dict(r)
                r.update({"id": f"{slug}-{m['matter_id']}-{i}", "agency": meta["agency"], "state": meta["state"], "client": slug,
                          "date": m["intro_date"], "matter_id": m["matter_id"], "matter_file": m["file"], "title": m["title"],
                          "source_url": src, "legistar_url": m["legistar_url"], "extract_model": a.model})
                all_records.append(r); n_rec += 1
        print(f"{slug}: {len(matters)} matters sent, {n_rec} records", flush=True)
    if not a.dry:
        before = len(all_records)
        all_records = dedupe(all_records)
        n_dup = before - len(all_records)
        all_records = [r for r in all_records if is_sole_source(r)]
        write_store(all_records)
        print(f"TOTAL {len(all_records)} records ({n_dup} duplicates, {before - n_dup - len(all_records)} competitively bid rows dropped); "
              f"tokens in={tok_in:,} out={tok_out:,}")


if __name__ == "__main__":
    main()
