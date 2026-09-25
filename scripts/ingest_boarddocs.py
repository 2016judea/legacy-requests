#!/usr/bin/env python3
"""Pull sole-source agenda items off BoardDocs (go.boarddocs.com/<state>/<site>/Board.nsf).

BoardDocs has no documented API, but every public site answers the same POST
endpoints its own page calls:

    SEARCH?open            searchstring=<q>&meetings=1&attachments=1  -> HTML list of hits
                           (type="agendaitem" unique=<item id>, or type="file" parentunique=<item id>)
    BD-GetAgendaItem?open  id=<item id>                               -> the item's HTML (meeting, subject, body)
    BD-GetPublicFiles?open id=<item id>                               -> <a class="public-file" href=...> per attachment

For every site in boarddocs.json and every phrase in PHRASES, collect the agenda
items the site's own full-text search returns (it searches attachments too), keep
those whose meeting is on or after SINCE, then cache each item's HTML and its PDF
attachments. Writes data/matters/boarddocs-<state>-<site>.json in the shape
documented at the top of scripts/extract.py, tagged platform=boarddocs.

The site answers 403 to a short User-Agent, 403 again when requests come too fast
(CloudFront rate rule: run one site at a time), and 404 to a site that is not public.
None of it needs a login. Every response is cached under data/cache/boarddocs/
(HTML) and data/cache/pdf/ (PDFs, same key scheme as ingest.py) and never refetched.

Usage: scripts/ingest_boarddocs.py [state/site ...]   (default: every site in boarddocs.json)
"""
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
SITES = json.loads((ROOT / "boarddocs.json").read_text())
SINCE = "2024-01-01"
BASE = "https://go.boarddocs.com"
PHRASES = ['"sole source"', '"single source"', '"sole-source"', "proprietary", "obsolete",
           '"no longer manufactured"', '"end of life"', "discontinued", '"original equipment manufacturer"']
# For a site flagged "item_text_only" in boarddocs.json, an item is kept only if its own text (not
# just an attachment) uses this language. Same words as extract.KEYWORD_RE. Tallahassee's search
# returned 100 qualifying items / 7.4M chars on attachments alone; 19 / 0.6M on item text.
ITEM_RE = re.compile(
    r"\b(sole[- ]source|single[- ]source|proprietary|obsolete|no longer (manufactured|made|supported|available)"
    r"|discontinued|OEM|original equipment manufacturer|emergency replacement|spare parts|replacement parts|lead[- ]time)\b",
    re.I)
MAX_BYTES = 40 << 20   # skip any attachment bigger than this
DELAY = 1.0   # seconds between live requests; run ONE site at a time (see Blocked)


class Blocked(RuntimeError):
    """go.boarddocs.com answered 403: rate-limited. Stop, wait, rerun; the cache resumes."""


# A short UA gets 403 from the WAF; this is an ordinary browser string, no session, no cookies.
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0 Safari/537.36 (public-records research; obsolete-parts index)"}


def _get(method: str, url: str, data: dict | None, kind: str, ext: str) -> bytes | None:
    key = hashlib.sha1((url + ("?" + requests.compat.urlencode(data) if data else "")).encode()).hexdigest()
    path = CACHE / kind / f"{key}.{ext}"
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            r = requests.request(method, url, data=data, headers=UA, timeout=90, stream=True)
            body, t0 = b"", time.time()
            for chunk in r.iter_content(1 << 16):
                body += chunk
                if len(body) > MAX_BYTES or time.time() - t0 > 180:
                    # a 200-page council packet trickled for 16 minutes on 2026-09-24; skip it, uncached
                    r.close()
                    return None
            r._content = body
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            path.write_bytes(r.content)
            (CACHE / kind / f"{key}.url").write_text(url + ("  POST " + json.dumps(data) if data else ""))
            time.sleep(DELAY)
            return r.content
        if r.status_code == 404:
            path.write_bytes(b"")
            return b""
        if r.status_code == 403:
            # CloudFront's rate rule, not a permission answer: never cache it. Fifteen sites in
            # parallel tripped it on 2026-09-24 and every later call 403'd, including /Public.
            raise Blocked(url)
        time.sleep(3 * (attempt + 1))
    return None


def post(site: str, endpoint: str, data: dict) -> str:
    b = _get("POST", f"{BASE}/{site}/Board.nsf/{endpoint}?open", data, "boarddocs", "html")
    return (b or b"").decode("utf-8", "replace")


def strip(h: str) -> str:
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n\n", t)).strip()


def search_items(site: str) -> dict[str, str]:
    """item id -> the date the search result shows (e.g. 'Tue, Oct 9, 2018')."""
    items = {}
    for q in PHRASES:
        h = post(site, "SEARCH", {"searchstring": q, "meetings": "1", "attachments": "1"})
        for m in re.finditer(r'<div class="result[^"]*" type="(\w+)" unique="(\w+)"(?: parentunique="(\w*)")?[^>]*>(.*?)</div>\s*</div>',
                             h, re.S):
            typ, uniq, parent, body = m.groups()
            item = uniq if typ == "agendaitem" else parent if typ == "file" else None
            if not item:
                continue
            d = re.search(r'class="date">([^<]+)', body)
            items.setdefault(item, d.group(1).strip() if d else "")
    return items


def parse_date(s: str) -> str:
    for fmt in ("%a, %b %d, %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def ingest(site: str, meta: dict) -> dict:
    hits = search_items(site)
    out = {"platform": "boarddocs", "agency": meta["agency"], "state": meta["state"], "site": site,
           "since": SINCE, "matters": []}
    for item, shown in sorted(hits.items()):
        date = parse_date(shown)
        if date and date < SINCE:
            continue  # the search result's date is the meeting date; skip old items without fetching them
        raw = post(site, "BD-GetAgendaItem", {"id": item})
        if not raw.strip():
            continue
        text = strip(raw)
        mt = re.search(r"Meeting\s+([A-Z][a-z]{2} \d{1,2}, \d{4})\s*-\s*([^\n]+)", text)
        if mt:
            date = parse_date(mt.group(1)) or date
        if not date or date < SINCE:
            continue
        subj = re.search(r"Subject\s+(.+)", text)
        title = (subj.group(1).strip() if subj else text[:160])[:300]
        files = post(site, "BD-GetPublicFiles", {"id": item})
        atts = []
        for href, name in re.findall(r'<a class="public-file"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', files):
            url = BASE + html.unescape(href)
            if not url.lower().endswith(".pdf"):
                continue
            b = _get("GET", url, None, "pdf", "pdf")
            if b:
                atts.append({"name": html.unescape(name).strip(), "url": url,
                             "path": f"data/cache/pdf/{hashlib.sha1(url.encode()).hexdigest()}.pdf"})
        if meta.get("item_text_only") and not ITEM_RE.search(title + "\n" + text):
            continue  # big city packets: keep only items whose OWN text says sole source (see boarddocs.json)
        out["matters"].append({
            "matter_id": item, "title": title, "intro_date": date,
            "body": mt.group(2).strip() if mt else None,
            "url": f"{BASE}/{site}/Board.nsf/goto?open&id={item}",
            "text": text[text.find("Agenda Item Details"):] if "Agenda Item Details" in text else text,
            "attachments": atts,
        })
    return out


def main(argv):
    sites = {s["site"]: s for s in SITES}
    todo = argv or list(sites)
    for site in todo:
        meta = sites.get(site, {"agency": site, "state": site.split("/")[0].upper()[:2]})
        try:
            res = ingest(site, meta)
        except Blocked as e:
            sys.exit(f"BLOCKED (403) at {e}; wait and rerun, the cache keeps everything fetched so far")
        slug = "boarddocs-" + site.replace("/", "-")
        (ROOT / "data" / "matters" / f"{slug}.json").write_text(json.dumps(res, indent=1))
        print(f"{slug}: {len(res['matters'])} items since {SINCE}, "
              f"{sum(len(m['attachments']) for m in res['matters'])} pdfs", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
