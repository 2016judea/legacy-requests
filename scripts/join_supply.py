#!/usr/bin/env python3
"""Join supply listings to index records: "who has one", not just "who needed one".

THE CONTRACT. Every supply source writes one file, data/supply/<source>.jsonl,
one listing per line, with exactly these keys (null when the listing does not
say):

    source        str   short slug, same as the file name: "publicsurplus", "govdeals", "radwell"
    title         str   the listing's own title, verbatim
    manufacturer  str?  as the listing states it
    model         str?  as the listing states it
    part_number   str?  as the listing states it (catalog / MPN / SKU)
    price         num?  the asking price or current bid, in `currency`; null if none shown
    currency      str?  "USD"
    url           str   the listing page a person can open
    seen_at       str   ISO date the listing was fetched (YYYY-MM-DD)
    location      str?  city/state or seller location, when shown

A source adds itself by dropping that file in; this script reads every
data/supply/*.jsonl and needs no change. `validate()` below is the check.
The fetcher that writes it is scripts/supply_<source>.py; `make supply` runs
every one of those, then this join. Fetchers cache raw responses under
data/cache/supply/<source>/ and never re-fetch a cached query.

THE MATCH. Precision beats recall — telling an ops engineer "Radwell has one"
when Radwell has a different drive costs a wasted call and the index's
credibility. A listing matches a record only when BOTH hold:

  1. Manufacturer: a distinctive word of the record's manufacturer (or a known
     alias: Allen-Bradley <-> Rockwell) appears in the listing's manufacturer or
     title.
  2. Part number: a part-number-shaped token from the record's model field (or its part_numbers list)
     equals a token in the listing's part_number, model or title, after
     dropping separators ("1756-IB16" == "1756 IB16" == "1756IB16"). A token is
     part-number-shaped when it has a digit and either a letter or 6+ chars, so
     "2024", "500" and "Series" never match anything on their own.

Writes data/supply/matches.json: {record_id: [listing, ...]}.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUPPLY = ROOT / "data" / "supply"
FIELDS = ["source", "title", "manufacturer", "model", "part_number", "price", "currency", "url", "seen_at", "location"]
REQUIRED = {"source", "title", "url", "seen_at"}

# Words that name no one: dropped before comparing manufacturers.
MFR_STOP = {"inc", "llc", "co", "corp", "corporation", "company", "ltd", "the", "of", "and", "systems", "system",
            "technologies", "technology", "industries", "international", "group", "usa", "america", "north",
            "americas", "motor", "products", "solutions", "services", "manufacturing", "mfg", "electric",
            "electronics", "controls", "control", "equipment", "water", "enterprises", "division", "global"}
ALIASES = [{"allen", "bradley", "allenbradley", "rockwell"}, {"flir", "teledyne"}, {"xylem", "flygt"},
           {"gorman", "gormanrupp"}, {"roots", "dresser"}]
# A part token this common is a word, not a part number.
PART_STOP = {"series", "model", "type", "unit", "kit", "used", "new"}
MODEL_SPLIT = re.compile(r"[\s,;/()\[\]#&+|]+")
# A record that bought "OEM parts for Ford F-350" names the machine the parts
# fit, not the thing bought, so a surplus F-350 truck is not "one". First live
# run (2026-09-24) matched 89 whole GovDeals trucks to exactly that record.
PARTS_CONTRACT = re.compile(r"\bparts\b", re.I)


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def is_part_token(t: str) -> bool:
    if t.lower() in PART_STOP or not re.search(r"\d", t):
        return False
    if re.fullmatch(r"(19|20)\d\d", t):  # a year
        return False
    return len(t) >= 4 and (bool(re.search(r"[A-Z]", t)) or len(t) >= 6)


def part_tokens(text: str) -> set[str]:
    """Part-number-shaped tokens, separators dropped. Adjacent pieces are also
    joined so "1756 IB16" yields "1756IB16"."""
    pieces = [p for p in MODEL_SPLIT.split(str(text or "")) if p]
    raw = set()
    for i, p in enumerate(pieces):
        raw.add(norm(p))
        if i + 1 < len(pieces):
            raw.add(norm(p + pieces[i + 1]))
    return {t for t in raw if is_part_token(t)}


def mfr_words(name: str) -> set[str]:
    words = {w for w in re.findall(r"[a-z0-9]+", str(name or "").lower()) if w not in MFR_STOP and len(w) > 2}
    joined = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    for group in ALIASES:
        if words & group or joined in group:
            words |= group
    return words


def mfr_match(record_mfr: str, listing: dict) -> bool:
    want = mfr_words(record_mfr)
    if not want:
        return False
    hay = " ".join(str(listing.get(k) or "") for k in ("manufacturer", "title")).lower()
    have = set(re.findall(r"[a-z0-9]+", hay))
    have |= {re.sub(r"[^a-z0-9]", "", w) for w in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)+", hay)}
    return bool(want & have)


def match(record: dict, listing: dict) -> bool:
    if not record.get("manufacturer") or not record.get("model"):
        return False
    if PARTS_CONTRACT.search(record.get("part") or ""):
        return False
    want = part_tokens(record["model"])
    for pn in record.get("part_numbers") or []:  # verbatim catalog numbers, when the extract found them
        want |= part_tokens(pn)
    if not want:
        return False
    have = part_tokens(" ".join(str(listing.get(k) or "") for k in ("part_number", "model", "title")))
    return bool(want & have) and mfr_match(record["manufacturer"], listing)


def validate(listing: dict) -> list[str]:
    errs = [f"missing {k}" for k in REQUIRED if not listing.get(k)]
    errs += [f"unknown key {k}" for k in listing if k not in FIELDS]
    if listing.get("price") is not None and not isinstance(listing["price"], (int, float)):
        errs.append("price not a number")
    if listing.get("seen_at") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(listing["seen_at"])):
        errs.append("seen_at not YYYY-MM-DD")
    return errs


def load_listings() -> list[dict]:
    out = []
    for f in sorted(SUPPLY.glob("*.jsonl")):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if not line.strip():
                continue
            listing = json.loads(line)
            errs = validate(listing)
            if errs:
                sys.exit(f"{f.name}:{n}: {', '.join(errs)}")
            out.append({k: listing.get(k) for k in FIELDS})
    return out


def load_records() -> list[dict]:
    return [json.loads(l) for l in (ROOT / "data" / "records.jsonl").read_text().splitlines() if l.strip()]


def join(records: list[dict], listings: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in records:
        hits = [l for l in listings if match(r, l)]
        if hits:
            seen, uniq = set(), []
            for l in hits:
                if l["url"] not in seen:
                    seen.add(l["url"])
                    uniq.append(l)
            out[r["id"]] = sorted(uniq, key=lambda l: (l["price"] is None, l["price"] or 0))
    return out


def main():
    SUPPLY.mkdir(parents=True, exist_ok=True)
    listings = load_listings()
    matches = join(load_records(), listings)
    (SUPPLY / "matches.json").write_text(json.dumps(matches, indent=1, sort_keys=True))
    by_source: dict[str, int] = {}
    for l in listings:
        by_source[l["source"]] = by_source.get(l["source"], 0) + 1
    matched_listings = {l["url"] for ls in matches.values() for l in ls}
    print(f"supply: {len(listings)} listings from {len(by_source)} sources {by_source}")
    print(f"join: {len(matches)} records matched by {len(matched_listings)} listings ({date.today().isoformat()})")


if __name__ == "__main__":
    main()
