"""Which agencies run which equipment family, from the filings we already hold.

Scans every matter's own text and attachment text (the same text extract.py reads)
for the family regexes in eol_families.py. One install row per (agency, family),
with up to 3 citations: the filing URL, its date, and the sentence that names it.
Output: data/eol/installs.json. $0, no network.
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from eol_families import FAMILIES  # noqa: E402

CLIENTS = {c["slug"]: c for c in json.loads((ROOT / "clients.json").read_text())}
for extra in ("granicus.json", "boarddocs.json"):
    p = ROOT / extra
    if p.exists():
        try:
            for c in json.loads(p.read_text()):
                if isinstance(c, dict) and c.get("slug"):
                    CLIENTS.setdefault(c["slug"], c)
        except Exception:
            pass
RX = [(fid, oem, fam, re.compile(rx, re.I)) for fid, oem, fam, rx in FAMILIES]


def text_of(a):
    if a.get("text"):
        return a["text"]
    p = ROOT / a["path"] if a.get("path") else None
    if p and p.suffix.lower() == ".pdf":
        t = p.with_suffix(".txt")
        if t.exists() and t.stat().st_size:
            return t.read_text(errors="replace")
        t = ROOT / "data/eol/text" / (p.stem + ".txt")  # pdftotext fill-in for PDFs extract.py never read
        return t.read_text(errors="replace") if t.exists() else ""
    if p and p.exists():
        return p.read_text(errors="replace")
    return ""


def snippet(text, m):
    s = max(text.rfind("\n", 0, m.start()), text.rfind(". ", 0, m.start()), m.start() - 160)
    e = m.end() + 160
    for stop in (". ", "\n\n"):
        k = text.find(stop, m.end())
        if k != -1:
            e = min(e, k + 1)
    out = re.sub(r"\s+", " ", text[s:e]).strip(" .\n")[:260]
    return out or re.sub(r"\s+", " ", text[max(0, m.start() - 80):m.end() + 80]).strip()


def agency_for(slug, d, matter):
    # records carry the canonical agency name; fall back to clients.json, then the slug
    return (matter.get("agency") or d.get("agency") or CLIENTS.get(slug, {}).get("agency")
            or CLIENTS.get(slug.split("-", 1)[-1], {}).get("agency") or slug)


def main():
    rec_agency = {}
    for line in open(ROOT / "data/records.jsonl"):
        r = json.loads(line)
        rec_agency[(r["client"], str(r["matter_id"]))] = (r["agency"], r.get("state"))
    hits = defaultdict(list)
    for f in sorted((ROOT / "data/matters").glob("*.json")):
        d = json.loads(f.read_text())
        slug = d.get("client") or f.stem
        for m in d.get("matters", []):
            docs = [((m.get("title") or "") + "\n" + (m.get("text") or ""), m.get("legistar_url") or m.get("url"))]
            atts = m.get("attachments") or []
            if isinstance(atts, str):
                try: atts = json.loads(atts)
                except Exception: atts = []
            for a in atts:
                docs.append((text_of(a), a.get("url")))
            ag = rec_agency.get((slug, str(m.get("matter_id"))))
            agency, state = ag if ag else (agency_for(slug, d, m), CLIENTS.get(slug, {}).get("state"))
            for text, url in docs:
                if not text or not url:
                    continue
                for fid, oem, fam, rx in RX:
                    mm = rx.search(text)
                    if mm:
                        hits[(agency, fid)].append({
                            "url": url, "date": (m.get("intro_date") or m.get("date") or "")[:10],
                            "title": (m.get("title") or "")[:200].strip(), "quote": snippet(text, mm),
                            "state": state,
                        })
    # the extracted records themselves (make/model/part fields), cited to their filing
    for line in open(ROOT / "data/records.jsonl"):
        r = json.loads(line)
        text = " ".join(str(r.get(k) or "") for k in ("manufacturer", "model", "part", "part_numbers", "reason"))
        for fid, oem, fam, rx in RX:
            mm = rx.search(text)
            if mm:
                hits[(r["agency"], fid)].append({"url": r.get("legistar_url") or r["source_url"], "date": r.get("date") or "",
                    "title": (r.get("title") or "")[:200].strip(), "quote": snippet(text, mm), "state": r.get("state")})
    out = []
    for (agency, fid), cs in hits.items():
        seen, cites = set(), []
        for c in sorted(cs, key=lambda c: c["date"], reverse=True):
            if c["url"] in seen:
                continue
            seen.add(c["url"]); cites.append(c)
        out.append({"agency": agency, "state": cites[0]["state"], "family": fid, "filings": len(cites), "cites": cites[:3]})
    out.sort(key=lambda r: (r["family"], r["agency"]))
    (ROOT / "data/eol").mkdir(exist_ok=True)
    (ROOT / "data/eol/installs.json").write_text(json.dumps(out, indent=1))
    by = defaultdict(set)
    for r in out:
        by[r["family"]].add(r["agency"])
    for fid, ags in sorted(by.items(), key=lambda x: -len(x[1])):
        print(f"{fid:16} {len(ags):3}  {', '.join(sorted(ags))[:150]}")
    print(len(out), "install rows,", len({r['agency'] for r in out}), "agencies")


if __name__ == "__main__":
    main()
