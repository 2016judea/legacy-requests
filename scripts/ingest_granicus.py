#!/usr/bin/env python3
"""Pull sole-source agenda items off Granicus agenda sites (<host>.granicus.com).

Granicus has no search API, so this walks each site's public meeting list
(ViewPublisher.php?view_id=N), opens every agenda since SINCE and finds the items
that are sole-source purchases. An agenda arrives in one of four shapes, all handled:

  1. Agenda-management HTML on S3 (IEUA, Contra Costa WD): each item links a staff
     report page (HTML on cloudfront) or PDFs under /services/legistar/download/.
  2. GeneratedAgendaViewer.php (CVWD, Elk Grove, Encinitas): items link MetaViewer.php,
     which serves the item's PDF.
  3. A short agenda PDF whose link annotations point at each item's PDF (WSSC, Tampa Bay).
  4. A full agenda packet PDF, hundreds of pages (LADWP, SamTrans, Metrolink): the staff
     reports are inside it, so the matter is a window of pages around each hit.

Every item whose label or context names equipment, or whose text uses sole-source
language, has its document fetched; it becomes a matter only if the document itself
uses sole-source language (SOLE_RE). Agendas served from a Legistar host
(legistar1.com, legistar.granicus.com) are skipped: those belong to scripts/ingest.py.

Every response is cached under data/cache/ (HTML in granicus/, PDFs in pdf/) and never
re-downloaded. Output: data/matters/granicus-<slug>.json in the shape extract.py documents.
No login, no CAPTCHA: public pages only.

Usage: scripts/ingest_granicus.py [slug ...]      (default: every site in granicus.json)
"""
import faulthandler
import hashlib
import html as htmllib
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests

faulthandler.register(__import__('signal').SIGUSR1)  # kill -USR1 <pid> prints every thread's stack

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
SITES = json.loads((ROOT / "granicus.json").read_text())
SINCE = "2024-01-01"
UA = {"User-Agent": "obsolete-parts/0.1 (public-records research; github.com/2016judea/obsolete-parts)"}
MAX_PDF_BYTES = 120_000_000      # a packet bigger than this is skipped
PACKET_PAGES = 30                # an agenda PDF longer than this is a packet: windows, not links
WINDOW = (1, 4)                  # pages before / after a hit page that go into a packet matter
MAX_INLINE = 40_000              # chars of inline text per attachment

# Sole-source language, strict: gates whether a fetched document becomes a matter.
SOLE_RE = re.compile(
    r"sole[- ]source|single[- ]source|sole[- ]brand|brand[- ]name (only|specific)|no longer (manufactured|made|supported|available|produced)"
    r"|\bobsolete\b|end[- ]of[- ](life|support)|proprietary (equipment|parts?|system|software|technology|design|product|components?)"
    r"|(only|sole|exclusive) (authorized |factory[- ]authorized )?(distributor|dealer|supplier|provider|representative|source|manufacturer)"
    r"|OEM (parts|equipment|replacement)|original equipment manufacturer", re.I)
# Equipment / purchase words in an item's label: worth opening the document to look.
EQUIP_RE = re.compile(
    r"sole|single.source|proprietary|purchas|procure|equipment|replac|pump|valve|motor|generator|switchgear|transformer|scada|\bplc\b"
    r"|\bvfd|drive|parts|repair|rebuild|overhaul|upgrade|instrument|analy[sz]er|membrane|centrifuge|blower|compressor|chlorin|\buv\b"
    r"|filter|meter|vehicle|\bbus(es)?\b|locomotive|rail ?car|radio|\boem\b|obsolete|brand|crane|elevator|escalator|turbine|breaker"
    r"|actuator|controls?\b|hvac|chiller|boiler|sensor|camera|fare|signal|dredg|screen|clarifier|digester|conveyor|press\b", re.I)
# Documents that define "sole source" without buying anything: policies, budgets, minutes, audits.
NOISE_RE = re.compile(r"polic(y|ies)|budget|minutes|audit|ordinance|charter|salary|investment|treasurer|financial (report|statement)"
                      r"|legislative|calendar|agenda\b|strategic plan|annual report|\bcip\b|capital improvement (program|plan)|rates?\b", re.I)
SKIP_HREF = re.compile(r"^(mailto:|javascript:|#)|MediaPlayer\.php|ASX\.php|/player/|\.(mp4|mp3|m3u8|jpg|png|gif)$", re.I)
DOC_HREF = re.compile(r"MetaViewer\.php|DocumentViewer\.php|/services/legistar/download/|cloudfront\.net/|amazonaws\.com/|kentico\.|\.pdf$", re.I)
LEGISTAR_HOST = re.compile(r"legistar", re.I)


# ----------------------------------------------------------------------------- fetch + cache

def fetch(url: str) -> tuple[str, bytes, str]:
    """GET once; returns (kind, bytes, final_url) where kind is 'pdf', 'html' or ''. Cached forever."""
    key = hashlib.sha1(url.encode()).hexdigest()
    meta_p = CACHE / "granicus" / f"{key}.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
        p = ROOT / meta["path"] if meta.get("path") else None
        return meta["kind"], (p.read_bytes() if p and p.exists() else b""), meta.get("final_url", url)
    meta_p.parent.mkdir(parents=True, exist_ok=True)
    kind, body, final = "", b"", url
    for attempt in range(3):
        try:
            with get_following(url) as r:
                final = r.url
                if r.status_code in (400, 403, 404, 410):
                    break
                if r.status_code != 200:
                    time.sleep(3 * (attempt + 1)); continue
                chunks, size = [], 0
                for c in r.iter_content(1 << 20):
                    chunks.append(c); size += len(c)
                    if size > MAX_PDF_BYTES:
                        chunks = []; break
                body = b"".join(chunks)
                ct = r.headers.get("content-type", "").lower()
                kind = "pdf" if body[:5] == b"%PDF-" else ("html" if body and ("html" in ct or body.lstrip()[:1] == b"<") else "")
                break
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
    else:
        return "", b"", url  # transient failure: not cached, retried next run
    path = None
    if kind == "pdf":
        path = CACHE / "pdf" / f"{key}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body); (CACHE / "pdf" / f"{key}.url").write_text(url)
    elif kind == "html":
        path = CACHE / "granicus" / f"{key}.html"
        path.write_bytes(body)
    meta_p.write_text(json.dumps({"url": url, "final_url": final, "kind": kind,
                                  "path": str(path.relative_to(ROOT)) if path else None}))
    time.sleep(0.25)
    return kind, body, final


def s3_path_style(url: str) -> str:
    """Granicus's bucket has underscores in its name, so its virtual-host URL fails TLS hostname
    verification (curl shrugs, requests refuses). The path-style URL serves the same object."""
    return re.sub(r"^https?://([a-z0-9_.-]*_[a-z0-9_.-]*)\.s3\.amazonaws\.com/", r"https://s3.amazonaws.com/\1/", url)


def get_following(url: str, hops: int = 8):
    """requests.get with redirects followed by hand, so every hop goes through s3_path_style."""
    for _ in range(hops):
        r = requests.get(s3_path_style(url), headers=UA, timeout=(20, 120), stream=True, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urljoin(r.url, r.headers["location"]); r.close(); continue
        return r
    return r


def pdf_pages(url: str) -> list[str]:
    """Text of each page (pdftotext -layout), cached beside the PDF as .pages.json."""
    p = CACHE / "pdf" / f"{hashlib.sha1(url.encode()).hexdigest()}.pdf"
    j = p.with_suffix(".pages.json")
    if j.exists():
        return json.loads(j.read_text())
    try:
        out = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, timeout=600).stdout.decode("utf-8", "replace")
        pages = out.split("\f")
    except Exception:  # noqa: BLE001 - a broken PDF is an empty one
        pages = []
    j.write_text(json.dumps(pages))
    return pages


def pdf_links(url: str) -> list[tuple[int, str]]:
    """(page index, uri) for every link annotation in a short PDF."""
    import pdfplumber
    p = CACHE / "pdf" / f"{hashlib.sha1(url.encode()).hexdigest()}.pdf"
    out = []
    try:
        with pdfplumber.open(p) as doc:
            for i, pg in enumerate(doc.pages):
                for h in pg.hyperlinks:
                    if h.get("uri"):
                        out.append((i, h["uri"]))
    except Exception:  # noqa: BLE001
        pass
    return out


def html_text(body: bytes) -> str:
    h = body.decode("utf-8", "replace")
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<(br|p|div|li|tr|h\d)[^>]*>", "\n", h)
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", h)).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def resolve(url: str) -> str:
    """Unwrap docs.google.com/gview?url=... wrappers."""
    u = urlparse(url)
    if u.netloc.endswith("docs.google.com") and "url" in parse_qs(u.query):
        return parse_qs(u.query)["url"][0]
    return url


# ----------------------------------------------------------------------------- meetings

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def row_date(row: str) -> str | None:
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", row)).replace("\xa0", " ")
    m = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d)", t)
    if m:
        return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", t)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", t)
    return m.group(0) if m else None


def meetings(host: str, view: int) -> list[dict]:
    kind, body, _ = fetch_fresh(f"https://{host}.granicus.com/ViewPublisher.php?view_id={view}")
    out, seen = [], set()
    for row in re.split(r"(?i)<tr", body.decode("utf-8", "replace")):
        m = re.search(r"AgendaViewer\.php\?view_id=\d+&(?:amp;)?(?:clip_id|event_id)=\d+", row)
        d = row_date(row)
        if not m or not d or d < SINCE:
            continue
        url = f"https://{host}.granicus.com/" + m.group(0).replace("&amp;", "&")
        if url in seen:
            continue
        seen.add(url)
        name = re.search(r'(?is)<td[^>]*(?:headers="Name|class="listItem")[^>]*>(.*?)</td>', row)
        out.append({"url": url, "date": d, "name": re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", name.group(1)))).strip()[:120] if name else ""})
    return out


def fetch_fresh(url: str):
    """The meeting list changes weekly, so it is re-read each run (still written to cache for the record)."""
    r = requests.get(url, headers=UA, timeout=60)
    return "html", r.content, r.url


# ----------------------------------------------------------------------------- items

def html_items(body: bytes, base: str) -> list[dict]:
    """Anchors in document order, each with the text around it (the item's own words)."""
    h = body.decode("utf-8", "replace")
    anchors = list(re.finditer(r'(?is)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', h))
    items = []
    for i, a in enumerate(anchors):
        href = htmllib.unescape(a.group(1)).strip()
        label = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", a.group(2)))).strip()
        prev_end = anchors[i - 1].end() if i else max(0, a.start() - 3000)
        next_start = anchors[i + 1].start() if i + 1 < len(anchors) else a.end() + 3000
        before = html_text(h[prev_end:a.start()].encode())[-800:]
        after = html_text(h[a.end():next_start].encode())[:1500]
        items.append({"label": label, "href": None if SKIP_HREF.search(href) else urljoin(base, href),
                      "context": f"{before}\n{label}\n{after}".strip()})
    return items


def doc_to_attachments(label: str, url: str) -> tuple[list[dict], str]:
    """Fetch one item document. Returns (attachments, text) when it uses sole-source language, else ([], '')."""
    kind, body, final = fetch(url)
    if kind == "pdf":
        pages = pdf_pages(url)
        text = "\n".join(pages)
        if not SOLE_RE.search(text):
            return [], ""
        key = hashlib.sha1(url.encode()).hexdigest()
        if len(pages) <= 15:
            return [{"name": label, "url": final, "path": f"data/cache/pdf/{key}.pdf"}], text
        return [{"name": f"{label} (pages {a + 1}-{b})", "url": f"{final}#page={a + 1}", "text": t}
                for a, b, t in windows(pages)], text
    if kind == "html":
        text = html_text(body)
        if not SOLE_RE.search(text):
            return [], ""
        atts = [{"name": label, "url": final, "text": text[:MAX_INLINE]}]
        for c in re.findall(r'(?i)href="([^"]+\.pdf)"', body.decode("utf-8", "replace"))[:6]:
            c = urljoin(final, htmllib.unescape(c))
            k, _, cf = fetch(c)
            if k == "pdf" and len(pdf_pages(c)) <= 15:
                atts.append({"name": Path(urlparse(c).path).name, "url": cf,
                             "path": f"data/cache/pdf/{hashlib.sha1(c.encode()).hexdigest()}.pdf"})
        return atts, text
    return [], ""


def windows(pages: list[str]) -> list[tuple[int, int, str]]:
    """Merge hit pages into windows [start, end) of WINDOW pages around each; cap each window's text."""
    hits = [i for i, t in enumerate(pages) if SOLE_RE.search(t)]
    spans = []
    for i in hits:
        a, b = max(0, i - WINDOW[0]), min(len(pages), i + WINDOW[1] + 1)
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    return [(a, b, "\n".join(pages[a:b])[:MAX_INLINE]) for a, b in spans]


def first_hit_key(text: str) -> str:
    """The same staff report is printed in the committee packet and again in the board packet.
    Key a packet window on its first sole-source paragraph so the second printing is dropped."""
    m = SOLE_RE.search(text)
    seg = text[max(0, m.start() - 600): m.end() + 600] if m else text[:1200]
    return hashlib.sha1(re.sub(r"\s+", " ", seg).strip().lower().encode()).hexdigest()


SEEN_WINDOWS: dict[str, set] = {}


def agenda_matters(meeting: dict) -> list[dict]:
    kind, body, final = fetch(meeting["url"])
    real = resolve(final)
    if real != final:
        if LEGISTAR_HOST.search(urlparse(real).netloc):
            return []
        kind, body, final = fetch(real)
    if LEGISTAR_HOST.search(urlparse(final).netloc):
        return []
    base = {"intro_date": meeting["date"], "file": meeting["name"]}
    out = []

    def add(mid: str, title: str, url: str, text: str, atts: list):
        out.append({"matter_id": mid, "title": title[:300], "url": url, "text": text[:MAX_INLINE], "attachments": atts, **base})

    if kind == "html":
        for it in html_items(body, final):
            ctx_hit = SOLE_RE.search(it["context"])
            if NOISE_RE.search(it["label"]) and not SOLE_RE.search(it["label"]):
                continue
            if it["href"] and DOC_HREF.search(it["href"]) and not LEGISTAR_HOST.search(urlparse(it["href"]).netloc.replace("granicus.com", "")):
                if not (ctx_hit or EQUIP_RE.search(it["label"] + " " + it["context"][:400])):
                    continue
                atts, _ = doc_to_attachments(it["label"] or "item", it["href"])
                if atts:
                    add(hashlib.sha1(it["href"].encode()).hexdigest()[:12], it["label"] or meeting["name"], it["href"], it["context"], atts)
            elif ctx_hit and len(it["context"]) > 80:
                # a text-only item (MediaPlayer index): the agenda's own words are the record
                add(hashlib.sha1((meeting["url"] + it["label"]).encode()).hexdigest()[:12], it["label"], meeting["url"], it["context"], [])
    elif kind == "pdf":
        pages = pdf_pages(meeting["url"])
        linked_pages = set()
        if len(pages) <= PACKET_PAGES:
            for pi, uri in pdf_links(meeting["url"]):
                if not DOC_HREF.search(uri) or LEGISTAR_HOST.search(urlparse(uri).netloc.replace("granicus.com", "")):
                    continue
                label = unquote(Path(urlparse(uri).path).name).replace("_", " ").rsplit(".", 1)[0]
                if NOISE_RE.search(label) and not SOLE_RE.search(label):
                    continue
                if not EQUIP_RE.search(label) and not SOLE_RE.search(pages[pi] if pi < len(pages) else ""):
                    continue
                atts, _ = doc_to_attachments(label, uri)
                if atts:
                    linked_pages.add(pi)
                    add(hashlib.sha1(uri.encode()).hexdigest()[:12], label, uri, "", atts)
        key = hashlib.sha1(meeting["url"].encode()).hexdigest()[:10]
        for a, b, t in windows(pages):
            if len(pages) <= PACKET_PAGES and any(a <= p < b for p in linked_pages):
                continue
            first = next((ln.strip() for ln in "\n".join(pages[a:b]).splitlines() if SOLE_RE.search(ln)), "")
            if first_hit_key(t) in SEEN_WINDOWS.setdefault(meeting["site"], set()):
                continue
            SEEN_WINDOWS[meeting["site"]].add(first_hit_key(t))
            add(f"{key}-p{a + 1}", f"{meeting['name']} p.{a + 1}-{b}: {first[:160]}", f"{final}#page={a + 1}", t, [])
    return out


def ingest(site: dict) -> dict:
    ms, all_m, seen = [], [], set()
    for v in site["views"]:
        ms += meetings(site["host"], v)
    ms.sort(key=lambda m: m["date"], reverse=True)   # newest printing of a repeated report wins
    for mt in ms:
        mt["site"] = site["slug"]
        try:
            for m in agenda_matters(mt):
                if m["matter_id"] not in seen:
                    seen.add(m["matter_id"]); all_m.append(m)
        except Exception as e:  # noqa: BLE001 - one broken agenda never stops a site
            print(f"  {site['slug']} {mt['url']}: {e}", file=sys.stderr, flush=True)
    return {"platform": "granicus", "agency": site["agency"], "state": site["state"], "host": site["host"],
            "views": site["views"], "since": SINCE, "meetings_read": len(ms),
            "ingested": datetime.now().strftime("%Y-%m-%d"), "matters": all_m}


def main(argv):
    sites = [s for s in SITES if not argv or s["slug"] in argv]
    (ROOT / "data" / "matters").mkdir(exist_ok=True)

    def run(site):
        res = ingest(site)
        (ROOT / "data" / "matters" / f"granicus-{site['slug']}.json").write_text(json.dumps(res, indent=1))
        n_att = sum(len(m["attachments"]) for m in res["matters"])
        print(f"granicus-{site['slug']}: {res['meetings_read']} meetings, {len(res['matters'])} sole-source items, {n_att} attachments", flush=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(run, sites))


if __name__ == "__main__":
    main(sys.argv[1:])
