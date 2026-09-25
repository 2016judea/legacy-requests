"""Shared plumbing for the non-Legistar agenda ingesters (CivicClerk, PrimeGov).

Every response is cached under data/cache/<platform>/ and never re-downloaded; the
cache key is a STABLE key the caller chooses, not the URL, because CivicClerk hands
out Azure blob links whose signature changes on every request (a URL-keyed cache
would re-download the same PDF forever).
"""
import hashlib
import html
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
SINCE = "2024-01-01"
UA = {"User-Agent": "obsolete-parts/0.1 (public-records research; github.com/2016judea/obsolete-parts)"}
MAX_PDF_BYTES = 25_000_000      # a whole agenda packet is not an item attachment
MAX_ATTACHMENTS = 8             # per item; the justification is nearly always in the first few

# An item is worth downloading when its own text says one of these. Same vocabulary as
# extract.KEYWORD_RE plus the bid-waiver phrasings councils use instead of "sole source".
SOLE_RE = re.compile(
    r"\b(sole[- ]?source|single[- ]source|proprietary|obsolete|no longer (manufactured|made|supported|available|produced)"
    r"|discontinued|OEM|original equipment manufacturer|only (authorized|approved) (dealer|distributor|vendor|provider|service)"
    r"|exclusive (distributor|dealer|provider)|waiv\w+ (of )?(the )?(formal )?(competitive )?(bid|bidding|solicitation)"
    r"|exempt(ion)? from (the )?competitive (bid|bidding)|252\.022)\b", re.I)
# ...or when it buys or repairs a named class of hardware (extract.qualifies() then checks
# the PDFs for sole-source language before anything is sent to the model).
EQUIP_RE = re.compile(
    r"\b(pumps?|valves?|motors?|generators?|transformers?|switchgear|SCADA|membranes?|centrifuges?|blowers?|compressors?"
    r"|VFDs?|variable frequency|clarifiers?|ultraviolet|UV system|chlorinat\w+|lift station|turbines?|actuators?|PLCs?"
    r"|boilers?|chillers?|fire (truck|apparatus|engine)|aerial|ladder truck|breakers?|relays?|substation|meters?|analy[sz]ers?"
    r"|radios?|locomotive|rail ?cars?|buses|bus parts|runway|jet bridge|baggage|crane|dredge|screw press|belt press|digesters?)\b", re.I)
BUY_RE = re.compile(r"\b(purchas\w+|procure\w*|acqui\w+|replace\w*|repair\w*|rebuild\w*|parts|overhaul\w*|upgrade\w*|maintenance)\b", re.I)


SELL_RE = re.compile(r"\b(surplus|auction\w*|disposal of|dispose of)\b", re.I)


def wanted(text: str, title: str = "") -> str | None:
    """'sole' if the item's own text uses sole-source language, 'equip' if it buys hardware, else None.
    A surplus/auction item says "obsolete" about what the agency is SELLING; it is not a purchase."""
    if SELL_RE.search(title or text[:300]):
        return None
    if SOLE_RE.search(text):
        return "sole"
    if EQUIP_RE.search(text) and BUY_RE.search(text):
        return "equip"
    return None


def strip_html(s: str | None) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def _get(url: str, timeout=60) -> requests.Response | None:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (200, 400, 403, 404, 410):
            return r
        time.sleep(2 * (attempt + 1))
    return None


def cached_json(platform: str, key: str, url: str):
    path = CACHE / platform / "json" / f"{hashlib.sha1(key.encode()).hexdigest()}.json"
    if path.exists():
        b = path.read_bytes()
    else:
        r = _get(url)
        if r is None:
            return None                      # transient failure: not cached, retried next run
        b = r.content if r.status_code == 200 else b""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b)
        path.with_suffix(".url").write_text(url)
    try:
        return json.loads(b) if b else None
    except json.JSONDecodeError:
        return None


def cached_text(platform: str, key: str, url: str) -> str:
    path = CACHE / platform / "html" / f"{hashlib.sha1(key.encode()).hexdigest()}.html"
    if path.exists():
        return path.read_text(errors="replace")
    r = _get(url)
    if r is None:
        return ""
    t = r.text if r.status_code == 200 else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(t)
    path.with_suffix(".url").write_text(url)
    return t


def cached_pdf(platform: str, key: str, url: str) -> str | None:
    """Download once; return the repo-relative path, or None if it is not a usable PDF."""
    path = CACHE / platform / "pdf" / f"{hashlib.sha1(key.encode()).hexdigest()}.pdf"
    if not path.exists():
        r = _get(url, timeout=120)
        if r is None:
            return None
        ok = r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) <= MAX_PDF_BYTES
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content if ok else b"")
        path.with_suffix(".key").write_text(key)
    return str(path.relative_to(ROOT)) if path.stat().st_size else None


# What goes to the model is narrower than what gets downloaded. Measured 2026-09-24 on the
# first 20 tenants: sending every item that extract.qualifies() passes cost an estimated $59,
# over half of it Oklahoma City "waiving competitive bidding" emergencies (mostly construction)
# and equipment items whose PDFs say "OEM" in boilerplate. So an item is sent only if its OWN
# text names a sole/single-source or proprietary purchase, or it buys named hardware and one of
# its PDFs says "sole source" / "single source" in so many words.
STRICT_RE = re.compile(
    r"\b(sole[- ]?source|single[- ]source|proprietary|original equipment manufacturer|OEM|obsolete"
    r"|no longer (manufactured|made|supported|available|produced)|discontinued|only (authorized|approved) (dealer|distributor|vendor))\b", re.I)
PDF_SOLE_RE = re.compile(r"\b(sole|single)[- ]?source\b", re.I)
SOFT_RE = re.compile(r"\b(software|licen[cs]e|subscription|SaaS|cloud|professional services|consult\w+|membership|training"
                     r"|insurance|advertis\w+|marketing|legal services|audit\w*)\b", re.I)


def send_to_model(m: dict) -> bool:
    """Second cut, same day: the rule above still sent 1,253 items (~$103). 925 of them only
    mentioned sole-source language somewhere in a long item body ("proprietary information",
    grant boilerplate). So: hardware-titled items with the language anywhere; any other item
    only when its TITLE says it is a sole/single-source or proprietary purchase."""
    title = m.get("title") or ""
    if SOFT_RE.search(title) and not EQUIP_RE.search(title):
        return False                        # software/services renewals: the page's minor half already
    if re.search(r"proprietary information", title, re.I):
        return False
    if EQUIP_RE.search(title) and STRICT_RE.search(title + "\n" + (m.get("text") or "")):
        return True
    if STRICT_RE.search(title):
        return True
    if m.get("keyword") == "equip" and EQUIP_RE.search(title):
        from extract import pdf_text        # imported late: extract pulls in anthropic + pdfplumber
        return any(PDF_SOLE_RE.search(pdf_text(ROOT / a["path"])[0]) for a in m["attachments"] if a.get("path"))
    return False


MAX_ITEM_CHARS = 10_000        # item body
MAX_ATT_CHARS = 15_000         # per attachment; the justification memo is the first pages
MAX_SEND_ATTACHMENTS = 3


def slim(m: dict) -> dict:
    """Cap what one item costs. A text-layer PDF goes in as inline text (the extract contract
    allows it), cut to MAX_ATT_CHARS; a scanned PDF stays a file only if it is short. Measured
    2026-09-24: uncapped, the mean item was ~18k input tokens because a 60-page contract rode along."""
    from extract import pdf_text
    atts = []
    for a in m["attachments"]:
        if len(atts) >= MAX_SEND_ATTACHMENTS:
            break
        text, pages = pdf_text(ROOT / a["path"])
        if pages and len(text.strip()) / pages >= 200:
            atts.append({"name": a["name"], "url": a["url"], "text": text[:MAX_ATT_CHARS]})
        elif 0 < pages <= 4:
            atts.append(a)
    return {**m, "text": (m.get("text") or "")[:MAX_ITEM_CHARS], "attachments": atts}


# A spend knob, not a judgement: with 70 agencies passing send_to_model the bill was ~$45 against
# a $25 budget (pilot, 2026-09-24: $0.0485 per item, sonnet-5), and one city (Lansing, 133
# "Sole Source Purchase;" items) would have taken a fifth of it. Each agency sends its hardware-
# titled items first, newest first, up to this many. Raise it to spend more; the cache keeps the rest.
MAX_SEND_PER_AGENCY = 15
EXTRACT_MODEL = "claude-sonnet-5"


def write_matters(slug: str, platform: str, agency: str, state: str, matters: list[dict]) -> list[dict]:
    """Write only the items worth a model call (send_to_model), slimmed and capped; the rest stay
    in the cache. An item whose model response is already cached always stays (it costs nothing)."""
    matters = [m for m in matters if send_to_model(m)]
    done = CACHE / "extract" / EXTRACT_MODEL
    cached = [m for m in matters if (done / f"{slug}-{m['matter_id']}.json").exists()]
    rest = sorted((m for m in matters if m not in cached),
                  key=lambda m: m.get("intro_date") or "", reverse=True)                # newest first...
    rest = sorted(rest, key=lambda m: not EQUIP_RE.search(m.get("title") or ""))         # ...hardware before that (stable)
    matters = [slim(m) for m in cached + rest[: max(0, MAX_SEND_PER_AGENCY - len(cached))]]
    out = ROOT / "data" / "matters" / f"{slug}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"platform": platform, "agency": agency, "state": state, "since": SINCE,
                               "matters": matters}, indent=1))
    return matters
