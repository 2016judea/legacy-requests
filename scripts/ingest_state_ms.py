#!/usr/bin/env python3
"""Mississippi: every "SOLE SOURCE NOTICES" posting on the state bid search -> data/matters/state-ms.json.

Mississippi agencies and universities post each proposed sole-source purchase on
ms.gov/dfa/contract_bid_search (sub-category 13, "SOLE SOURCE NOTICES"). The grid
behind the page is a public DataTables endpoint, POST only, no login:

    POST /dfa/contract_bid_search/Bid/BidData?AppId=1&SubProcurementCategoryID=13&Status=<s>
         (form body = the DataTables server-side params; without Status it returns only Open)

Each row carries the agency, a description that usually names the item, and links to
the notice PDFs on SRM.MAGIC.MS.GOV. The justification PDFs (up to two per notice) are
cached and handed to extract.py, which reads a text layer or, for scans, the image.

Cached under data/cache/json/state-ms/ and data/cache/pdf/; never re-fetched.
Usage: scripts/ingest_state_ms.py
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
URL = "https://www.ms.gov/dfa/contract_bid_search/Bid/BidData"
PAGE = "https://www.ms.gov/dfa/contract_bid_search/Bid/Details/{}"
JCACHE = ROOT / "data" / "cache" / "json" / "state-ms"
PCACHE = ROOT / "data" / "cache" / "pdf"
H = {"User-Agent": "Mozilla/5.0 (obsolete-parts-index; public records research)", "X-Requested-With": "XMLHttpRequest"}
BODY = ("sEcho=1&iColumns=8&sColumns=&iDisplayStart=0&iDisplayLength=9999&iSortCol_0=5&sSortDir_0=desc&iSortingCols=1"
        "&mDataProp_0=Agency&mDataProp_1=BidNumber&mDataProp_2=ObjectID&mDataProp_3=VerNumber&mDataProp_4=BidStatus"
        "&mDataProp_5=AdvertiseDate&mDataProp_6=SubmissionDate&mDataProp_7=OpeningDate")
WANT_DOC = re.compile(r"sole|justif|notice|letter|determination|questionnaire", re.I)
SKIP_DOC = re.compile(r"newspaper|advertisement|word|\bURL\b|contract", re.I)


def rows() -> list[dict]:
    JCACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for status in ("Open", "Closed", "Awarded", "Archived"):
        p = JCACHE / f"{status}.json"
        if not p.exists():
            r = requests.post(f"{URL}?AppId=1&SubProcurementCategoryID=13&Status={status}", data=BODY, headers={**H, "Content-Type": "application/x-www-form-urlencoded"}, timeout=300)
            r.raise_for_status()
            p.write_text(r.text)
        for row in json.loads(p.read_text())["aaData"]:
            out[row["BidID"]] = row
    return list(out.values())


def ms_date(v: str | None) -> str:
    m = re.search(r"\d+", v or "")
    return datetime.fromtimestamp(int(m.group()) / 1000, tz=timezone.utc).date().isoformat() if m else ""


def fetch_pdf(att: dict) -> str | None:
    p = PCACHE / f"state-ms-{att['AttachmentID']}.pdf"
    if not p.exists():
        try:
            r = requests.get(att["Url"], headers={"User-Agent": H["User-Agent"]}, timeout=120)
        except requests.RequestException:
            return None
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            return None
        p.write_bytes(r.content)
    return str(p.relative_to(ROOT))


def main():
    PCACHE.mkdir(parents=True, exist_ok=True)
    matters = []
    for r in rows():
        docs = [a for a in r.get("Attachments") or [] if WANT_DOC.search(a["Description"] or "") and not SKIP_DOC.search(a["Description"] or "")][:2]
        atts = []
        for a in docs:
            path = fetch_pdf(a)
            if path:
                atts.append({"name": a["Description"], "url": a["Url"], "path": path})
        agency = (r.get("Agency") or "").strip() or "Mississippi Information Technology Services"
        matters.append({
            "matter_id": str(r["BidID"]), "title": re.sub(r"\s+", " ", r.get("BidDescription") or "")[:300],
            "intro_date": ms_date(r.get("AdvertiseDate")), "file": r.get("BidNumber"), "url": PAGE.format(r["BidID"]),
            "agency": agency.title().replace("Ms ", "Mississippi ").replace("Univ Of", "University of").replace(" Of ", " of "),
            "text": "SOLE SOURCE NOTICE (Mississippi)\n" + (r.get("BidDescription") or "") + "\n" + (r.get("AdditionalInfo") or ""),
            "attachments": atts,
        })
    out = ROOT / "data" / "matters" / "state-ms.json"
    out.write_text(json.dumps({"platform": "state-ms", "agency": "State of Mississippi", "state": "MS", "matters": matters}, indent=1))
    print(f"wrote {out.relative_to(ROOT)}: {len(matters)} notices, {sum(len(m['attachments']) for m in matters)} PDFs")


if __name__ == "__main__":
    main()
