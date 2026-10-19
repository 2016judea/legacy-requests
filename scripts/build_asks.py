#!/usr/bin/env python3
"""Open asks: every government RFQ for a part that is still taking quotes. The paid list.

Model: DATA_MODEL.md "Open asks". Sources, all cached, nothing fetched here:
  - DLA DIBBS bulk files (in<YYMMDD>.txt + bq<YYMMDD>.zip), via scripts/dibbs_match.py's loaders
  - each solicitation's RFQ PDF text (scripts/fetch_open_rfqs.py): buyer, office, approved
    source names, procurement history (last price paid)
  - SAM.gov sole-source notices still open (data/open_notices.jsonl, `make open`)
  - our supply listings (data/supply/*.jsonl) + dealer sitemaps, matched by exact PN + maker word

Writes:
  private/bundle/rows.json.gz     every open ask, full (served only by /api/data and /api/check)
  site/asks/meta.json             counts and the maker list (no rows)
  site/asks/index.html            the free page: counts, a pre-loaded example line, search, the offer
  site/for/<token>/index.html     one page per round-1 recipient (outreach/round1/recipients.json)

FULL DATA NEVER SHIPS STATICALLY: site/ gets counts and redacted samples only.
Run: .venv/bin/python scripts/build_asks.py
"""
import gzip
import json
import re
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dibbs_match as D  # noqa: E402
from join_supply import load_listings, listing_tokens, mfr_match, mfr_words, norm, is_part_token  # noqa: E402
import supply_dealers as SD  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PRIV = ROOT / "private" / "bundle"
RECIP = ROOT / "outreach" / "round1" / "recipients.json"
PRICE_USD = 85  # README "## Price" carries the arithmetic; a hypothesis under test, not a fact
HOST = "https://legacy-requests.vercel.app"

SUFFIX = re.compile(r"\b(?:INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LLC|L\.L\.C|LTD|LIMITED|LP|THE|DIV|DIVISION|DBA|USA|US)\b\.?", re.I)


def maker_key(name: str) -> str:
    s = SUFFIX.sub(" ", (name or "").upper().replace(",", " ").replace(".", " "))
    return re.sub(r"\s+", " ", s).strip()


BUYER = re.compile(r"Name:\s*(.*?)\s+Buyer Code:\s*(\S+)\s+Tel:\s*([\d\-() ]+?)\s+Fax:")
EMAIL = re.compile(r"Email:\s*(\S+@\S+)")
DUE = re.compile(r"BEFORE CLOSE OF BUSINESS \(Date\).*?\n\s*(\d{4} [A-Z]{3} \d{1,2})", re.S)


def phone(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    if not d.strip("0"):  # "000-000-0000" and the nine-zero "000000000" the RFQ prints for no phone
        return ""
    return f"{d[:3]}-{d[3:6]}-{d[6:10]}" if len(d) == 10 else (s or "").strip()


def qty_num(v):
    """SAM.gov quantity is free text ("1.00 EA", "36 National Stock Numbers (NSNs)"): the leading number, or None."""
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r"\s*(\d[\d,]*)", str(v or ""))
    return int(m.group(1).replace(",", "")) if m else None


def read_pdf(sol: str) -> dict | None:
    f = D.CACHE / "pdf" / f"{sol}.txt"
    if not f.exists():
        return None
    t = f.read_text(errors="replace")
    out = {"sources": {}, "history": [], "buyer": None, "email": None, "tel": None, "office": None}
    if m := BUYER.search(t):
        out["buyer"], out["tel"] = m.group(1).strip(), phone(m.group(3)) or None
    if m := EMAIL.search(t):
        out["email"] = m.group(1).strip().rstrip(".,;")
    lines = t.splitlines()
    for i, line in enumerate(lines):
        if "5. ISSUED BY" in line:
            office = [l[:110].strip() for l in lines[i + 1:i + 4] if l[:110].strip() and not l.strip().startswith("Name:")]
            out["office"] = " · ".join(x for x in office[:2] if not re.match(r"^(PO BOX|\d)", x)) or None
            break
    for line in lines:
        if m := D.SRC_LINE.match(line):
            out["sources"][m.group(2)] = {"name": m.group(1), "pn": m.group(3)}
        elif m := D.HIST_LINE.match(line):
            out["history"].append({"cage": m.group(1), "qty": float(m.group(3)), "unit": float(m.group(4)),
                                   "date": f"{m.group(5)[:4]}-{m.group(5)[4:6]}-{m.group(5)[6:]}", "surplus": m.group(6) == "Y"})
    out["history"].sort(key=lambda h: h["date"], reverse=True)
    return out


def dibbs_rows() -> list[dict]:
    today = date.today().isoformat()
    latest, approved = {}, defaultdict(list)
    # One RFQ line is one purchase request (solicitation + NSN + PR). A re-issue prints the same
    # line again in a later daily file with a new return-by date, so the latest issue day wins:
    # summing the files counted 4,793 of 52,616 lines twice (measured 2026-10-18).
    for d in D.issue_days(40):  # ascending, so a later day overwrites
        r, srcs = D.load_day(d)
        for x in r:
            latest[(x["solicitation"], x["nsn"], x["pr"])] = x
        for nsn, pairs in srcs.items():
            approved[nsn] += [p for p in pairs if p not in approved[nsn]]
    rows = [x for x in latest.values() if x["return_by"] and x["return_by"] >= today]
    out = []
    for r in rows:
        sol = r["solicitation"]
        pdf = read_pdf(sol) or {}
        appr = []
        for cage, pn in approved.get(r["nsn"], []):
            name = ((pdf.get("sources") or {}).get(cage) or {}).get("name")
            appr.append({"cage": cage, "pn": pn, "maker": name})
        hist = pdf.get("history") or []
        last = hist[0] if hist else None
        nsn = r["nsn"]
        out.append({
            "id": f"{sol}:{nsn}", "source": "DLA DIBBS", "solicitation": sol, "nsn": nsn,
            "part": r["nomenclature"].title() if r["nomenclature"] else None,
            "approved": appr, "qty": r["qty"], "unit": r["ui"], "issued": r["issued"], "due": r["return_by"],
            "agency": "Defense Logistics Agency", "office": pdf.get("office"),
            "buyer_name": pdf.get("buyer"), "buyer_email": pdf.get("email"), "buyer_phone": pdf.get("tel"),
            "last_paid": last["unit"] if last else None, "last_paid_date": last["date"] if last else None,
            "last_qty": last["qty"] if last else None, "awards_on_file": len(hist),
            "took_surplus": any(h["surplus"] for h in hist) if hist else None,
            "rfq_url": f"{D.D2}/Downloads/RFQ/{sol[-1]}/{sol}.PDF",
            "pdf_read": bool(pdf),
        })
    return out


def sam_rows() -> list[dict]:
    f = ROOT / "data" / "open_notices.jsonl"
    today = date.today().isoformat()
    out = []
    for l in (f.read_text().splitlines() if f.exists() else []):
        if not l.strip():
            continue
        n = json.loads(l)
        if n["deadline_date"] < today:
            continue
        for i, p in enumerate(n["parts"]):
            out.append({
                "id": f"{n['notice_id']}:{i}", "source": "SAM.gov", "solicitation": n.get("solicitation") or n["notice_id"],
                "nsn": None, "part": p.get("part"),
                "approved": [{"cage": None, "pn": pn, "maker": p.get("manufacturer")} for pn in (p.get("part_numbers") or [None])],
                "qty": qty_num(p.get("quantity")), "unit": None, "issued": n["posted"], "due": n["deadline_date"],
                "agency": n["agency"], "office": n.get("office"),
                "buyer_name": None, "buyer_email": None, "buyer_phone": None,  # on the notice; the file never carries it
                "last_paid": None, "last_paid_date": None, "last_qty": None, "awards_on_file": 0, "took_surplus": None,
                "rfq_url": n["sam_url"], "pdf_read": True,
            })
    return out


def attach_supply(rows: list[dict]) -> int:
    """for_sale: a listing whose PN token equals an approved PN AND names the approved maker."""
    want = defaultdict(list)
    for r in rows:
        for a in r["approved"]:
            t = norm(a["pn"] or "")
            if a["maker"] and is_part_token(t):
                want[t].append((r, a))
    hits = 0
    for L in load_listings():
        for t in listing_tokens(L) & want.keys():
            for r, a in want[t]:
                if mfr_words(a["maker"]) and mfr_match(a["maker"], L):
                    r.setdefault("for_sale", [])
                    if not any(x["url"] == L["url"] for x in r["for_sale"]):
                        r["for_sale"].append({"seller": L["source"], "url": L["url"], "title": L.get("title"),
                                              "price": L.get("price"), "currency": L.get("currency") or "USD"})
                        hits += 1
    for dealer, cfg in SD.DEALERS.items():
        try:
            urls = SD.product_urls(dealer, cfg, False)
        except Exception as e:  # a dealer's sitemap cache missing is not fatal
            print(f"  {dealer}: {e}", file=sys.stderr)
            continue
        for u in urls:
            m = cfg["product"].search(u)
            if not m:
                continue
            g = m.groupdict()
            toks = ({re.sub(r"[^A-Z0-9]", "", urllib.parse.unquote(g["pn"]).upper())} if "pn" in g
                    else SD.slug_tokens(urllib.parse.unquote(g["slug"])))
            for t in toks & want.keys():
                for r, a in want[t]:
                    words = mfr_words(a["maker"])
                    if words and any(w in u.lower() for w in words):
                        r.setdefault("for_sale", [])
                        if not any(x["url"] == u for x in r["for_sale"]):
                            r["for_sale"].append({"seller": dealer, "url": u, "title": None, "price": None, "currency": "USD"})
                            hits += 1
    return hits


def makers_of(r: dict) -> list[str]:
    return sorted({maker_key(a["maker"]) for a in r["approved"] if a.get("maker")})


def redact(r: dict) -> dict:
    """What anyone sees without paying: what is asked for, by whom (agency), how many, and what it last sold for."""
    a = next((x for x in r["approved"] if x.get("maker")), r["approved"][0] if r["approved"] else {})
    return {"part": r["part"], "maker": a.get("maker"), "pn": a.get("pn"), "qty": r["qty"], "unit": r["unit"],
            "agency": r["agency"], "source": r["source"], "last_paid": r["last_paid"], "last_paid_date": r["last_paid_date"],
            "for_sale": len(r.get("for_sale") or []), "n_approved": len(r["approved"])}


def main():
    rows = dibbs_rows() + sam_rows()
    n_sale = attach_supply(rows)
    for r in rows:
        r["makers"] = makers_of(r)
    rows.sort(key=lambda r: (r["due"], r["id"]))
    PRIV.mkdir(parents=True, exist_ok=True)
    built = date.today().isoformat()
    blob = {"built": built, "rows": rows}
    (PRIV / "rows.json.gz").write_bytes(gzip.compress(json.dumps(blob, separators=(",", ":")).encode()))

    mk = Counter(m for r in rows for m in r["makers"])
    n_contact = sum(1 for r in rows if r["buyer_email"])
    n_pn = sum(1 for r in rows if any(a["pn"] for a in r["approved"]))
    n_paid = sum(1 for r in rows if r["last_paid"])
    n_sale_rows = sum(1 for r in rows if r.get("for_sale"))
    dues = sorted(r["due"] for r in rows)
    meta = {
        "built": built, "price_usd": PRICE_USD, "n": len(rows), "n_pn": n_pn, "n_contact": n_contact,
        "n_last_paid": n_paid, "n_for_sale": n_sale_rows, "n_pdf_read": sum(r["pdf_read"] for r in rows),
        "n_makers": len(mk), "due_first": dues[0] if dues else None, "due_last": dues[-1] if dues else None,
        "sources": dict(Counter(r["source"] for r in rows)),
        "makers": [[m, n] for m, n in mk.most_common()],
    }
    (SITE / "asks").mkdir(parents=True, exist_ok=True)
    (SITE / "asks" / "meta.json").write_text(json.dumps(meta, separators=(",", ":")))

    import render_asks
    example = pick_example(rows, mk)
    (SITE / "asks" / "index.html").write_text(render_asks.page(meta, example))
    n_for = 0
    if RECIP.exists():
        for rc in json.loads(RECIP.read_text()):
            own = [r for r in rows if r["id"] in set(rc["ask_ids"])]
            if not own:
                print(f"  ! {rc['token']} {rc['org']}: its ask is no longer open; page not built", file=sys.stderr)
                continue
            line = [m for m in rc.get("lines", []) if m]
            # Others on the page must still be open when the email lands (sends run a few days after a build).
            late = (date.today() + timedelta(days=7)).isoformat()
            pool = [r for r in rows if r["id"] not in set(rc["ask_ids"]) and set(r["makers"]) & set(line) and r["due"] >= late]
            others = sorted(pool, key=lambda r: (-(r["last_paid"] or 0) * (r["qty"] or 0)))[:5]
            n_line = len(pool)
            d = SITE / "for" / rc["token"]
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(render_asks.for_page(meta, rc, own, [redact(r) for r in others], n_line))
            n_for += 1
    print(f"open asks {len(rows):,} (DIBBS {meta['sources'].get('DLA DIBBS', 0):,}, SAM {meta['sources'].get('SAM.gov', 0)}), "
          f"PDF read {meta['n_pdf_read']:,}, buyer email {n_contact:,}, last paid {n_paid:,}, with PN {n_pn:,}, "
          f"for sale {n_sale_rows} ({n_sale} listings), makers {len(mk):,}, due {meta['due_first']}..{meta['due_last']}, /for pages {n_for}")


def pick_example(rows, mk):
    """Pre-load the page with a real line: the most-asked maker that is a plain industrial name with priced rows."""
    for m, _ in mk.most_common(80):
        rs = [r for r in rows if m in r["makers"] and r["last_paid"]]
        if len(rs) >= 3 and not re.search(r"DEFENSE|ARMY|NAVY|AIR FORCE|DLA|GOVERNMENT|NATIONAL", m):
            return {"maker": m, "n": mk[m], "rows": [redact(r) for r in rs[:3]]}
    return {"maker": None, "n": 0, "rows": []}


if __name__ == "__main__":
    main()
