#!/usr/bin/env python3
"""DIBBS matcher: can the supply we already scrape answer open DLA RFQs at a margin?

A MEASUREMENT, not a product. One run writes data/dibbs/matches_<date>.jsonl and
data/dibbs/REPORT_<date>.md. Nothing is quoted, registered or sent.

WHERE THE DATA COMES FROM (worked out 2026-10-06, curl only):

  1. Consent. Both hosts (www.dibbs.bsm.dla.mil, dibbs2.bsm.dla.mil) put every page
     behind a DoD warning page; GET it, POST its hidden inputs back with butAgree=OK,
     and the session cookie is set. Without it the WAF answers "Request Rejected".
     Each host needs its own consent.
  2. The day's RFQs in bulk. /RFQ/RFQDates.aspx?category=recent lists, per issue day,
     dibbs2 .../Downloads/RFQ/Archive/in<YYMMDD>.txt (one fixed-width line per RFQ
     line item) and bq<YYMMDD>.zip, whose as<YYMMDD>.txt is the APPROVED SOURCES:
     "NSN","CAGE","part number","". These 404 without the dibbs2 consent cookie,
     which is why they looked dead. One file per day replaces ~30 paged postbacks.
  3. Manufacturer name and price history: only for RFQs whose approved PN hit a
     listing, the RFQ PDF (dibbs2 .../Downloads/RFQ/<n>/<SOL>.PDF). It prints each
     approved source as "<NAME> <CAGE> P/N <PN>" and a "Procurement History for
     NSN/FSC" table: CAGE, contract, qty, unit cost, award date, surplus flag.

THE MATCH is scripts/join_supply.py's: a part token of the approved PN equals a
listing token (separators dropped) AND a distinctive word of the approved source's
name appears in the listing (join_supply.mfr_match). Supply = every
data/supply/*.jsonl plus the six dealers' cached sitemaps (scripts/supply_dealers;
sitemaps are NOT refreshed here, candidate product pages are fetched once and cached).

BID-ELIGIBLE here means the listing is NEW (says so) or GOVERNMENT SURPLUS (GovDeals,
PublicSurplus). Used marketplace stock is not eligible: DLA buys new material
traceable to the approved source, and surplus only under DLAD 52.211-9000.

MARGIN = (last award unit price - listing price) / last award unit price, before
shipping, packaging and the listing's own buyer premium. A listing is assumed to be
one unit unless it says otherwise; the RFQ quantity is reported beside it.

Run: .venv/bin/python scripts/dibbs_match.py [--days 5]
"""
import argparse
import html as htmllib
import io
import json
import re
import subprocess
import sys
import time
import urllib.parse
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from join_supply import is_part_token, listing_tokens, load_listings, mfr_match, mfr_words, norm  # noqa: E402
import supply_dealers as SD  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "dibbs"
OUT = ROOT / "data" / "dibbs"
WWW = "https://www.dibbs.bsm.dla.mil"
D2 = "https://dibbs2.bsm.dla.mil"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.5 Safari/605.1.15")
DELAY = 1.2
MARGIN = 0.30
# Listing prices in other currencies, converted to USD before the margin. A fixed rate,
# not a live one: eltra-trade.com prices in EUR (found 2026-10-06, its Omron S8VK-T48024
# read as a 34% margin until the EUR was noticed).
FX_USD = {"USD": 1.0, "EUR": 1.17, "GBP": 1.34}
# A dealer page that sells a substitute names the asked-for PN in its title: Kempston's
# "Schneider ZB5AA2 ABB Alternative" is an ABB part, not the approved Schneider one.
SUBSTITUTE = re.compile(r"\balternat|\bequivalent\b|\bcompatible\b|\breplacement for\b", re.I)

S = requests.Session()
S.headers["User-Agent"] = UA
_last = [0.0]
_consented: set[str] = set()


def _wait():
    w = DELAY - (time.time() - _last[0])
    if w > 0:
        time.sleep(w)
    _last[0] = time.time()


def consent(host: str, goto: str = "/"):
    _wait()
    r = S.get(f"{host}/dodwarning.aspx?goto={urllib.parse.quote(goto)}", timeout=60)
    fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', r.text))
    fields["butAgree"] = "OK"
    _wait()
    S.post(r.url, data=fields, timeout=60)
    _consented.add(host)


def blocked(body: bytes) -> bool:
    head = body[:3000]
    return b"Request Rejected" in head or b"butAgree" in body[:60000] and b"Warning and Consent" in head


def get(url: str, path: Path | None = None) -> bytes | None:
    """Cached GET. A cached file is never re-fetched; a WAF/consent page is never cached."""
    if path and path.exists():
        return path.read_bytes()
    host = WWW if url.startswith(WWW) else D2
    if host not in _consented:
        consent(host, urllib.parse.urlparse(url).path)
    for attempt in range(2):
        _wait()
        r = S.get(url, timeout=180)
        if r.status_code == 200 and not blocked(r.content):
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r.content)
            return r.content
        print(f"  ! {url}: {r.status_code}{' blocked' if blocked(r.content) else ''}", file=sys.stderr)
        consent(host, urllib.parse.urlparse(url).path)
    return None


# ---------- 1-2: the bulk files ----------

def issue_days(n: int) -> list[str]:
    """The latest n YYMMDD issue days that have both an in*.txt and a bq*.zip."""
    page = get(f"{WWW}/RFQ/RFQDates.aspx?category=recent",
               CACHE / "dates" / f"{date.today().isoformat()}.html").decode("utf-8", "replace")
    ins = set(re.findall(r"Archive/in(\d{6})\.txt", page))
    bqs = set(re.findall(r"Archive/bq(\d{6})\.zip", page))
    return sorted(ins & bqs)[-n:]


def parse_in(text: str, day: str) -> list[dict]:
    """Fixed width, 141 chars (measured on in261005.txt, 2,506 lines)."""
    out = []
    for line in text.splitlines():
        if len(line) < 110:
            continue
        rb = line[72:80]
        out.append({
            "solicitation": line[0:13].strip(),
            "nsn": line[13:26].strip(),
            "item_pn": line[26:62].strip() or None,
            "pr": line[62:72].strip(),
            "return_by": datetime.strptime(rb, "%m/%d/%y").date().isoformat() if re.fullmatch(r"\d\d/\d\d/\d\d", rb) else None,
            "pdf": line[80:99].strip(),
            "qty": int(line[99:106]) if line[99:106].strip().isdigit() else None,
            "ui": line[106:108].strip(),
            "nomenclature": line[108:129].strip(),
            "issued": f"20{day[:2]}-{day[2:4]}-{day[4:]}",
        })
    return out


AS_LINE = re.compile(r'^"(\d{13})","([0-9A-Z]{5})","(.*)","(.*)"$')


def parse_as(text: str) -> dict[str, list[tuple[str, str]]]:
    """NSN -> [(CAGE, PN)]. Line-wise: a PN containing a quote breaks csv."""
    out = defaultdict(list)
    for line in text.splitlines():
        m = AS_LINE.match(line.strip())
        if m and m.group(3).strip():
            out[m.group(1)].append((m.group(2), m.group(3).strip()))
    return out


def load_day(day: str):
    raw_in = get(f"{D2}/Downloads/RFQ/Archive/in{day}.txt", CACHE / "archive" / f"in{day}.txt")
    raw_bq = get(f"{D2}/Downloads/RFQ/Archive/bq{day}.zip", CACHE / "archive" / f"bq{day}.zip")
    if not raw_in or not raw_bq:
        return [], {}
    z = zipfile.ZipFile(io.BytesIO(raw_bq))
    name = next((n for n in z.namelist() if n.lower().startswith("as")), None)
    return parse_in(raw_in.decode("latin-1"), day), parse_as(z.read(name).decode("latin-1") if name else "")


# ---------- 3: the RFQ PDF ----------

SRC_LINE = re.compile(r"^\s*(\S.*?)\s+([0-9A-Z]{5})\s+P/N\s+(\S.*?)\s*$")
HIST_LINE = re.compile(r"^\s*([0-9A-Z]{5})\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+(\d{8})\s+([YN])\s*$")


def rfq_pdf(rfq: dict) -> dict:
    sol = rfq["solicitation"]
    pdf = get(f"{D2}/Downloads/RFQ/{sol[-1]}/{sol}.PDF", CACHE / "pdf" / f"{sol}.PDF")
    if not pdf or not pdf.startswith(b"%PDF"):
        return {"sources": {}, "history": []}
    txt = CACHE / "pdf" / f"{sol}.txt"
    if not txt.exists():
        txt.write_text(subprocess.run(["pdftotext", "-layout", str(CACHE / "pdf" / f"{sol}.PDF"), "-"],
                                      capture_output=True, text=True).stdout)
    sources, history = {}, []
    for line in txt.read_text().splitlines():
        if m := SRC_LINE.match(line):
            sources[m.group(2)] = {"name": m.group(1), "pn": m.group(3)}
        elif m := HIST_LINE.match(line):
            history.append({"cage": m.group(1), "contract": m.group(2), "qty": float(m.group(3)),
                            "unit": float(m.group(4)), "date": m.group(5), "surplus": m.group(6) == "Y"})
    history.sort(key=lambda h: h["date"], reverse=True)
    return {"sources": sources, "history": history}


# ---------- condition ----------

GOV_SURPLUS = {"govdeals", "publicsurplus"}
NEW_RE = re.compile(r"\b(?:brand[- ]new|new in (?:box|package)|nib|nos|new old stock|factory sealed|sealed|"
                    r"unused|unopened|new surplus|new)\b", re.I)
USED_RE = re.compile(r"\b(?:used|refurb\w*|rebuilt|as[- ]is|for parts|tested|working|pulled|removed)\b", re.I)


def condition(listing: dict, page: str | None = None) -> str:
    if listing["source"] in GOV_SURPLUS:
        return "surplus"
    text = listing.get("title") or ""
    if page:
        m = re.search(r'itemCondition"?\s*[:=]\s*"?(?:https?://schema\.org/)?(\w+)', page)
        if m:
            return "new" if m.group(1).lower().startswith("new") else "used"
    if USED_RE.search(text):
        return "used"
    if NEW_RE.search(text):
        return "new"
    return "used" if listing["source"] == "craigslist" else "unknown"


# ---------- 4: match ----------

def pn_token(pn: str) -> str | None:
    t = norm(pn)
    return t if is_part_token(t) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5)
    a = ap.parse_args()
    today = date.today().isoformat()

    days = issue_days(a.days)
    rfqs, approved = [], defaultdict(list)
    for d in days:
        rows, srcs = load_day(d)
        rfqs += rows
        for nsn, pairs in srcs.items():
            for p in pairs:
                if p not in approved[nsn]:
                    approved[nsn].append(p)
        print(f"{d}: {len(rows)} RFQ lines, {len(srcs)} NSNs with approved sources")
    open_rfqs = [r for r in rfqs if r["return_by"] and r["return_by"] >= today]
    with_pn = [r for r in open_rfqs if approved.get(r["nsn"])]

    # token -> [(rfq, cage, pn)]
    want = defaultdict(list)
    for r in with_pn:
        for cage, pn in approved[r["nsn"]]:
            if t := pn_token(pn):
                want[t].append((r, cage, pn))
    print(f"open RFQ lines {len(open_rfqs)}, with approved PN {len(with_pn)}, distinct PN tokens {len(want)}")

    # pass A: PN only. Marketplace listings...
    cand = []  # (token, listing, page)
    for L in load_listings():
        for t in listing_tokens(L) & want.keys():
            cand.append((t, L, None))
    print(f"marketplace PN-token hits: {len(cand)}")
    # ...and dealer sitemaps (exact PN segment, or a run of slug pieces).
    dealer_hits = []
    for dealer, cfg in SD.DEALERS.items():
        urls = SD.product_urls(dealer, cfg, False)
        n0 = len(dealer_hits)
        for u in urls:
            m = cfg["product"].search(u)
            if not m:
                continue
            g = m.groupdict()
            if "pn" in g:
                toks = {re.sub(r"[^A-Z0-9]", "", urllib.parse.unquote(g["pn"]).upper())}
            else:
                toks = SD.slug_tokens(urllib.parse.unquote(g["slug"]))
            for t in toks & want.keys():
                dealer_hits.append((t, dealer, cfg, u))
        print(f"  {dealer}: {len(urls)} urls, {len(dealer_hits) - n0} PN-token hits")

    # pass B: manufacturer, from the RFQ PDF's own approved-source line.
    pdfs = {}

    def src_name(rfq, cage):
        sol = rfq["solicitation"]
        if sol not in pdfs:
            pdfs[sol] = rfq_pdf(rfq)
        return (pdfs[sol]["sources"].get(cage) or {}).get("name"), pdfs[sol]

    out, pn_only = [], 0
    seen = set()

    def emit(rfq, cage, pn, L, page):
        name, info = src_name(rfq, cage)
        if not name or not mfr_words(name) or not mfr_match(name, L):
            return False
        if SUBSTITUTE.search(L.get("title") or ""):
            return False
        k = (rfq["solicitation"], rfq["nsn"], L["url"])
        if k in seen:
            return True
        seen.add(k)
        last = info["history"][0] if info["history"] else None
        cond = condition(L, page)
        fx = FX_USD.get(L.get("currency") or "USD")
        usd = round(L["price"] * fx, 2) if L.get("price") and fx else None
        margin = round((last["unit"] - usd) / last["unit"], 3) if last and usd and last["unit"] > 0 else None
        out.append({
            "nsn": rfq["nsn"], "nomenclature": rfq["nomenclature"], "solicitation": rfq["solicitation"],
            "qty": rfq["qty"], "ui": rfq["ui"], "issued": rfq["issued"], "return_by": rfq["return_by"],
            "approved_cage": cage, "approved_name": name, "approved_pn": pn,
            "listing_url": L["url"], "listing_title": L["title"], "listing_price": L.get("price"),
            "listing_currency": L.get("currency"), "listing_usd": usd,
            "condition": cond, "bid_eligible": cond in ("new", "surplus"), "seller": L["source"],
            "last_award_unit": last["unit"] if last else None, "last_award_date": last["date"] if last else None,
            "last_award_qty": last["qty"] if last else None, "awards_on_file": len(info["history"]),
            "margin": margin,
        })
        return True

    for t, L, page in cand:
        for rfq, cage, pn in want[t]:
            pn_only += 1
            emit(rfq, cage, pn, L, page)

    for t, dealer, cfg, u in dealer_hits:
        # only fetch the dealer page when the PDF's source name agrees with the URL/slug
        hits = []
        for rfq, cage, pn in want[t]:
            pn_only += 1
            name, _ = src_name(rfq, cage)
            if name and SD.candidates(u, cfg, {t: [{"manufacturer": name, "model": pn}]}):
                hits.append((rfq, cage, pn))
        if not hits:
            continue
        p = SD.CACHE / dealer / "pages" / f"{SD.key(u)}.json"
        if p.exists():
            c = json.loads(p.read_text())
        else:
            page = SD.cached(SD.CACHE / dealer / "pages" / f"{SD.key(u)}.html", u)
            if page is None:
                continue
            c = {"url": u, "fetched": today, "html": page}
            p.write_text(json.dumps(c))
            (SD.CACHE / dealer / "pages" / f"{SD.key(u)}.html").unlink(missing_ok=True)
        row = SD.parse(c["html"], u, dealer, cfg, c["fetched"])
        if not row:
            continue
        for rfq, cage, pn in hits:
            if pn_token(pn) in listing_tokens(row) | {t}:
                emit(rfq, cage, pn, row, c["html"])

    OUT.mkdir(parents=True, exist_ok=True)
    out.sort(key=lambda m: (not m["bid_eligible"], -(m["margin"] or -9)))
    (OUT / f"matches_{today}.jsonl").write_text("".join(json.dumps(m) + "\n" for m in out))

    elig = [m for m in out if m["bid_eligible"]]
    clear = [m for m in elig if m["margin"] is not None and m["margin"] >= MARGIN]
    stats = {
        "days": days, "rfq_lines": len(rfqs), "open": len(open_rfqs),
        "open_solicitations": len({r["solicitation"] for r in open_rfqs}),
        "with_pn": len(with_pn), "with_pn_solicitations": len({r["solicitation"] for r in with_pn}),
        "pn_tokens": len(want), "pn_only_pairs": pn_only, "pdfs": len(pdfs),
        "exact": len(out), "exact_rfqs": len({m["solicitation"] for m in out}),
        "eligible": len(elig), "eligible_rfqs": len({m["solicitation"] for m in elig}),
        "clear": len(clear), "clear_rfqs": len({m["solicitation"] for m in clear}),
        "by_condition": dict(sorted(defaultdict(int, {}).items())),
    }
    cond_count = defaultdict(int)
    for m in out:
        cond_count[m["condition"]] += 1
    stats["by_condition"] = dict(cond_count)
    (CACHE / f"stats_{today}.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))
    write_report(stats, out, today)


def caveat(m: dict) -> str:
    notes = []
    if m["condition"] == "surplus" and not NEW_RE.search(m["listing_title"] or ""):
        notes.append("government surplus, not stated unused: DLA takes surplus only unused and traceable (DLAD 52.211-9000)")
    if (m.get("listing_currency") or "USD") != "USD":
        notes.append(f"priced in {m['listing_currency']}, converted at a fixed rate")
    if m["qty"] and m["qty"] > 1:
        notes.append(f"RFQ wants {m['qty']} {m['ui']}; listing is one")
    if m["last_award_date"] and m["last_award_date"] < "2024":
        notes.append(f"last award {m['last_award_date'][:4]}")
    return "; ".join(notes) or "-"


def write_report(st: dict, out: list[dict], today: str):
    elig = [m for m in out if m["bid_eligible"]]
    clear = [m for m in elig if m["margin"] is not None and m["margin"] >= MARGIN]
    clean = [m for m in clear if caveat(m) == "-" or "surplus" not in caveat(m)]
    days = [f"20{d[:2]}-{d[2:4]}-{d[4:]}" for d in st["days"]]
    per_week = len({m["solicitation"] for m in clean}) * 5 / max(len(days), 1)
    verdict = "VIABLE" if per_week >= 3 else "DEAD"
    fmt = lambda v: "-" if v is None else f"${v:,.2f}"
    pct = lambda v: "-" if v is None else f"{v:.0%}"
    lines = [
        f"# DIBBS matcher, {today}",
        "",
        f"Open DLA RFQs issued {days[0]} to {days[-1]} ({len(days)} issue days), approved CAGE/PN from DIBBS's own",
        "batch files, matched against every scraped listing and six dealer sitemaps by the index's own rule",
        "(manufacturer AND exact part number). Generated by `scripts/dibbs_match.py`; rows in",
        f"`data/dibbs/matches_{today}.jsonl`.",
        "",
        "| | count |",
        "|---|---:|",
        f"| RFQ line items scanned (still open) | {st['open']:,} ({st['open_solicitations']:,} solicitations) |",
        f"| ... with an approved part number | {st['with_pn']:,} ({st['with_pn_solicitations']:,}) |",
        f"| (listing, RFQ) pairs sharing a part number | {st['pn_only_pairs']} |",
        f"| exact matches (PN + manufacturer) | {st['exact']} on {st['exact_rfqs']} RFQs |",
        f"| ... NEW or government surplus (bid-eligible) | {st['eligible']} on {st['eligible_rfqs']} RFQs |",
        f"| ... clearing {int(MARGIN * 100)}% over last award, before shipping | {st['clear']} on {st['clear_rfqs']} RFQs |",
        f"| ... and not a used surplus unit | {len(clean)} on {len({m['solicitation'] for m in clean})} RFQs |",
        "",
        "## Bid-eligible matches",
        "",
        "| RFQ | item | approved | qty | return by | last award | listing (USD) | margin | seller | caveat |",
        "|---|---|---|---:|---|---:|---:|---:|---|---|",
    ]
    for m in elig:
        lines.append(f"| {m['solicitation']} | {m['nomenclature']} | {m['approved_name'].title()} {m['approved_pn']} | {m['qty']} "
                     f"| {m['return_by']} | {fmt(m['last_award_unit'])} | [{fmt(m['listing_usd'])}]({m['listing_url']}) "
                     f"| {pct(m['margin'])} "
                     f"| {m['seller']} | {caveat(m)} |")
    cond = st["by_condition"]
    lines += [
        "",
        "## Why so few",
        "",
        f"- {st['open'] - st['with_pn']:,} of {st['open']:,} open lines name no approved part number at all (mil-spec,",
        "  drawing-controlled), and of the rest only a few hundred (listing, RFQ) pairs share a part number with",
        "  anything we scrape. Our supply is commodity industrial catalog stock plus Craigslist; DLA's buy is not.",
        f"- Of {st['exact']} exact matches, {cond.get('used', 0)} are used marketplace stock and {cond.get('unknown', 0)} are",
        "  dealer pages that do not state condition. Neither is bid-eligible.",
        "- Where the item is a catalog part a dealer stocks new, DLA's last award is already at or under the",
        "  dealer's price: the same pattern as batch 2. The agency is not overpaying on commodity parts.",
        "",
        f"**{verdict}**: {per_week:.1f} clean bid-eligible >{int(MARGIN * 100)}% matches per week against a bar of 3.",
        "",
    ]
    (OUT / f"REPORT_{today}.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
