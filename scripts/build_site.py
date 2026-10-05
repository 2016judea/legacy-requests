#!/usr/bin/env python3
"""Generate site/index.html, site/data.json and site/records.json from data/records.jsonl.

The page is static and searched in the browser. First paint carries only the
default view (the first page of physical rows, most expensive first) inline;
site/data.json holds every record in the fields the page draws, fetched right
after first paint, and every search runs over it. records.json is the full
download. This file is the only source of all three — never hand-edit the output.

Why split: at 7,055 records the page embedded everything and weighed 8.8MB,
for a phone. 2026-09-25.
"""
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
TITLE = "The Google of obsolete infrastructure parts"

FIELDS = ["part_numbers", "id", "manufacturer", "model", "part", "quantity", "price_usd", "lead_time", "sole_source_vendor", "reason",
          "equipment_class", "installed_location", "is_obsolete", "agency", "state", "date", "source_url", "legistar_url", "title"]


PLACEHOLDER_PRICE = 100  # Columbus files "$1.00" as a not-to-exceed placeholder on universal term contracts

# This site is about PHYSICAL obsolete infrastructure — a board, a drive, an
# impeller. `equipment_class` cannot express that on its own, because the model
# emits one bucket, "SCADA/controls/software", holding both halves: "BOARD FLIR
# VIP3D.1s Video Detection Processor" and "MODULE PIM CARD SDLC INTERFACE" sit
# in it beside "Self-checkout kiosk software module subscription".
#
# Splitting on class alone was wrong in both directions — it hid 22 real
# hardware rows behind the software toggle, and let ~270 non-physical rows into
# the default view. So we read the part text instead. Derived at build time, so
# it costs no model calls and changing the rule is a rebuild, not a re-extract.
SOFTWARE_WORDS = re.compile(
    r"\b(software|licen[cs]e|licensing|subscription|saas|cloud|hosting|hosted|records management"
    r"|professional services|maintenance and support|implementation services|training|portal|website"
    r"|web app|mobile app|data migration|annual support|user seats?|kiosk|signage|patron)\b", re.I)

# Unambiguously a physical object.
STRONG_HARDWARE = re.compile(
    r"\b(board|rack|chassis|encoder|decoder|impeller|bearing|gearbox|rotor|stator|shaft|coupling|bushing"
    r"|vfd|plc|rtu|hmi|switchgear|transformer|breaker|contactor|starter|motor|pump|valve|blower|compressor"
    r"|generator|transmitter|probe|centrifuge|clarifier|aerator|membrane|power supply|antenna|nozzle|gasket)\b", re.I)

# Physical only in company — "module" and "card" appear in both worlds, so one
# on its own proves nothing and two together do.
WEAK_HARDWARE = re.compile(
    r"\b(module|card|panel|drive|unit|assembly|housing|controller|processor|cpu|actuator|relay|sensor"
    r"|analyzer|meter|screen|mixer|gate|pipe|fitting|seal|camera|detector|radio|terminal|cabinet)\b", re.I)

PHYSICAL_CLASSES = {"pump", "valve", "motor/drive", "electrical/switchgear/transformer", "generator", "HVAC",
                    "pipe/fitting", "treatment process (membrane/centrifuge/UV/chemical feed)",
                    "instrumentation/calibration"}


def is_physical(r: dict) -> bool:
    """True when this record is a thing that can wear out and need a part."""
    text = " ".join(str(r.get(k) or "") for k in ("part", "manufacturer", "model"))
    if SOFTWARE_WORDS.search(text):
        return False
    if r.get("equipment_class") == "service/maintenance contract":
        return False
    if r.get("equipment_class") in PHYSICAL_CLASSES:
        return True
    if STRONG_HARDWARE.search(text):
        return True
    return len(set(m.lower() for m in WEAK_HARDWARE.findall(text))) >= 2


SUPPLY_FIELDS = ["source", "title", "price", "currency", "url", "seen_at", "location"]
SOURCE_NAMES = {"govdeals": "GovDeals", "publicsurplus": "PublicSurplus", "radwell": "Radwell", "mroelectric": "MRO Electric",
                "kempston": "Kempston Controls", "artisantg": "Artisan Technology Group", "bidonequipment": "Bid on Equipment",
                "eltra": "Eltra Trade", "aotewell": "Aotewell",
                "euautomation": "EU Automation", "plccenter": "PLC Center"}


def load_supply() -> dict:
    """data/supply/matches.json, written by scripts/join_supply.py (make join)."""
    f = ROOT / "data" / "supply" / "matches.json"
    if not f.exists():
        return {}
    return {rid: [{k: l.get(k) for k in SUPPLY_FIELDS} for l in ls] for rid, ls in json.loads(f.read_text()).items()}


def load():
    recs = [json.loads(l) for l in (ROOT / "data" / "records.jsonl").read_text().splitlines() if l.strip()]
    out = [{k: r.get(k) for k in FIELDS} for r in recs]
    supply = load_supply()
    for r in out:
        r["supply"] = supply.get(r["id"], [])
        if r["price_usd"] is not None and r["price_usd"] < PLACEHOLDER_PRICE:
            r["price_usd"] = None
        r["is_physical"] = is_physical(r)
    return out


def span(dates):
    if not dates:
        return ""
    a, b = dates[0][:4], dates[-1][:4]
    return a if a == b else f"{a}–{b}"


SHORT = {"treatment process (membrane/centrifuge/UV/chemical feed)": "treatment process",
         "electrical/switchgear/transformer": "electrical", "instrumentation/calibration": "instrumentation",
         "SCADA/controls/software": "SCADA/software", "service/maintenance contract": "service contract",
         "vehicle/fleet": "vehicles", "communications/radio": "radio", "motor/drive": "motors/drives"}


HARDWARE = ["pump", "valve", "motor/drive", "electrical/switchgear/transformer", "generator", "HVAC", "pipe/fitting",
            "treatment process (membrane/centrifuge/UV/chemical feed)", "instrumentation/calibration", "communications/radio",
            "vehicle/fleet", "other equipment"]
SOFT = ["SCADA/controls/software", "service/maintenance contract"]


PAGE = 100
# What the page draws; data.json carries only these (no id, title or legistar_url).
PAGE_FIELDS = ["manufacturer", "model", "part_numbers", "part", "quantity", "price_usd", "lead_time", "sole_source_vendor",
               "reason", "equipment_class", "installed_location", "is_obsolete", "agency", "state", "date", "source_url",
               "supply", "is_physical"]


def slim(recs: list[dict]) -> list[dict]:
    return [{k: r[k] for k in PAGE_FIELDS} for r in recs]


def default_view(recs: list[dict]) -> list[dict]:
    """The rows the page shows before anyone touches it: physical, price descending, nulls last.
    sorted() is stable, like the browser's Array.sort, so ties keep file order in both."""
    phys = [r for r in recs if r["is_physical"]]
    return sorted(phys, key=lambda r: (r["price_usd"] is None, -(r["price_usd"] or 0)))


def render(recs: list[dict]) -> str:
    agencies = sorted({r["agency"] for r in recs})
    n_hw = sum(1 for r in recs if r["is_physical"])
    n_soft = len(recs) - n_hw
    classes = [c for c, _ in Counter(r["equipment_class"] for r in recs).most_common()]
    classes = [c for c in classes if c not in SOFT] + [c for c in classes if c in SOFT]
    n_mfr = len({(r["manufacturer"] or "").lower() for r in recs if r["manufacturer"]})
    n_price = sum(1 for r in recs if r["price_usd"])
    dates = sorted(r["date"] for r in recs if r["date"])
    first = default_view(recs)
    data = json.dumps(slim(first[:PAGE]), separators=(",", ":")).replace("</", "<\\/")
    meta = json.dumps({"total": len(recs), "n_default": len(first), "sum_default": sum(r["price_usd"] or 0 for r in first)})
    n_sup = sum(1 for r in recs if r["supply"] and r["is_physical"])
    n_list = len({l["url"] for r in recs for l in r["supply"]})
    sources = sorted({l["source"] for r in recs for l in r["supply"]})
    names = [SOURCE_NAMES.get(x, x) for x in sources]
    sup_names = ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + (names[-1] if names else "")
    sup_lede = (f' <b>{n_sup:,} can be bought right now</b>: {n_list:,} matching listing{"s" if n_list != 1 else ""} on {sup_names}.'
                if n_sup else "")
    n_open = len(load_open())
    open_lede = f' <a href="/open"><b>{n_open} federal sole-source notices are still open</b> for a supplier to answer &rarr;</a>' if n_open else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}</title>
<meta name="description" content="{len(recs):,} sole-source equipment purchases by {len(agencies)} public agencies since 2024: manufacturer, model, price, and the stated reason no one else could supply it, each linked to the source document.">
<style>
:root{{--ink:#141414;--muted:#6b6b6b;--line:#e3e0da;--bg:#faf9f6;--card:#fff;--accent:#b4451d;--accent-bg:#fbeee6}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}}
header{{padding:28px 16px 12px;max-width:1280px;margin:0 auto}}
h1{{font-size:clamp(22px,4.5vw,34px);line-height:1.15;margin:0 0 8px;letter-spacing:-.01em}}
.lede{{color:var(--muted);margin:0 0 18px;max-width:62ch}}
.lede b{{color:var(--ink)}}
.controls{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
input[type=search]{{flex:1 1 260px;font:inherit;font-size:17px;padding:11px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card);min-width:0}}
input[type=search]:focus{{outline:2px solid var(--accent);outline-offset:1px}}
select{{font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);max-width:100%}}
label.tog{{display:inline-flex;gap:6px;align-items:center;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);cursor:pointer;white-space:nowrap}}
.chips{{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}}
.chip{{font:inherit;font-size:13px;padding:6px 10px;border-radius:999px;border:1px solid var(--line);background:var(--card);cursor:pointer;color:var(--ink)}}
.chip[aria-pressed=true]{{background:var(--ink);color:#fff;border-color:var(--ink)}}
.count{{color:var(--muted);font-size:13px;margin:14px 0 6px}}
main{{max-width:1280px;margin:0 auto;padding:0 16px 60px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
th{{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);padding:10px 12px;border-bottom:1px solid var(--line);background:#f3f1ec;cursor:pointer;user-select:none;white-space:nowrap}}
th.num,td.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
td{{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}}
td.ag{{min-width:190px}}
td.dt{{white-space:nowrap}}
td.pt{{min-width:220px}}
tr:last-child td{{border-bottom:0}}
.mm{{font-weight:600}}
.mm small{{display:block;font-weight:400;color:var(--muted)}}
.reason{{color:var(--muted);font-style:italic;max-width:46ch}}
.ob{{display:inline-block;font-size:11px;font-weight:600;padding:2px 7px;border-radius:6px;background:var(--accent-bg);color:var(--accent);margin-left:6px;vertical-align:middle;letter-spacing:.02em}}
a{{color:var(--accent)}}
.src{{white-space:nowrap}}
.sup{{margin-top:6px;font-size:13px}}
.sup summary{{display:inline-block;cursor:pointer;font-weight:600;color:#1d6b3a;background:#e7f3ea;border-radius:6px;padding:2px 8px;list-style:none}}
.sup summary::-webkit-details-marker{{display:none}}
.sup ul{{margin:6px 0 0;padding:0;list-style:none}}
.sup li{{padding:4px 0;border-top:1px dashed var(--line)}}
.sup li small{{color:var(--muted)}}
.more{{display:block;margin:18px auto;font:inherit;padding:10px 18px;border-radius:10px;border:1px solid var(--line);background:var(--card);cursor:pointer}}
.more[hidden]{{display:none}}
.empty{{padding:40px 16px;text-align:center;color:var(--muted)}}
footer{{max-width:1280px;margin:0 auto;padding:0 16px 40px;color:var(--muted);font-size:13px}}
@media (max-width:900px){{
  header{{padding-top:18px}}
  .lede{{font-size:14px;margin-bottom:12px}}
  .controls{{gap:6px}}
  /* 16px floor on the phone: iOS Safari zooms in on a focused control under 16px and never zooms back (mobile-ui-audit, 2026-10-04) */
  select{{flex:1 1 40%;min-width:0;padding:8px 10px;font-size:16px}}
  label.tog{{flex:1 1 45%;justify-content:center;padding:8px;font-size:13px;white-space:normal;text-align:center}}
  .chips{{flex-wrap:nowrap;overflow-x:auto;margin:8px -16px 0;padding:0 16px 6px;scrollbar-width:none}}
  .chips::-webkit-scrollbar{{display:none}}
  .chip{{white-space:nowrap}}
  .count{{margin-top:8px}}
  table,thead,tbody,tr,td{{display:block}}
  td.e{{display:none}}
  thead{{display:none}}
  tr{{padding:12px 14px;border-bottom:1px solid var(--line)}}
  td{{padding:2px 0;border:0}}
  td.num{{text-align:left}}
  td[data-l]::before{{content:attr(data-l) " ";color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
  .reason{{max-width:none;margin-top:4px}}
}}
</style>
</head>
<body>
<header>
<h1>{TITLE}</h1>
<p class="lede"><b>{n_hw:,} pieces of physical equipment</b> that <b>{len(agencies)} public agencies</b> could buy from only one supplier, {span(dates)}. Each row quotes the agency's own reason and links to the source document.{sup_lede}{open_lede}</p>
<div class="controls">
  <input id="q" type="search" placeholder="Search manufacturer, model, part, vendor, agency…" autocomplete="off" autofocus>
  <select id="mfr"><option value="">All manufacturers</option></select>
  <select id="agency"><option value="">All agencies</option>{''.join(f'<option>{a}</option>' for a in agencies)}</select>
  <label class="tog"><input type="checkbox" id="obs"> Obsolete / discontinued only</label>
  {'<label class="tog"><input type="checkbox" id="sup"> For sale now only</label>' if n_sup else '<input type="checkbox" id="sup" hidden>'}
  <label class="tog"><input type="checkbox" id="soft"> Include software, licences &amp; service contracts</label>
</div>
<div class="chips" id="chips">{''.join(f'<button class="chip" data-c="{c}" aria-pressed="false">{SHORT.get(c, c)}</button>' for c in classes)}</div>
</header>
<main>
<div class="count" id="count"></div>
<table id="t"><thead><tr>
<th data-k="manufacturer">Manufacturer / model</th><th data-k="part">Part</th><th data-k="agency">Agency</th>
<th class="num" data-k="price_usd">Price</th><th data-k="lead_time">Lead time</th><th data-k="reason">Their reason</th><th data-k="date">Date</th><th>Source</th>
</tr></thead><tbody id="rows"></tbody></table>
<button class="more" id="more" hidden>Show more</button>
</main>
<footer>Built from the Legistar public API (sole-source, single-source, proprietary and obsolete-equipment matters introduced since 2024-01-01) and the state sole-source notice boards of Florida (Vendor Bid System, since 2022) and Mississippi, and federal sole-source, brand-name and J&amp;A notices on SAM.gov (posted since 2025-09-26), extracted with Claude, never typed by hand. "Who has one" listings come from public surplus auctions and surplus dealers, searched for each record's manufacturer and part number, and count only when both agree; a listing can end or sell after the date it was seen. A field is blank when the agency's document did not state it. Regenerated {date.today().isoformat()}.</footer>
<script id="data" type="application/json">{data}</script>
<script>
let R=JSON.parse(document.getElementById('data').textContent),full=false;
const META={meta};
const $=s=>document.querySelector(s);
const q=$('#q'),mfr=$('#mfr'),ag=$('#agency'),obs=$('#obs'),sup=$('#sup'),soft=$('#soft'),rows=$('#rows'),count=$('#count'),more=$('#more');
const SRC={json.dumps(SOURCE_NAMES)};
const SOFT=new Set({json.dumps(SOFT)});
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
const money=v=>v==null?'':'$'+Math.round(v).toLocaleString();
let cls=new Set(),sortK='price_usd',sortD=-1,page=1;const PAGE={PAGE};
const hay=r=>r._h=[r.manufacturer,r.model,(r.part_numbers||[]).join(' '),r.part,r.sole_source_vendor,r.agency,r.state,r.reason,r.installed_location,r.equipment_class].join(' ').toLowerCase();
R.forEach(hay);
// the inline rows are only the default view; every record arrives in data.json right after first paint
const isDefault=()=>!q.value.trim()&&!mfr.value&&!ag.value&&!obs.checked&&!sup.checked&&!soft.checked&&!cls.size&&sortK==='price_usd'&&sortD===-1;
function loadAll(){{
  fetch('data.json').then(r=>{{if(!r.ok)throw r.status;return r.json()}}).then(d=>{{
    R=d;R.forEach(hay);full=true;
    // manufacturers, most frequent first
    const mc={{}};R.forEach(r=>{{if(r.manufacturer)mc[r.manufacturer]=(mc[r.manufacturer]||0)+1}});
    const want=new URL(location).searchParams.get('mfr')||mfr.value;
    Object.entries(mc).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).forEach(([m,n])=>{{const o=document.createElement('option');o.value=m;o.textContent=`${{m}} (${{n}})`;mfr.append(o)}});
    mfr.value=want;draw(false);
  }}).catch(()=>{{count.textContent='Could not load the full index. Reload to try again.'}});
}}
function filtered(){{
  const terms=q.value.toLowerCase().split(/\\s+/).filter(Boolean);
  return R.filter(r=>(!mfr.value||r.manufacturer===mfr.value)&&(!ag.value||r.agency===ag.value)&&(!obs.checked||r.is_obsolete)&&(!sup.checked||r.supply.length)&&(cls.size?cls.has(r.equipment_class):(soft.checked||r.is_physical))&&terms.every(t=>r._h.includes(t)))
    .sort((a,b)=>{{const x=a[sortK],y=b[sortK];if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;return (x>y?1:x<y?-1:0)*sortD}});
}}
function row(r){{
  const mm=r.manufacturer||r.model?`<span class="mm">${{esc(r.manufacturer||'—')}}${{r.is_obsolete?'<span class="ob">OBSOLETE</span>':''}}<small>${{esc(r.model||'')}}</small></span>`:`<span class="mm" style="color:var(--muted)">not stated${{r.is_obsolete?'<span class="ob">OBSOLETE</span>':''}}</span>`;
  const vendor=r.sole_source_vendor&&(r.sole_source_vendor||'').toLowerCase()!==(r.manufacturer||'').toLowerCase()?`<small style="color:var(--muted)">via ${{esc(r.sole_source_vendor)}}</small>`:'';
  const s=r.supply.length?`<details class="sup"><summary>Who has one: ${{r.supply.length}} for sale</summary><ul>${{r.supply.map(l=>`<li><a href="${{esc(l.url)}}" target="_blank" rel="noopener">${{esc(l.title)}}</a><br><small>${{esc(SRC[l.source]||l.source)}} · ${{l.price!=null?money(l.price):'no price shown'}}${{l.location?' · '+esc(l.location):''}} · seen ${{esc(l.seen_at)}}</small></li>`).join('')}}</ul></details>`:'';
  return `<tr><td>${{mm}}</td><td class="pt" data-l="Part">${{esc(r.part)}}${{r.quantity?` <small style="color:var(--muted)">× ${{esc(r.quantity)}}</small>`:''}}<br>${{vendor}}${{s}}</td><td class="ag" data-l="Agency">${{esc(r.agency)}}, ${{esc(r.state)}}</td><td class="num${{r.price_usd==null?' e':''}}" data-l="Price">${{money(r.price_usd)}}</td><td class="${{r.lead_time?'':'e'}}" data-l="Lead time">${{esc(r.lead_time||'')}}</td><td><div class="reason">“${{esc(r.reason)}}”</div></td><td class="dt" data-l="Date">${{esc(r.date)}}</td><td class="src"><a href="${{esc(r.source_url)}}" target="_blank" rel="noopener">${{/\\.pdf/i.test(r.source_url)?'source PDF':'source notice'}}</a></td></tr>`;
}}
function draw(reset){{
  if(reset)page=1;
  const f=filtered(),show=f.slice(0,page*PAGE);
  rows.innerHTML=show.map(row).join('')||(full?`<tr><td colspan="8" class="empty">Nothing matches. Try fewer words.</td></tr>`:'');
  if(full){{
    const sum=f.reduce((s,r)=>s+(r.price_usd||0),0);
    count.textContent=`${{f.length.toLocaleString()}} of ${{R.length.toLocaleString()}} records${{sum?` · ${{money(sum)}} stated`:''}}`;
    more.hidden=show.length>=f.length;
  }}else{{
    count.textContent=isDefault()?`${{META.n_default.toLocaleString()}} of ${{META.total.toLocaleString()}} records · ${{money(META.sum_default)}} stated`:`Searching all ${{META.total.toLocaleString()}} records…`;
    more.hidden=true;
  }}
  const u=new URL(location);['q','mfr','agency'].forEach((k,i)=>{{const v=[q,mfr,ag][i].value;v?u.searchParams.set(k,v):u.searchParams.delete(k)}});
  obs.checked?u.searchParams.set('obs','1'):u.searchParams.delete('obs');sup.checked?u.searchParams.set('sale','1'):u.searchParams.delete('sale');cls.size?u.searchParams.set('class',[...cls].join('|')):u.searchParams.delete('class');
  history.replaceState(null,'',u);
}}
[q,mfr,ag,obs,soft,sup].forEach(el=>el.addEventListener('input',()=>draw(true)));
document.querySelectorAll('.chip').forEach(b=>b.addEventListener('click',()=>{{const c=b.dataset.c;cls.has(c)?cls.delete(c):cls.add(c);b.setAttribute('aria-pressed',cls.has(c));draw(true)}}));
document.querySelectorAll('th[data-k]').forEach(th=>th.addEventListener('click',()=>{{const k=th.dataset.k;if(sortK===k)sortD=-sortD;else{{sortK=k;sortD=k==='price_usd'||k==='date'?-1:1}}draw(true)}}));
more.addEventListener('click',()=>{{page++;draw(false)}});
// restore state from the URL
const p=new URL(location).searchParams;q.value=p.get('q')||'';mfr.value=p.get('mfr')||'';ag.value=p.get('agency')||'';obs.checked=p.get('obs')==='1';sup.checked=p.get('sale')==='1';
(p.get('class')||'').split('|').filter(Boolean).forEach(c=>{{cls.add(c);const b=document.querySelector(`.chip[data-c="${{c}}"]`);if(b)b.setAttribute('aria-pressed','true')}});
draw(true);
loadAll();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- /open: notices still taking responses

def load_open() -> list[dict]:
    """data/open_notices.jsonl, written by scripts/ingest_sam_open.py (make open). No contracting-officer contact:
    that file never carries it, and the page links to the notice, which does."""
    f = ROOT / "data" / "open_notices.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


def _esc(v) -> str:
    return (str(v if v is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _dealer_chip(d: dict) -> str:
    why = {"catalog": "has this part number", "brand": f"carries {d.get('brand')}",
           "listings": f"{d.get('n')} listings of this maker"}[d["why"]]
    inner = f"<b>{_esc(d['name'])}</b> <small>{_esc(why)}</small>"
    return f'<a class="dl" href="{_esc(d["url"])}">{inner}</a>' if d.get("url") else f'<span class="dl">{inner}</span>'


def _part_li(pt: dict) -> str:
    head = " ".join(_esc(x) for x in (pt.get("manufacturer"), pt.get("model")) if x) or "Maker not named"
    pns = "".join(f"<code>{_esc(x)}</code>" for x in pt.get("part_numbers") or [])
    qty = f' <small>qty {_esc(pt["quantity"])}</small>' if pt.get("quantity") else ""
    dealers = {d["slug"]: d for d in pt.get("dealers") or []}
    sup = "".join(f'<a class="dl" href="{_esc(l["url"])}"><b>{_esc(SOURCE_NAMES.get(l["source"], l["source"]))}</b> <small>listing</small></a>'
                  for l in pt.get("supply") or [])
    chips = sup + "".join(_dealer_chip(d) for d in dealers.values())
    return (f'<li><div class="pm">{head}{qty}</div><div class="pp">{_esc(pt.get("part"))}</div>'
            + (f'<div class="pns">{pns}</div>' if pns else "")
            + (f'<div class="dls">{chips}</div>' if chips else "") + "</li>")


def render_open(rows: list[dict]) -> str:
    n_pn = sum(r["has_part_number"] for r in rows)
    n_dl = sum(r["has_dealer"] for r in rows)
    cards = []
    for r in rows:
        tags = "".join(f'<span class="tag {c}">{t}</span>' for c, t, on in
                       (("pn", "part number printed", r["has_part_number"]), ("dlr", "dealer candidate", r["has_dealer"])) if on)
        cards.append(
            f'<article data-pn="{int(r["has_part_number"])}" data-dl="{int(r["has_dealer"])}" data-end="{_esc(r["deadline"])}">'
            f'<div class="due"><span class="cd"></span> <small>responses due {_esc(r["deadline_date"])}</small></div>'
            f'<h2><a href="{_esc(r["sam_url"])}">{_esc(r["title"])}</a></h2>'
            f'<div class="who">{_esc(r["agency"])}{" · " + _esc(r["office"]) if r.get("office") and r["office"] != r["agency"] else ""} · {_esc(r["type"])}'
            f'{" · " + _esc(r["solicitation"]) if r.get("solicitation") else ""}</div>{tags and f"<div>{tags}</div>"}'
            f'<ul>{"".join(_part_li(p) for p in r["parts"][:3])}</ul>'
            + (f'<details><summary>{len(r["parts"]) - 3} more parts</summary><ul>{"".join(_part_li(p) for p in r["parts"][3:])}</ul></details>'
               if len(r["parts"]) > 3 else "")
            + f'<a class="go" href="{_esc(r["sam_url"])}">Respond through the notice on SAM.gov &rarr;</a></article>')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open sole-source notices</title>
<meta name="description" content="{len(rows)} federal notices of intent to sole-source a physical part that are still taking responses, soonest deadline first.">
<style>
:root{{--ink:#141414;--muted:#6b6b6b;--line:#e3e0da;--bg:#faf9f6;--card:#fff;--accent:#b4451d;--accent-bg:#fbeee6;--ok:#1d6b3a;--ok-bg:#e7f3ea}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}}
header,main,footer{{max-width:860px;margin:0 auto;padding:0 16px}}
header{{padding-top:24px}}
.back{{font-size:13px;color:var(--muted)}}
h1{{font-size:clamp(22px,4.5vw,32px);line-height:1.15;margin:8px 0;letter-spacing:-.01em}}
.lede{{color:var(--muted);margin:0 0 14px;max-width:62ch}}
.lede b{{color:var(--ink)}}
label.tog{{display:inline-flex;gap:6px;align-items:center;padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);cursor:pointer;margin:0 6px 8px 0;font-size:14px}}
article{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:12px 0}}
article[hidden]{{display:none}}
.due{{font-weight:700;color:var(--accent)}}
.due small{{font-weight:400;color:var(--muted)}}
.closed .due{{color:var(--muted)}}
h2{{font-size:17px;line-height:1.3;margin:4px 0}}
h2 a{{color:var(--ink);text-decoration:none}}
.who{{color:var(--muted);font-size:13px;overflow-wrap:anywhere}}
.tag{{display:inline-block;font-size:11px;font-weight:600;padding:2px 7px;border-radius:6px;margin:6px 6px 0 0}}
.tag.pn{{background:var(--accent-bg);color:var(--accent)}}
.tag.dlr{{background:var(--ok-bg);color:var(--ok)}}
ul{{list-style:none;margin:10px 0 0;padding:0}}
li{{border-top:1px dashed var(--line);padding:8px 0}}
.pm{{font-weight:600}}
.pm small{{font-weight:400;color:var(--muted)}}
.pp{{color:var(--muted);font-size:14px}}
.pns code{{display:inline-block;font-size:12px;background:#f3f1ec;border-radius:5px;padding:1px 6px;margin:4px 4px 0 0;overflow-wrap:anywhere;max-width:100%}}
.dls{{margin-top:6px}}
.dl{{display:inline-block;font-size:13px;background:var(--ok-bg);color:var(--ok);border-radius:6px;padding:2px 8px;margin:2px 4px 0 0;text-decoration:none}}
.dl small{{color:var(--ink);opacity:.7}}
details summary{{cursor:pointer;color:var(--accent);font-size:14px;padding:6px 0}}
.go{{display:inline-block;margin-top:10px;font-weight:600;color:var(--accent)}}
.empty{{padding:30px 0;color:var(--muted)}}
footer{{color:var(--muted);font-size:13px;padding-bottom:40px}}
</style>
</head>
<body>
<header>
<a class="back" href="/">&larr; The Google of obsolete infrastructure parts</a>
<h1>Sole-source notices you can still answer</h1>
<p class="lede"><b>{len(rows)} federal buyers</b> have said only one supplier can sell them a physical part, and are still taking responses. <b>{n_pn}</b> print the part number; <b>{n_dl}</b> name a maker a surplus dealer lists. Soonest deadline first.</p>
<label class="tog"><input type="checkbox" id="pn"> Part number printed</label><label class="tog"><input type="checkbox" id="dl"> Dealer candidate</label>
</header>
<main>
{"".join(cards) or '<p class="empty">No open notices today.</p>'}
<p class="empty" id="none" hidden>Nothing matches both filters.</p>
</main>
<footer>SAM.gov notices of intent to sole source, presolicitations, sources sought and brand-name solicitations whose title says sole source, single source, brand name or intent, with a response deadline still ahead, read {date.today().isoformat()} and extracted with Claude. The contracting officer and the way to respond are on each notice. A dealer candidate means the dealer's own catalog lists that maker or that part number; it is not a quote. Regenerated daily by <code>make open</code>.</footer>
<script>
const now=Date.now();
function left(ms){{const h=Math.floor(ms/36e5);return h<48?h+' hours left':Math.floor(h/24)+' days left'}}
document.querySelectorAll('article').forEach(a=>{{const t=Date.parse(a.dataset.end),c=a.querySelector('.cd');
  if(isNaN(t)){{c.textContent='Open'}}else if(t<now){{c.textContent='Closed';a.classList.add('closed')}}else c.textContent=left(t-now)}});
const pn=document.getElementById('pn'),dl=document.getElementById('dl');
function draw(){{let n=0;document.querySelectorAll('article').forEach(a=>{{const h=(pn.checked&&a.dataset.pn!=='1')||(dl.checked&&a.dataset.dl!=='1');a.hidden=h;n+=!h}});document.getElementById('none').hidden=n>0}}
pn.onchange=dl.onchange=draw;
</script>
</body>
</html>
"""


def main():
    recs = load()
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(render(recs))
    (SITE / "data.json").write_text(json.dumps(slim(recs), separators=(",", ":")))
    (SITE / "records.json").write_text(json.dumps(recs, separators=(",", ":")))
    opens = load_open()
    (SITE / "open").mkdir(exist_ok=True)
    (SITE / "open" / "index.html").write_text(render_open(opens))
    print(f"site/open/index.html: {len(opens)} open notices")
    core = {"pump", "valve", "motor/drive", "electrical/switchgear/transformer", "generator"}
    print(f"site/index.html: {len(recs)} records, {len({r['agency'] for r in recs})} agencies, "
          f"{sum(r['is_physical'] for r in recs)} physical, "
          f"{sum(r['equipment_class'] in core for r in recs)} pump/valve/motor/electrical/generator, "
          f"index.html {(SITE / 'index.html').stat().st_size // 1024} KB, data.json {(SITE / 'data.json').stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
