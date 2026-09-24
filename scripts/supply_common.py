"""Shared by the supply fetchers: what to search for, and a polite cached HTTP get.

What to search for comes from the index itself — the makes and models already
extracted — so a fetcher never pulls listings no record could match. Two kinds
of query per source:

  - the manufacturer's name ("allen bradley"), which finds listings whose
    title spells the part number differently from how we would search it;
  - each part-number-shaped token of a record's model field, as written.

Every raw response is cached under data/cache/supply/<source>/ keyed by a hash
of the request, and a cached request is never sent again. Delete a file to
refresh it.
"""
import hashlib
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import is_physical  # noqa: E402
from join_supply import MFR_STOP, SUPPLY, load_records, part_tokens  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (compatible; obsolete-parts-index/0.1)"
# Too generic to search by name: they return thousands of vehicles or nothing
# to do with the maker. Their part numbers are still searched.
MFR_QUERY_SKIP = {"ford", "digital", "beam", "duke s", "sony"}
MODEL_SPLIT = re.compile(r"[\s,;/()\[\]#&+|]+")


def mfr_query(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name) if w.lower() not in MFR_STOP]
    return " ".join(words[:2]).lower()


def queries() -> list[str]:
    """Manufacturer names first, then part numbers. Physical records only —
    nobody lists a software licence on a surplus site."""
    mfrs, parts = [], []
    for r in load_records():
        if not (r.get("manufacturer") and r.get("model")) or not is_physical(r):
            continue
        if not part_tokens(r["model"]):
            continue
        q = mfr_query(r["manufacturer"])
        if len(q) >= 4 and q not in MFR_QUERY_SKIP and q not in mfrs:
            mfrs.append(q)
        for piece in MODEL_SPLIT.split(r["model"]):
            if part_tokens(piece) and piece not in parts:
                parts.append(piece)
    return mfrs + parts


class Cache:
    def __init__(self, source: str, delay: float):
        self.dir = ROOT / "data" / "cache" / "supply" / source
        self.dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.last = 0.0
        self.hits = self.fetches = 0

    def get(self, method: str, url: str, **kw) -> tuple[str, str]:
        """(body, the date it was fetched). A cached body keeps its original date."""
        key = hashlib.sha1(json.dumps([method, url, kw.get("params"), kw.get("json")], sort_keys=True).encode()).hexdigest()[:16]
        f = self.dir / f"{key}.txt"
        if f.exists():
            self.hits += 1
            return f.read_text(), date.fromtimestamp(f.stat().st_mtime).isoformat()
        wait = self.delay - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        headers = {"User-Agent": UA, **kw.pop("headers", {})}
        resp = requests.request(method, url, headers=headers, timeout=40, **kw)
        self.last = time.time()
        self.fetches += 1
        resp.raise_for_status()
        f.write_text(resp.text)
        return resp.text, date.today().isoformat()


def write_listings(source: str, listings: list[dict]):
    SUPPLY.mkdir(parents=True, exist_ok=True)
    seen, out = set(), []
    for l in listings:
        if l["url"] not in seen:
            seen.add(l["url"])
            out.append(l)
    out.sort(key=lambda l: l["url"])
    (SUPPLY / f"{source}.jsonl").write_text("".join(json.dumps(l, sort_keys=True) + "\n" for l in out))
    return out
