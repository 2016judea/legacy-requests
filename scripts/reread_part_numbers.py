#!/usr/bin/env python3
"""Re-read part numbers on records extracted before the schema had `part_numbers` (2026-09-24).

extract.py caches one model response per matter and never re-runs it, so re-running `make extract`
returns the OLD responses (no part_numbers) at $0 and changes nothing. This script calls the model
fresh for exactly those matters, then merges ONLY `part_numbers` into the cached response. Every other
field keeps the value from the original read: a second read is not a better read, and the page's
prices, reasons and manufacturers were already reviewed on the first.

Targets: matters with at least one record in records.jsonl that lacks the part_numbers key and is
physical equipment (anything but "service/maintenance contract").

Each new raw response is kept at data/cache/extract/<model>/reread-pn/<slug>-<id>.json, so a crash or
rerun never pays twice. A new record is paired to an old one by manufacturer + model (normalised); an old
record with no pair is left without the key (still "not read"), never given another record's numbers.
A part number is kept only if it appears verbatim (separators ignored) in the matter's text layer, unless
the matter had scanned PDFs the model read as images and the text layer cannot confirm it.

Usage: scripts/reread_part_numbers.py [--dry] [--limit N] [--workers 6]; then extract.py --cached-only.
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anthropic  # noqa: E402
from extract import CACHE, DEFAULT_MODEL, RECORD_SCHEMA, ROOT, SYSTEM, attachment_text, build_content, load_env  # noqa: E402

PHYSICAL_EXCLUDE = {"service/maintenance contract"}


def norm(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def targets(model: str) -> list[tuple[str, dict]]:
    recs = [json.loads(l) for l in (ROOT / "data" / "records.jsonl").read_text().splitlines() if l.strip()]
    want = {(r["client"], str(r["matter_id"])) for r in recs
            if "part_numbers" not in r and r["equipment_class"] not in PHYSICAL_EXCLUDE and r["extract_model"] == model}
    out = []
    for slug in sorted({c for c, _ in want}):
        d = json.loads((ROOT / "data" / "matters" / f"{slug}.json").read_text())
        out += [(slug, m) for m in d["matters"] if (slug, str(m["matter_id"])) in want]
    return out


def call(client, model: str, slug: str, matter: dict) -> dict:
    raw = CACHE / "extract" / model / "reread-pn" / f"{slug}-{matter['matter_id']}.json"
    if raw.exists():
        return json.loads(raw.read_text())
    blocks, info = build_content(matter)
    try:
        resp = client.messages.create(model=model, max_tokens=16000, system=SYSTEM,
                                      messages=[{"role": "user", "content": blocks}],
                                      output_config={"format": {"type": "json_schema", "schema": RECORD_SCHEMA}})
    except anthropic.RequestTooLargeError:
        info["pdfs_scanned_dropped"] = info.pop("pdfs_scanned", 0)
        blocks = [b for b in blocks if b["type"] == "text"]
        resp = client.messages.create(model=model, max_tokens=16000, system=SYSTEM,
                                      messages=[{"role": "user", "content": blocks}],
                                      output_config={"format": {"type": "json_schema", "schema": RECORD_SCHEMA}})
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    try:
        records = json.loads(text).get("records", [])
    except json.JSONDecodeError:
        records = []
    out = {"records": records, "info": info, "stop_reason": resp.stop_reason, "fresh": True,
           "usage": {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}, "model": model}
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps(out, indent=1))
    return out


def source_text(matter: dict) -> str:
    return norm((matter.get("title") or "") + (matter.get("text") or "") +
                "".join(attachment_text(a) for a in matter.get("attachments", [])))


def merge(old: dict, new: dict, matter: dict) -> tuple[int, int, int]:
    """Write part_numbers onto old records in place. Returns (paired, numbers kept, numbers dropped)."""
    hay = source_text(matter)
    scanned = bool(new["info"].get("pdfs_scanned"))
    pool = list(new["records"])
    paired = kept = dropped = 0
    for r in old["records"]:
        if "part_numbers" in r:
            continue
        key = (norm(r.get("manufacturer")), norm(r.get("model")))
        cand = [n for n in pool if (norm(n.get("manufacturer")), norm(n.get("model"))) == key]
        if not cand and key[1]:  # same model, manufacturer spelled differently
            cand = [n for n in pool if norm(n.get("model")) == key[1]]
        if not cand:
            continue
        n = cand[0]
        pool.remove(n)
        pns = []
        for pn in n.get("part_numbers") or []:
            if norm(pn) and (norm(pn) in hay or scanned):
                pns.append(pn)
            else:
                dropped += 1
        r["part_numbers"] = pns
        paired += 1
        kept += len(pns)
    return paired, kept, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    todo = targets(a.model)
    if a.limit:
        todo = todo[: a.limit]
    est_in = est_out = 0
    for slug, m in todo:
        u = json.loads((CACHE / "extract" / a.model / f"{slug}-{m['matter_id']}.json").read_text())["usage"]
        est_in += u["in"]; est_out += u["out"]
    print(f"{len(todo)} matters; first read used in={est_in:,} out={est_out:,} -> est ${est_in * 3e-6 + est_out * 15e-6:.2f}", flush=True)
    if a.dry:
        return
    load_env()
    client = anthropic.Anthropic()
    fresh_before = {(s, m["matter_id"]) for s, m in todo
                    if (CACHE / "extract" / a.model / "reread-pn" / f"{s}-{m['matter_id']}.json").exists()}
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        news = list(pool.map(lambda sm: call(client, a.model, *sm), todo))
    t_in = t_out = n_new = paired = kept = dropped = 0
    for (slug, m), new in zip(todo, news):
        if (slug, m["matter_id"]) not in fresh_before:
            t_in += new["usage"]["in"]; t_out += new["usage"]["out"]; n_new += 1
        f = CACHE / "extract" / a.model / f"{slug}-{m['matter_id']}.json"
        old = json.loads(f.read_text())
        p, k, d = merge(old, new, m)
        paired += p; kept += k; dropped += d
        old.setdefault("reread_pn", {"usage": new["usage"], "stop_reason": new["stop_reason"]})
        f.write_text(json.dumps(old, indent=1))
    print(f"THIS RUN: {n_new} new model calls, in={t_in:,} out={t_out:,}, ${t_in * 3e-6 + t_out * 15e-6:.2f}")
    print(f"merged: {paired} old records paired, {kept} part numbers kept, {dropped} dropped (not verbatim in the text layer)")


if __name__ == "__main__":
    main()
