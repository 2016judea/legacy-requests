#!/usr/bin/env python3
"""Prove the supply join: fixed cases it must get right, then the live counts.

Run: make check. Exits non-zero on any failure. The counts it prints are read
off data/supply/*.jsonl and data/records.jsonl, never typed.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from join_supply import SUPPLY, join, load_listings, load_records, match, part_tokens, validate  # noqa: E402

AB = {"id": "x", "manufacturer": "Allen-Bradley", "model": "1756-IB16"}
FLIR = {"id": "y", "manufacturer": "Teledyne FLIR", "model": "VIP3D.1s #7250-117"}
XYLEM = {"id": "z", "manufacturer": "Xylem", "model": "6626"}


def L(title, **kw):
    return {"source": "t", "title": title, "url": "u", "seen_at": "2026-09-24", **kw}


CASES = [
    # (record, listing, should_match, why)
    (AB, L("Allen-Bradley 1756-IB16 ControlLogix Input Module"), True, "exact"),
    (AB, L("ALLEN BRADLEY 1756 IB16 DC INPUT"), True, "separator differs"),
    (AB, L("Rockwell Automation 1756IB16"), True, "alias + no separator"),
    (AB, L("Allen-Bradley 1756-IB16D Diagnostic Input"), False, "a different part (suffix)"),
    (AB, L("Siemens 1756-IB16 compatible module"), False, "right number, wrong maker"),
    (AB, L("Allen-Bradley PowerFlex 755 drive"), False, "right maker, no number"),
    (FLIR, L("FLIR 7250-117 VIP3D processor board"), True, "second token in model field"),
    (FLIR, L("Teledyne FLIR thermal camera 7250"), False, "prefix of the number only"),
    (XYLEM, L("Xylem 6626 diffuser"), False, "4-digit bare number is not a part number"),
]


def main():
    bad = 0
    for rec, lst, want, why in CASES:
        got = match(rec, lst)
        if got != want:
            bad += 1
            print(f"FAIL {why}: {rec['model']!r} vs {lst['title']!r} -> {got}, want {want}")
    assert "2024" not in part_tokens("T10x (2024) Tablet"), "a year must not be a part token"
    assert validate(L("x", price="12")) == ["price not a number"]
    print(f"cases: {len(CASES) - bad}/{len(CASES)} pass")

    listings = load_listings()
    records = load_records()
    matches = join(records, listings)
    stored = json.loads((SUPPLY / "matches.json").read_text()) if (SUPPLY / "matches.json").exists() else None
    if stored is not None and stored != matches:
        bad += 1
        print("FAIL data/supply/matches.json is stale: run make join")
    # every match must satisfy the rule when re-checked from scratch
    by_id = {r["id"]: r for r in records}
    for rid, ls in matches.items():
        for l in ls:
            if not match(by_id[rid], l):
                bad += 1
                print(f"FAIL {rid} does not re-match {l['url']}")
    print(f"live: {len(listings)} listings, {len(matches)} of {len(records)} records matched")
    for rid, ls in sorted(matches.items()):
        r = by_id[rid]
        print(f"  {r['manufacturer']} {r['model']} ({r['agency']}) <- {len(ls)}: " +
              "; ".join(f"[{l['source']}] {l['title'][:60]}" for l in ls[:3]))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
