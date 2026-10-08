#!/usr/bin/env python3
"""Build /worth: one card per piece of equipment, an image, and what it has actually gone for.

The person here OWNS a thing and wants to know what it is worth (Aidan, 2026-10-01: "Business Pilot
#2. The Google of obsolete equipment. What is everything worth."). So the unit is the ITEM, not the
filing, and the answer is a spread of observed prices with their sources, never one typed number.

An item is (maker, part number). Two kinds feed it:

  - the index: every physical sole-source record with a maker and a part-number-shaped token
    (join_supply.record_tokens — the same rule the supply join uses). What an agency paid, divided
    by the stated quantity, is a "paid" point; a contract with no quantity is shown but kept out of
    the range, because a $209k contract for an unstated number of antennas is not a price.
  - listings: every data/supply/*.jsonl row (Craigslist, GovDeals, PublicSurplus, dealers) whose
    title holds a part-number-shaped token. One that joins a record (the strict join) lands on that
    record's item; the rest become items of their own, named by their own title, so a search for
    a part the agencies never filed still finds a photo and an asking price. Craigslist rows count
    only in equipment categories (EQUIP_CATS) and never when they are a vehicle or a repair service.

Image: the first listing photo in the item, else the drawing make_item_images.py cached for it
(site/worth/img/<id>.jpg, marked as a drawing on the page), else none yet — the page shows a
placeholder and the item ranks below ones with a picture.

Writes data/worth_items.json (everything, for make_item_images.py), site/worth/items.json (the page's
lazy load) and site/worth/index.html with the first page inline. Never hand-edit the output.
"""
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import PLACEHOLDER_PRICE, SOURCE_NAMES, is_physical  # noqa: E402
from join_supply import (ALIASES, is_part_token, join, listing_tokens, load_listings, load_records,  # noqa: E402
                         mfr_words, norm, part_tokens, record_tokens)

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "worth"
IMG = SITE / "img"
SOURCE_NAMES = {**SOURCE_NAMES, "craigslist": "Craigslist", "ebay": "eBay"}
EQUIP_CATS = {"tls", "tld", "ele", "eld", "bfs", "bfd", "grd", "grq", "hvo", "hvd", "sys", "syd", "sop", "sdp", "pts", "ptd",
              "mat", "mad", "pho", "phd", "app", "ppd"}
AUCTION = {"govdeals", "publicsurplus"}
SOLD = {"ebay-sold"}
PAGE = 24
QTY = re.compile(r"\d+(?:\.\d+)?")


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:60]


def mfr_key(name: str) -> str:
    words = mfr_words(name)
    if not words:
        return ""
    for group in ALIASES:
        if words & group:
            return sorted(group)[0]
    return sorted(words, key=lambda w: (-len(w), w))[0]


def primary_token(tokens: set[str]) -> str:
    """The token that names the part: letters-and-digits beats digits-only, longer beats shorter."""
    return sorted(tokens, key=lambda t: (not re.search(r"[A-Z]", t), -len(t), t))[0]


def quantity(q) -> float | None:
    m = QTY.search(str(q or ""))
    if not m:
        return None
    n = float(m.group())
    return n if n >= 1 else None


def display_pn(record: dict, token: str) -> str:
    """The part number as printed, when the filing printed one."""
    for pn in record.get("part_numbers") or []:
        if norm(str(pn).split("+")[0]) == token:
            return str(pn).split("+")[0]
    return record.get("model") or token


def keep_listing(l: dict) -> bool:
    if l.get("price") is None:
        return False
    if l["source"] == "craigslist" and l.get("category") not in EQUIP_CATS:
        return False
    return bool(listing_tokens(l))  # also drops vehicles and repair services


def point_for_listing(l: dict) -> dict:
    kind = "auction" if l["source"] in AUCTION else "sold" if l["source"] in SOLD else "asking"
    return {"k": kind, "p": round(float(l["price"]), 2), "s": l["source"], "t": l["title"], "u": l["url"],
            "d": l.get("posted") or l.get("seen_at"), "l": l.get("location")}


def point_for_record(r: dict) -> dict | None:
    if not r.get("price_usd") or r["price_usd"] < PLACEHOLDER_PRICE:
        return None
    q = quantity(r.get("quantity"))
    base = {"s": "agency", "t": f"{r['agency']}, {r['state']}", "u": r.get("source_url"), "d": r.get("date"), "l": None}
    if q:
        return {"k": "paid", "p": round(r["price_usd"] / q, 2), "q": q, **base}
    return {"k": "contract", "p": round(r["price_usd"], 2), **base}


def build() -> list[dict]:
    records = [r for r in load_records() if is_physical(r)]
    listings = [l for l in load_listings() if keep_listing(l)]
    matched = join(records, listings)  # record id -> listings, strict rule
    matched_urls = {l["url"] for ls in matched.values() for l in ls}

    items: dict[tuple, dict] = {}

    def item(key: tuple, **init) -> dict:
        if key not in items:
            items[key] = {"key": key, "records": [], "listings": [], "aliases": set(), **init}
        return items[key]

    for r in records:
        toks = record_tokens(r)
        if not toks:
            continue
        tok = primary_token(toks)
        it = item((mfr_key(r["manufacturer"]), tok), manufacturer=r["manufacturer"], pn=display_pn(r, tok),
                  model=r.get("model"), part=r.get("part"), equipment_class=r.get("equipment_class"), is_obsolete=False)
        it["records"].append(r)
        it["aliases"] |= toks
        it["is_obsolete"] = it["is_obsolete"] or bool(r.get("is_obsolete"))
        for l in matched.get(r["id"], []):
            it["listings"].append(l)

    makers = {}  # frozenset of maker words -> display name, from the index
    for r in records:
        if r.get("manufacturer"):
            w = frozenset(mfr_words(r["manufacturer"]))
            if w and (len(w) > 1 or len(next(iter(w))) >= 5):
                makers.setdefault(w, r["manufacturer"])

    for l in listings:
        if l["url"] in matched_urls:
            continue
        toks = listing_tokens(l)
        tok = primary_token(toks)
        words = set(re.findall(r"[a-z0-9]+", l["title"].lower()))
        maker = next((name for w, name in makers.items() if w <= words), None)
        it = item((mfr_key(maker) if maker else "", tok), manufacturer=maker, pn=tok, model=None, part=None,
                  equipment_class=None, is_obsolete=False)
        it["listings"].append(l)
        it["aliases"] |= toks

    out = []
    for key, it in items.items():
        points = [p for p in (point_for_record(r) for r in it["records"]) if p]
        seen = set()
        for l in sorted(it["listings"], key=lambda l: l.get("posted") or l.get("seen_at") or "", reverse=True):
            if l["url"] not in seen:
                seen.add(l["url"])
                points.append(point_for_listing(l))
        prices = sorted(p["p"] for p in points if p["k"] in ("paid", "asking", "auction", "sold"))
        stats = {"n": len(prices), "low": prices[0], "high": prices[-1], "median": round(statistics.median(prices), 2)} if prices else None
        photo = next((l["image"] for l in it["listings"] if l.get("image")), None)
        name = it["part"] or min((l["title"] for l in it["listings"]), key=len, default=it["pn"])
        if it["records"]:
            ident = f"{it['manufacturer']} {it['pn']}"
        else:
            ident = f"{it['manufacturer']} {it['pn']}" if it["manufacturer"] else it["pn"]
        iid = slug(f"{key[0]}-{key[1]}") if key[0] else slug(key[1])
        obsolete_n = sum(1 for r in it["records"] if r.get("is_obsolete"))
        lead = next((r["lead_time"] for r in it["records"] if r.get("lead_time")), None)
        out.append({"id": iid, "name": name[:140], "ident": ident, "manufacturer": it["manufacturer"], "pn": it["pn"],
                    "model": it["model"], "part": it["part"], "equipment_class": it["equipment_class"],
                    "aliases": sorted(it["aliases"]), "photo": photo,
                    "drawing": (IMG / f"{iid}.jpg").exists(), "points": points, "stats": stats,
                    "n_records": len(it["records"]), "n_listings": len(seen), "obsolete": obsolete_n, "lead_time": lead,
                    "agencies": sorted({r["agency"] for r in it["records"]})[:6]})
    # the same id from two keys (a listing-only item that later gets a maker) — keep the richer one
    by_id: dict[str, dict] = {}
    for it in out:
        if it["id"] not in by_id or len(it["points"]) > len(by_id[it["id"]]["points"]):
            by_id[it["id"]] = it
    out = list(by_id.values())
    out.sort(key=rank)
    return out


def rank(it: dict):
    """Evidence first: a priced spread beats a single point beats a contract total; a picture beats none."""
    n = it["stats"]["n"] if it["stats"] else 0
    return (-min(n, 5), not (it["photo"] or it["drawing"]), -len(it["points"]), -(it["stats"]["median"] if it["stats"] else 0), it["id"])


PAGE_FIELDS = ["id", "name", "ident", "manufacturer", "pn", "aliases", "photo", "drawing", "points", "stats", "n_records",
               "n_listings", "obsolete", "lead_time", "agencies", "equipment_class"]


def slim(items):
    return [{k: it[k] for k in PAGE_FIELDS} for it in items]


def render(items: list[dict]) -> str:
    n_points = sum(len(it["points"]) for it in items)
    n_photo = sum(1 for it in items if it["photo"])
    n_draw = sum(1 for it in items if not it["photo"] and it["drawing"])
    sources = sorted({p["s"] for it in items for p in it["points"]})
    n_agencies = len({a for it in items for a in it["agencies"]})
    first = json.dumps(slim(items[:PAGE]), separators=(",", ":")).replace("</", "<\\/")
    meta = json.dumps({"total": len(items), "points": n_points, "photo": n_photo, "drawing": n_draw})
    src_names = [SOURCE_NAMES.get(s, s) for s in sources if s != "agency"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What is it worth? — obsolete equipment prices</title>
<meta name="description" content="Type a part number or model and see what {len(items):,} pieces of industrial equipment have actually gone for: {n_points:,} observed prices from public-agency purchases, surplus auctions and classifieds, each linked to its source.">
<style>
:root{{--ink:#141414;--muted:#6b6b6b;--line:#e3e0da;--bg:#faf9f6;--card:#fff;--accent:#b4451d;--accent-bg:#fbeee6;--ok:#1d6b3a;--ok-bg:#e7f3ea;--paid:#1d4f8b;--paid-bg:#e6eef9}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}}
header{{max-width:1100px;margin:0 auto;padding:36px 16px 10px}}
h1{{font-size:clamp(30px,7vw,46px);line-height:1.05;margin:0 0 10px;letter-spacing:-.02em}}
.lede{{color:var(--muted);margin:0 0 16px;max-width:56ch;font-size:16px}}
.lede b{{color:var(--ink)}}
.search{{position:relative}}
input[type=search]{{width:100%;font:inherit;font-size:19px;padding:15px 16px;border:2px solid var(--ink);border-radius:14px;background:var(--card);-webkit-appearance:none}}
input[type=search]:focus{{outline:3px solid var(--accent);outline-offset:2px}}
.eg{{margin:10px 0 0;font-size:13px;color:var(--muted)}}
.eg button{{font:inherit;font-size:13px;background:none;border:1px solid var(--line);border-radius:999px;padding:4px 10px;margin:4px 4px 0 0;cursor:pointer;color:var(--ink)}}
main{{max-width:1100px;margin:0 auto;padding:0 16px 60px}}
.count{{color:var(--muted);font-size:13px;margin:16px 0 8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}}
.pic{{position:relative;background:#eeece7;aspect-ratio:4/3;overflow:hidden}}
.pic img{{width:100%;height:100%;object-fit:cover;display:block}}
.pic.draw img{{object-fit:contain;background:#e9e7e2}}
.pic .tag{{position:absolute;left:8px;top:8px;font-size:11px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;background:rgba(255,255,255,.9);border-radius:6px;padding:3px 7px;color:var(--muted)}}
.pic.none{{display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:13px}}
.body{{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;flex:1}}
.ident{{font-weight:700;font-size:16px;line-height:1.25;overflow-wrap:anywhere}}
.ident .ob{{display:inline-block;font-size:11px;font-weight:600;padding:2px 6px;border-radius:6px;background:var(--accent-bg);color:var(--accent);margin-left:6px;vertical-align:middle}}
.name{{color:var(--muted);font-size:14px;line-height:1.35;overflow-wrap:anywhere}}
.range{{font-size:22px;font-weight:700;letter-spacing:-.01em;font-variant-numeric:tabular-nums;margin-top:2px}}
.range small{{display:block;font-size:13px;font-weight:400;color:var(--muted)}}
.one{{font-size:14px;color:var(--muted)}}
.chips{{display:flex;flex-wrap:wrap;gap:5px}}
.chip{{font-size:12px;border-radius:6px;padding:2px 7px;background:#f3f1ec;color:var(--muted)}}
.chip.paid{{background:var(--paid-bg);color:var(--paid)}}
.chip.asking{{background:var(--ok-bg);color:var(--ok)}}
.chip.auction{{background:var(--accent-bg);color:var(--accent)}}
details{{margin-top:auto;padding-top:6px}}
summary{{cursor:pointer;color:var(--accent);font-weight:600;font-size:14px;list-style:none}}
summary::-webkit-details-marker{{display:none}}
summary::after{{content:" ↓";font-weight:400}}
details[open] summary::after{{content:" ↑"}}
.pts{{list-style:none;margin:8px 0 0;padding:0;font-size:13px}}
.pts li{{display:flex;gap:10px;justify-content:space-between;align-items:baseline;padding:6px 0;border-top:1px dashed var(--line)}}
.pts .p{{font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums}}
.pts .w{{color:var(--muted);overflow-wrap:anywhere}}
.pts a{{color:var(--ink)}}
.more{{display:block;margin:20px auto;font:inherit;padding:12px 20px;border-radius:12px;border:1px solid var(--line);background:var(--card);cursor:pointer}}
.more[hidden]{{display:none}}
.empty{{padding:40px 16px;text-align:center;color:var(--muted)}}
footer{{max-width:1100px;margin:0 auto;padding:0 16px 40px;color:var(--muted);font-size:13px;line-height:1.5}}
footer a{{color:var(--accent)}}
@media (max-width:600px){{header{{padding-top:26px}}.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
<h1>What is it worth?</h1>
<p class="lede">Type the part number, model or maker of a piece of equipment you own. <b>{len(items):,} items</b> with <b>{n_points:,} real prices</b>: what {n_agencies} public agencies paid, what surplus auctions closed at, what sellers are asking on {", ".join(src_names)}.</p>
<div class="search"><input id="q" type="search" placeholder="e.g. 1756-IB16, ACS880, Flygt 3153…" autocomplete="off" autocapitalize="off" spellcheck="false" autofocus></div>
<p class="eg">Try: {''.join(f'<button data-q="{it["pn"]}">{it["pn"]}</button>' for it in items[:5] if it["manufacturer"])}</p>
</header>
<main>
<div class="count" id="count"></div>
<div class="grid" id="grid"></div>
<button class="more" id="more" hidden>Show more</button>
</main>
<footer>
<p><b>Where the prices come from.</b> <span style="color:var(--paid)">Paid</span> is what a public agency paid per unit in a sole-source filing (price divided by the quantity it states; a contract with no quantity is listed but left out of the range). <span style="color:var(--accent)">Auction</span> is a bid on GovDeals or PublicSurplus the day it was read. <span style="color:var(--ok)">Asking</span> is a seller's price on Craigslist or a surplus dealer, not a sale. Every price links to where it was seen; a listing can sell or expire after that date. Nothing here is typed by hand.</p>
<p><b>Pictures.</b> A photo is the seller's own listing photo. A <i>drawing</i> is an AI technical illustration made from the part's description so you can orient around it; it is not evidence of condition or model. {n_photo:,} items have a photo, {n_draw:,} a drawing.</p>
<p><a href="/">The index of sole-source purchases these items come from &rarr;</a> Regenerated {date.today().isoformat()}.</p>
</footer>
<script id="data" type="application/json">{first}</script>
<script>
let R=JSON.parse(document.getElementById('data').textContent),full=false;
const META={meta},SRC={json.dumps(SOURCE_NAMES)},PAGE={PAGE};
const $=s=>document.querySelector(s);
const q=$('#q'),grid=$('#grid'),count=$('#count'),more=$('#more');
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
const money=v=>v==null?'':'$'+(v>=100?Math.round(v).toLocaleString():v.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}}));
const nrm=s=>String(s||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
const hay=r=>{{r._h=[r.ident,r.name,r.manufacturer,r.pn,(r.aliases||[]).join(' '),(r.agencies||[]).join(' '),r.equipment_class].join(' ').toLowerCase();r._n=(r.aliases||[]).map(nrm).concat([nrm(r.pn)])}};
R.forEach(hay);
let page=1;
function filtered(){{
  const raw=q.value.trim();if(!raw)return R;
  const terms=raw.toLowerCase().split(/\\s+/).filter(Boolean),n=nrm(raw);
  return R.filter(r=>terms.every(t=>r._h.includes(t))||(n.length>=4&&r._n.some(a=>a.includes(n))));
}}
const KIND={{paid:'paid',asking:'asking',auction:'auction',sold:'sold',contract:'contract'}};
function pt(p){{
  const who=p.s==='agency'?esc(p.t)+(p.k==='paid'&&p.q>1?` · ${{p.q}} units`:p.k==='contract'?' · total, quantity not stated':''):esc(SRC[p.s]||p.s)+(p.l?' · '+esc(p.l):'');
  return `<li><span class="p">${{money(p.p)}}<br><span class="chip ${{p.k}}">${{KIND[p.k]}}</span></span><span class="w"><a href="${{esc(p.u)}}" target="_blank" rel="noopener">${{who}}</a>${{p.d?' · '+esc(p.d):''}}${{p.s!=='agency'?'<br>'+esc(p.t):''}}</span></li>`;
}}
function card(r){{
  const pic=r.photo?`<div class="pic"><img loading="lazy" src="${{esc(r.photo)}}" alt="" referrerpolicy="no-referrer" onerror="this.parentNode.className='pic none';this.parentNode.textContent='photo gone'"><span class="tag">photo</span></div>`:r.drawing?`<div class="pic draw"><img loading="lazy" src="img/${{r.id}}.jpg" alt=""><span class="tag">drawing</span></div>`:`<div class="pic none">no picture yet</div>`;
  const s=r.stats;const kinds=[...new Set(r.points.map(p=>p.k))];
  const range=s?(s.n>1?`<div class="range">${{money(s.low)}} – ${{money(s.high)}}<small>median ${{money(s.median)}} · ${{s.n}} prices</small></div>`:`<div class="range">${{money(s.low)}}<small>one price seen</small></div>`):`<div class="one">${{r.points.length?'contract total only, no unit price':'no price seen yet'}}</div>`;
  const chips=kinds.map(k=>`<span class="chip ${{k}}">${{r.points.filter(p=>p.k===k).length}} ${{KIND[k]}}</span>`).join('')+(r.lead_time?`<span class="chip">lead time ${{esc(r.lead_time)}}</span>`:'');
  return `<article class="card">${{pic}}<div class="body"><div class="ident">${{esc(r.ident)}}${{r.obsolete?'<span class="ob">obsolete</span>':''}}</div><div class="name">${{esc(r.name)}}</div>${{range}}<div class="chips">${{chips}}</div><details><summary>Every price, with its source</summary><ul class="pts">${{r.points.map(pt).join('')}}</ul></details></div></article>`;
}}
function draw(reset){{
  if(reset)page=1;
  const f=filtered(),show=f.slice(0,page*PAGE);
  grid.innerHTML=show.map(card).join('')||(full?`<div class="empty">Nothing for “${{esc(q.value)}}” yet. Try the maker's name alone, or a shorter part number.</div>`:'');
  count.textContent=full?(q.value.trim()?`${{f.length.toLocaleString()}} of ${{R.length.toLocaleString()}} items`:`${{R.length.toLocaleString()}} items, best-evidenced first`):(q.value.trim()?`Searching all ${{META.total.toLocaleString()}} items…`:`${{META.total.toLocaleString()}} items, best-evidenced first`);
  more.hidden=!full||show.length>=f.length;
  const u=new URL(location);q.value.trim()?u.searchParams.set('q',q.value.trim()):u.searchParams.delete('q');history.replaceState(null,'',u);
}}
fetch('items.json').then(r=>{{if(!r.ok)throw r.status;return r.json()}}).then(d=>{{R=d;R.forEach(hay);full=true;draw(false)}}).catch(()=>{{count.textContent='Could not load every item. Reload to try again.'}});
q.addEventListener('input',()=>draw(true));
document.querySelectorAll('.eg button').forEach(b=>b.addEventListener('click',()=>{{q.value=b.dataset.q;draw(true);q.focus()}}));
more.addEventListener('click',()=>{{page++;draw(false)}});
q.value=new URL(location).searchParams.get('q')||'';
draw(true);
</script>
</body>
</html>
"""


def main():
    items = build()
    SITE.mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "worth_items.json").write_text(json.dumps(items, separators=(",", ":")))
    (SITE / "items.json").write_text(json.dumps(slim(items), separators=(",", ":")))
    (SITE / "index.html").write_text(render(items))
    n_pts = sum(len(it["points"]) for it in items)
    by_src = defaultdict(int)
    for it in items:
        for p in it["points"]:
            by_src[p["s"]] += 1
    print(f"site/worth/index.html: {len(items)} items ({sum(1 for it in items if it['n_records'])} from the index, "
          f"{sum(1 for it in items if not it['n_records'])} from listings only), {n_pts} price points {dict(by_src)}, "
          f"{sum(1 for it in items if it['photo'])} with a photo, {sum(1 for it in items if not it['photo'] and it['drawing'])} with a drawing, "
          f"{sum(1 for it in items if it['stats'] and it['stats']['n'] >= 2)} with a spread; "
          f"index.html {(SITE / 'index.html').stat().st_size // 1024} KB, items.json {(SITE / 'items.json').stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
