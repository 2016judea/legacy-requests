#!/usr/bin/env python3
"""Pull sole-source / obsolete-equipment matters off the Legistar public API.

For every client in clients.json and every keyword in KEYWORDS, list matters
introduced since SINCE whose title contains the keyword, then fetch each
matter's text and attachments. Every JSON response and every PDF is cached
under data/cache/ and never re-downloaded; the cache is the source of truth.

Usage: scripts/ingest.py [client ...]      (default: every client in clients.json)
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
CLIENTS = json.loads((ROOT / "clients.json").read_text())
SINCE = "2024-01-01"
API = "https://webapi.legistar.com/v1"
KEYWORDS = [
    "sole source", "single source", "proprietary", "obsolete",
    "no longer manufactured", "discontinued", "OEM", "emergency replacement",
    "spare parts", "replacement parts", "lead time",
    # equipment terms: these catch the matters whose title never says "sole source";
    # extract.py only sends a matter to the model if its text or a PDF uses sole-source language
    "pump", "transformer", "switchgear", "SCADA", "valve", "membrane", "centrifuge", "generator",
]
UA = {"User-Agent": "obsolete-parts/0.1 (public-records research; github.com/2016judea/obsolete-parts)"}


def cached_get(url: str, kind: str, params=None) -> bytes | None:
    """GET once. kind is 'json' or 'pdf'; the cache key is the full URL."""
    full = url + ("?" + requests.compat.urlencode(params) if params else "")
    key = hashlib.sha1(full.encode()).hexdigest()
    path = CACHE / kind / f"{key}.{kind}"
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            r = requests.get(full, headers=UA, timeout=60)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            path.write_bytes(r.content)
            (CACHE / kind / f"{key}.url").write_text(full)
            time.sleep(0.3)
            return r.content
        if r.status_code in (404, 400):
            path.write_bytes(b"")
            (CACHE / kind / f"{key}.url").write_text(full)
            return b""
        time.sleep(2 * (attempt + 1))
    return None


def get_json(url, params=None):
    b = cached_get(url, "json", params)
    if not b:
        return None
    try:
        return json.loads(b)
    except json.JSONDecodeError:
        return None


def list_matters(client: str) -> dict[int, dict]:
    matters = {}
    for kw in KEYWORDS:
        flt = f"substringof('{kw}',MatterTitle) and MatterIntroDate ge datetime'{SINCE}'"
        skip = 0
        while True:
            page = get_json(f"{API}/{client}/matters", {"$filter": flt, "$top": 1000, "$skip": skip})
            if not isinstance(page, list):
                break
            for m in page:
                m["_keyword"] = kw
                matters.setdefault(m["MatterId"], m)
            if len(page) < 1000:
                break
            skip += 1000
    return matters


def matter_text(client: str, mid: int) -> str:
    versions = get_json(f"{API}/{client}/matters/{mid}/versions") or []
    for v in versions:
        for key in (v.get("Key"), v.get("Value")):
            t = get_json(f"{API}/{client}/matters/{mid}/texts/{key}")
            if t and t.get("MatterTextPlain"):
                return t["MatterTextPlain"]
    return ""


def ingest(client: str) -> dict:
    matters = list_matters(client)
    out = {"client": client, "since": SINCE, "matters": []}
    for mid, m in sorted(matters.items()):
        atts = get_json(f"{API}/{client}/matters/{mid}/attachments") or []
        pdfs = []
        for a in atts:
            href = a.get("MatterAttachmentHyperlink") or ""
            if not href.lower().endswith(".pdf"):
                continue
            b = cached_get(href, "pdf")
            if b:
                pdfs.append({"name": a.get("MatterAttachmentName"), "url": href,
                             "path": str((CACHE / "pdf" / f"{hashlib.sha1(href.encode()).hexdigest()}.pdf").relative_to(ROOT))})
        out["matters"].append({
            "matter_id": mid,
            "file": m.get("MatterFile"),
            "title": m.get("MatterTitle"),
            "intro_date": (m.get("MatterIntroDate") or "")[:10],
            "type": m.get("MatterTypeName"),
            "body": m.get("MatterBodyName"),
            "status": m.get("MatterStatusName"),
            "keyword": m["_keyword"],
            "legistar_url": f"https://{client}.legistar.com/LegislationDetail.aspx?ID={mid}&GUID={m.get('MatterGuid','')}",
            "text": matter_text(client, mid),
            "attachments": pdfs,
        })
    return out


def main(argv):
    clients = argv or [c["slug"] for c in CLIENTS]
    (ROOT / "data" / "matters").mkdir(exist_ok=True)
    for c in clients:
        res = ingest(c)
        (ROOT / "data" / "matters" / f"{c}.json").write_text(json.dumps(res, indent=1))
        n_pdf = sum(len(m["attachments"]) for m in res["matters"])
        print(f"{c}: {len(res['matters'])} matters, {n_pdf} pdfs", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
