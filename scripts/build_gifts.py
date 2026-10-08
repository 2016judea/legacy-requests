#!/usr/bin/env python3
"""Free per-recipient pages at site/for/<token>/index.html, from data/gifts.json.

Two kinds, both the other side of the reader's own deal:

  dealer  A parts dealer whose own live listing is a part a government asked for. The page
          quotes that listing, shows the filing(s) that asked for that exact part, then every
          ask in the index for the same maker.
  apex    An APEX Accelerator (the former PTACs). The page lists the legacy-equipment asks
          from the agencies in its own service area, and the agency+maker pairs that asked
          more than once, which is where a client could be ready before the next one.

Every number on a page is counted here from site/data.json (what the site serves) and
data/records.jsonl (for the exact-match filings, by record id). Nothing is typed.
Listing prices in gifts.json were read off each dealer's page on its 'checked' date.

Pages carry noindex and are not linked from the site. Run after `make site`:
    .venv/bin/python scripts/build_gifts.py
"""
import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_site import SOFTWARE_WORDS  # noqa: E402  same rule the site uses for "physical"

VA_TAG = ('<script>window.va=window.va||function(){(window.vaq=window.vaq||[]).push(arguments)};</script>'
          '<script defer src="/_vercel/insights/script.js"></script>')  # Vercel Web Analytics, every page
# Gift pages also carry the persistent reader id + touch events: a copy of
# bricks/scripts/outreach/reader_events.js (refresh from there, don't fork it).
VA_TAG += "<script>" + (Path(__file__).with_name("reader_events.js")).read_text().strip() + "</script>"

SITE = ROOT / "site"
OUT = SITE / "for"
BASE = "https://legacy-requests.vercel.app"
SUBSTACK = "https://aidanjude.substack.com/p/project-the-google-of-obsolete-equipment"

esc = lambda s: html.escape(str(s or ""), quote=True)


def money(v):
    if v is None:
        return ""
    return f"${v:,.2f}" if v < 1000 else f"${v:,.0f}"


def load():
    gifts = json.loads((ROOT / "data" / "gifts.json").read_text())["gifts"]
    rows = json.loads((SITE / "data.json").read_text())
    recs = {}
    for line in (ROOT / "data" / "records.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            recs[r["id"]] = r
    return gifts, rows, recs


def dealer_asks(g, rows):
    mre = re.compile(g["maker_re"], re.I) if g.get("maker_re") else None
    pre = re.compile(g["part_re"], re.I) if g.get("part_re") else None
    xre = re.compile(g["exclude_part_re"], re.I) if g.get("exclude_part_re") else None
    out = []
    for r in rows:
        text = " ".join(str(r.get(k) or "") for k in ("part", "manufacturer", "model"))
        hit = bool(mre and mre.search(r.get("manufacturer") or ""))
        if not hit and pre:
            hit = bool(pre.search(" ".join(str(r.get(k) or "") for k in ("part", "model"))))
        if not hit:
            continue
        if xre and xre.search(r.get("part") or ""):
            continue
        if r.get("equipment_class") == "service/maintenance contract" or SOFTWARE_WORDS.search(text):
            continue
        if g.get("classes") and r.get("equipment_class") not in g["classes"]:
            continue
        out.append(r)
    return sorted(out, key=lambda r: r.get("date") or "", reverse=True)


def apex_asks(g, rows):
    want = set(g["agencies"])
    out = [r for r in rows if r.get("agency") in want and r.get("is_physical")]
    return sorted(out, key=lambda r: r.get("date") or "", reverse=True)


def recurring(asks):
    """agency + maker pairs asked in two or more separate filings."""
    by = defaultdict(set)
    for r in asks:
        if r.get("manufacturer"):
            by[(r["agency"], r["manufacturer"])].add(r.get("source_url"))
    pairs = [(a, m, len(s)) for (a, m), s in by.items() if len(s) >= 2]
    return sorted(pairs, key=lambda p: (-p[2], p[0], p[1]))


def row_li(r, mark=False):
    what = " ".join(x for x in [r.get("manufacturer"), r.get("model")] if x)
    pns = ", ".join(str(p) for p in (r.get("part_numbers") or [])[:3])
    bits = [esc(r.get("date") or "no date"), esc(r.get("agency")) + (", " + esc(r["state"]) if r.get("state") else "")]
    qty = f" · qty {esc(r['quantity'])}" if r.get("quantity") else ""
    price = f" · {money(r['price_usd'])} stated" if r.get("price_usd") else ""
    obs = ' <i class="obs">obsolete</i>' if r.get("is_obsolete") else ""
    return (f'<li{" class=hit" if mark else ""}><small>{" · ".join(bits)}</small>'
            f'<b>{esc(r.get("part"))}</b>{obs}'
            f'<span>{esc(what)}{(" · " + esc(pns)) if pns else ""}{qty}{price}</span>'
            f'<a href="{esc(r.get("source_url"))}" target="_blank" rel="noopener">Source document</a></li>')


CSS = """:root{--ink:#141414;--muted:#6b6b6b;--line:#e3e0da;--bg:#faf9f6;--card:#fff;--accent:#b4451d;--accent-bg:#fbeee6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.w{max-width:760px;margin:0 auto;padding:36px 16px 56px}
.brand{font-size:13px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--accent);margin-bottom:16px}
.brand a{color:inherit;text-decoration:none}
h1{font-size:clamp(30px,7vw,46px);line-height:1.08;margin:0 0 14px;letter-spacing:-.02em}
.lede{color:var(--muted);font-size:18px;margin:0 0 22px;max-width:56ch}
.lede a{color:var(--accent)}
.quote{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:14px 16px;margin:0 0 22px}
.quote small{display:block;color:var(--muted);font-size:13px;margin-bottom:4px}
.quote a{color:var(--ink);font-weight:650}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:0 0 28px}
.stats div{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.stats b{display:block;font-size:28px;line-height:1.05;letter-spacing:-.02em}
.stats span{color:var(--muted);font-size:13px}
h2{font-size:clamp(21px,4.5vw,27px);line-height:1.2;margin:30px 0 6px;letter-spacing:-.01em}
.sub{color:var(--muted);margin:0 0 12px}
ul{list-style:none;margin:0;padding:0}
li{border-top:1px solid var(--line);padding:12px 0}
li small{display:block;color:var(--muted);font-size:13px}
li b{font-weight:650}
li span{display:block;color:var(--muted);font-size:14px;margin-top:2px;overflow-wrap:anywhere}
li a{display:inline-block;margin-top:4px;color:var(--accent);font-weight:600;font-size:14px;padding:4px 0}
li.hit{background:var(--accent-bg);border-radius:10px;padding:12px;border-top:0;margin-bottom:6px}
i.obs{font-style:normal;font:600 12px ui-monospace,Menlo,monospace;background:var(--accent-bg);color:var(--accent);border-radius:5px;padding:1px 6px;margin-left:6px}
.pairs li{display:flex;justify-content:space-between;gap:12px}
.pairs li b{font-weight:600}
.pairs li em{font-style:normal;color:var(--muted);white-space:nowrap}
.btn{display:inline-block;margin:18px 0 0;background:var(--ink);color:#fff;text-decoration:none;font-weight:650;padding:13px 18px;border-radius:12px}
.note{color:var(--muted);font-size:14px;margin-top:36px;border-top:1px solid var(--line);padding-top:16px}
.note a{color:var(--muted)}
@media(max-width:420px){.stats b{font-size:24px}}"""


def page(title, body):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{esc(title)}</title>
<style>{CSS}</style>
{VA_TAG}
</head>
<body><div class="w">
{body}
</div></body>
</html>
"""


def note(extra=""):
    return (f'<p class="note">Every ask above is a public agency\'s own filing: a sole-source approval, board item or notice, '
            f'linked to the source document. {extra}Free, from Aidan Jude. Nothing to sign up for. '
            f'<a href="{SUBSTACK}">Why this exists</a>.</p>')


def build_dealer(g, rows, recs):
    asks = dealer_asks(g, rows)
    exact = [recs[i] for i in g.get("exact", []) if i in recs]
    missing = [i for i in g.get("exact", []) if i not in recs]
    if missing:
        sys.exit(f"{g['token']}: exact record ids not in records.jsonl: {missing}")
    n, ag, st = len(asks), len({r["agency"] for r in asks}), len({r["state"] for r in asks if r.get("state")})
    obs = sum(1 for r in asks if r.get("is_obsolete"))
    latest = max((r.get("date") or "" for r in asks), default="")
    L = g["listing"]
    price = f" at ${L['price']:,.2f}" if L.get("price") is not None else " (price on quote)"
    h1 = f"{n} government asks for {g['makers']} {g['noun']}"
    ex_agencies = sorted({r["agency"] for r in exact})
    body = f"""<div class="brand"><a href="{BASE}/">Legacy Requests</a> · for {esc(g['org'])}</div>
<h1>{esc(h1)}</h1>
<p class="lede">Public agencies asking for {esc(g['makers'])} {esc(g['noun'])}, pulled from their own filings. {ag} agencies in {st} states, latest {esc(latest)}.</p>
<div class="quote"><small>Your listing, checked {esc(L['checked'])}</small><a href="{esc(L['url'])}" target="_blank" rel="noopener">{esc(L['title'])}</a>{esc(price)}</div>
<div class="stats"><div><b>{n}</b><span>asks</span></div><div><b>{ag}</b><span>agencies</span></div><div><b>{obs}</b><span>marked obsolete</span></div></div>
<h2>Asked for the part you list</h2>
<p class="sub">{esc(' and '.join(ex_agencies))} filed for it.</p>
<ul>{''.join(row_li(r, True) for r in exact)}</ul>
<h2>Every {esc(g['makers'])} ask in the index</h2>
<p class="sub">Newest first.</p>
<ul>{''.join(row_li(r) for r in asks)}</ul>
<a class="btn" href="{BASE}/?q={quote(g['search'])}">Search the full index for {esc(g['search'])}</a>
{note()}"""
    return h1, page(h1, body), {"asks": n, "agencies": ag, "states": st, "obsolete": obs, "latest": latest,
                                "exact": [(r["agency"], r["date"], r.get("quantity"), r.get("price_usd"), r["source_url"]) for r in exact]}


def build_apex(g, rows, recs):
    asks = apex_asks(g, rows)
    pairs = recurring(asks)
    n, ag = len(asks), len({r["agency"] for r in asks})
    since = sum(1 for r in asks if (r.get("date") or "") >= "2025-10-06")
    region = g.get("short_region") or g["region"]
    h1 = f"{n} legacy-equipment asks from {region}"
    top = Counter(r["agency"] for r in asks).most_common(1)[0][0]
    pairs_html = "".join(f"<li><b>{esc(a)} · {esc(m)}</b><em>{k} filings</em></li>" for a, m, k in pairs)
    body = f"""<div class="brand"><a href="{BASE}/">Legacy Requests</a> · for {esc(g['org'])}</div>
<h1>{esc(h1)}</h1>
<p class="lede">Pumps, drives, controls, radios and instruments that agencies in {esc(g['region'])} asked for by name, most of them filed as sole-source purchases that never went out to bid. Each one links to the agency's own filing.</p>
<div class="stats"><div><b>{n}</b><span>asks</span></div><div><b>{len(pairs)}</b><span>repeat agency + maker pairs</span></div><div><b>{since}</b><span>in the last 12 months</span></div></div>
<h2>Asked more than once</h2>
<p class="sub">The same agency, the same maker, two or more separate filings. A client who stocks or services that maker can be ready before the next one.</p>
<ul class="pairs">{pairs_html or '<li>No repeats yet.</li>'}</ul>
<h2>Every ask from {esc(region)}</h2>
<p class="sub">Newest first.</p>
<ul>{''.join(row_li(r) for r in asks)}</ul>
<a class="btn" href="{BASE}/?agency={quote(top)}">Open {esc(top)} in the full index</a>
{note()}"""
    return h1, page(h1, body), {"asks": n, "agencies": ag, "pairs": len(pairs), "last12": since,
                                "top_pairs": pairs[:3], "top_agency": top}


def main():
    gifts, rows, recs = load()
    seen = set()
    summary = []
    for g in gifts:
        t = g["token"]
        if not re.fullmatch(r"[0-9a-f]{8}", t) or t in seen:
            sys.exit(f"bad or duplicate token {t}")
        seen.add(t)
        h1, doc, facts = (build_dealer if g["kind"] == "dealer" else build_apex)(g, rows, recs)
        d = OUT / t
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(doc)
        summary.append({"token": t, "kind": g["kind"], "org": g["org"], "h1": h1, "url": f"{BASE}/for/{t}/", **facts})
    # stale pages for tokens no longer in gifts.json are removed so they stop deploying
    for d in OUT.iterdir():
        if d.is_dir() and d.name not in seen:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
