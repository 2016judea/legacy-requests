#!/usr/bin/env python3
"""Pull sole-source / proprietary-equipment agenda items off PrimeGov public portals.

PrimeGov tenants answer unauthenticated at https://<tenant>.primegov.com:
  /api/v2/PublicPortal/ListArchivedMeetings?year=Y   meetings, each with a documentList
  /Portal/Meeting?meetingTemplateId=<templateId>     the HTML agenda of a document whose
                                                     compileOutputType is 3 ("HTML Agenda")
  /api/compilemeetingattachmenthistory/historyattachment/?historyId=<uid>   an item's PDF
(/Portal/MeetingPreview?compiledMeetingDocumentFileId= redirects to a login; don't use it.)
The HTML agenda carries each item as <div class='meeting-item' data-itemid=N> with its
text and attachment links, so items are filtered locally (agenda_common.wanted) and only
the kept items' PDFs are downloaded. Meetings published only as PDF agendas are skipped.

Output: data/matters/primegov-<tenant>.json in the shape documented in scripts/extract.py.

Usage: scripts/ingest_primegov.py [tenant ...]      (default: every tenant in TENANTS)
"""
import datetime
import html
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from agenda_common import MAX_ATTACHMENTS, SINCE, cached_json, cached_pdf, cached_text, strip_html, wanted, write_matters

P = "primegov"
TENANTS = {   # tenant -> (agency, state). Found by probing subdomains 2026-09-24.
    "ladwp": ("Los Angeles Department of Water and Power", "CA"),
    "lacity": ("City of Los Angeles", "CA"),
    "longbeach": ("City of Long Beach", "CA"),
    "sanantonio": ("City of San Antonio", "TX"),
    "okc": ("City of Oklahoma City", "OK"),
    "lasvegas": ("City of Las Vegas", "NV"),
    "reno": ("City of Reno", "NV"),
    "slc": ("Salt Lake City", "UT"),
    "santafe": ("City of Santa Fe", "NM"),
    "ventura": ("County of Ventura", "CA"),
    "cityofpaloalto": ("City of Palo Alto", "CA"),
    "fremont": ("City of Fremont", "CA"),
    "sanmateo": ("City of San Mateo", "CA"),
    "ranchocucamonga": ("City of Rancho Cucamonga", "CA"),
    "sanbernardino": ("City of San Bernardino", "CA"),
    "renton": ("City of Renton", "WA"),
    "gresham": ("City of Gresham", "OR"),
    "virginiabeach": ("City of Virginia Beach", "VA"),
    "cvwd": ("Coachella Valley Water District", "CA"),
    "wmwd": ("Western Municipal Water District", "CA"),
    "glendaleca": ("City of Glendale", "CA"),
    "norwalk": ("City of Norwalk", "CA"),
    "sanjoseca": ("City of San Jose", "CA"),
    "santaclaracounty": ("County of Santa Clara", "CA"),
    "brazos": ("Brazos County", "TX"),
}
# Two agenda templates: HTML-built items (<div class='meeting-item'>) and Word-built ones
# (<table class="item-table-fromdocx">, Norwalk / San Jose / Santa Clara County).
ITEM_SPLIT = re.compile(r"<(?:div|table)[^>]*class=['\"](?:meeting-item|item-table-fromdocx)['\"][^>]*data-itemid=['\"](\d+)['\"]", re.I)
ATT_RE = re.compile(r"historyattachment/\?historyId=([0-9a-f-]{36})", re.I)
ATT_NAME_RE = re.compile(r"title=['\"]View (.*?) - New Window['\"][^>]*href=['\"][^'\"]*uid=([0-9a-f-]{36})", re.I)


def base(t): return f"https://{t}.primegov.com"


def meetings(tenant: str) -> list[dict]:
    today = datetime.date.today()
    out = []
    for y in range(int(SINCE[:4]), today.year + 1):
        url = f"{base(tenant)}/api/v2/PublicPortal/ListArchivedMeetings?year={y}"
        # past years never change; the current year is re-listed each day
        key = url if y < today.year else f"{today.isoformat()}:{url}"
        out += cached_json(P, key, url) or []
    return [m for m in out if (m.get("dateTime") or "")[:10] >= SINCE]


def item_matters(tenant: str, m: dict) -> list[dict]:
    doc = next((d for d in m.get("documentList") or [] if d.get("compileOutputType") == 3), None)
    if not doc:
        return []
    page_url = f"{base(tenant)}/Portal/Meeting?meetingTemplateId={doc['templateId']}"
    page = cached_text(P, f"{tenant}:agenda:{doc['templateId']}", page_url)
    parts = ITEM_SPLIT.split(page)
    out = []
    for i in range(1, len(parts) - 1, 2):
        item_id, chunk = parts[i], parts[i + 1].split(">", 1)[-1]   # split lands mid-tag
        head = re.search(r"class=['\"]agenda-item['\"][^>]*>(.*?)</(?:div|td)>", chunk, re.S)
        title = strip_html(head.group(1) if head else "")
        text = strip_html(chunk)
        file_no = None
        if len(title) < 40:
            # Los Angeles puts only the Council File number ("23-1328") in the item cell;
            # the description is the first long line after it.
            file_no = title or None
            title = next((ln for ln in text.splitlines() if len(ln) >= 40), title)
        why = wanted(text, title)
        if not why:
            continue
        names = {uid: html.unescape(n) for n, uid in ATT_NAME_RE.findall(chunk)}
        atts = []
        for uid in list(dict.fromkeys(ATT_RE.findall(chunk)))[:MAX_ATTACHMENTS]:
            url = f"{base(tenant)}/api/compilemeetingattachmenthistory/historyattachment/?historyId={uid}"
            path = cached_pdf(P, f"{tenant}:att:{uid}", url)
            if path:
                atts.append({"name": names.get(uid) or "attachment", "url": url, "path": path})
        out.append({
            "matter_id": int(item_id),
            "file": file_no,
            "title": (title or text)[:500],
            "intro_date": (m.get("dateTime") or "")[:10],
            "body": m.get("title"),
            "keyword": why,
            "url": page_url,
            "text": text[:60_000],
            "attachments": atts,
        })
    return out


def ingest(tenant: str):
    ms = meetings(tenant)
    with ThreadPoolExecutor(4) as pool:
        matters = [x for xs in pool.map(lambda m: item_matters(tenant, m), ms) for x in xs]
    seen, uniq = set(), []
    for x in matters:
        if x["matter_id"] not in seen:
            seen.add(x["matter_id"]); uniq.append(x)
    agency, state = TENANTS[tenant]
    sent = write_matters(f"{P}-{tenant}", P, agency, state, uniq)
    return tenant, len(ms), len(uniq), len(sent)


def main(argv):
    with ThreadPoolExecutor(6) as pool:
        for t, n_m, n_i, n_pdf in pool.map(ingest, argv or list(TENANTS)):
            print(f"primegov-{t}: {n_m} meetings, {n_i} items kept, {n_pdf} sent to extract", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
