#!/usr/bin/env python3
"""Generate site/index.html (and site/records.json) from data/records.jsonl.

The page is static: every record is embedded as JSON and searched in the
browser. This file is the only source of the HTML — never hand-edit the output.
"""
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
TITLE = "The Google of obsolete infrastructure parts"

FIELDS = ["id", "manufacturer", "model", "part", "quantity", "price_usd", "lead_time", "sole_source_vendor", "reason",
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


def load():
    recs = [json.loads(l) for l in (ROOT / "data" / "records.jsonl").read_text().splitlines() if l.strip()]
    out = [{k: r.get(k) for k in FIELDS} for r in recs]
    for r in out:
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


def render(recs: list[dict]) -> str:
    agencies = sorted({r["agency"] for r in recs})
    n_hw = sum(1 for r in recs if r["is_physical"])
    n_soft = len(recs) - n_hw
    classes = [c for c, _ in Counter(r["equipment_class"] for r in recs).most_common()]
    classes = [c for c in classes if c not in SOFT] + [c for c in classes if c in SOFT]
    n_mfr = len({(r["manufacturer"] or "").lower() for r in recs if r["manufacturer"]})
    n_price = sum(1 for r in recs if r["price_usd"])
    dates = sorted(r["date"] for r in recs if r["date"])
    data = json.dumps(recs, separators=(",", ":")).replace("</", "<\\/")
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
.more{{display:block;margin:18px auto;font:inherit;padding:10px 18px;border-radius:10px;border:1px solid var(--line);background:var(--card);cursor:pointer}}
.empty{{padding:40px 16px;text-align:center;color:var(--muted)}}
footer{{max-width:1280px;margin:0 auto;padding:0 16px 40px;color:var(--muted);font-size:13px}}
@media (max-width:900px){{
  header{{padding-top:18px}}
  .lede{{font-size:14px;margin-bottom:12px}}
  .controls{{gap:6px}}
  select{{flex:1 1 40%;min-width:0;padding:8px 10px;font-size:14px}}
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
<p class="lede"><b>{n_hw:,} pieces of physical equipment</b> that <b>{len(agencies)} public agencies</b> could buy from only one supplier, {span(dates)}. Each row quotes the agency's own reason and links to the source document.</p>
<div class="controls">
  <input id="q" type="search" placeholder="Search manufacturer, model, part, vendor, agency…" autocomplete="off" autofocus>
  <select id="mfr"><option value="">All manufacturers</option></select>
  <select id="agency"><option value="">All agencies</option>{''.join(f'<option>{a}</option>' for a in agencies)}</select>
  <label class="tog"><input type="checkbox" id="obs"> Obsolete / discontinued only</label>
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
<footer>Built from the Legistar public API (sole-source, single-source, proprietary and obsolete-equipment matters introduced since 2024-01-01), extracted with Claude, never typed by hand. A field is blank when the agency's document did not state it. Regenerated {date.today().isoformat()}.</footer>
<script id="data" type="application/json">{data}</script>
<script>
const R=JSON.parse(document.getElementById('data').textContent);
const $=s=>document.querySelector(s);
const q=$('#q'),mfr=$('#mfr'),ag=$('#agency'),obs=$('#obs'),soft=$('#soft'),rows=$('#rows'),count=$('#count'),more=$('#more');
const SOFT=new Set({json.dumps(SOFT)});
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
const money=v=>v==null?'':'$'+Math.round(v).toLocaleString();
let cls=new Set(),sortK='price_usd',sortD=-1,page=1;const PAGE=100;
// manufacturers, most frequent first
const mc={{}};R.forEach(r=>{{if(r.manufacturer)mc[r.manufacturer]=(mc[r.manufacturer]||0)+1}});
Object.entries(mc).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).forEach(([m,n])=>{{const o=document.createElement('option');o.value=m;o.textContent=`${{m}} (${{n}})`;mfr.append(o)}});
R.forEach(r=>r._h=[r.manufacturer,r.model,r.part,r.sole_source_vendor,r.agency,r.state,r.reason,r.installed_location,r.equipment_class].join(' ').toLowerCase());
function filtered(){{
  const terms=q.value.toLowerCase().split(/\\s+/).filter(Boolean);
  return R.filter(r=>(!mfr.value||r.manufacturer===mfr.value)&&(!ag.value||r.agency===ag.value)&&(!obs.checked||r.is_obsolete)&&(cls.size?cls.has(r.equipment_class):(soft.checked||r.is_physical))&&terms.every(t=>r._h.includes(t)))
    .sort((a,b)=>{{const x=a[sortK],y=b[sortK];if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;return (x>y?1:x<y?-1:0)*sortD}});
}}
function row(r){{
  const mm=r.manufacturer||r.model?`<span class="mm">${{esc(r.manufacturer||'—')}}${{r.is_obsolete?'<span class="ob">OBSOLETE</span>':''}}<small>${{esc(r.model||'')}}</small></span>`:`<span class="mm" style="color:var(--muted)">not stated${{r.is_obsolete?'<span class="ob">OBSOLETE</span>':''}}</span>`;
  const vendor=r.sole_source_vendor&&(r.sole_source_vendor||'').toLowerCase()!==(r.manufacturer||'').toLowerCase()?`<small style="color:var(--muted)">via ${{esc(r.sole_source_vendor)}}</small>`:'';
  return `<tr><td>${{mm}}</td><td class="pt" data-l="Part">${{esc(r.part)}}${{r.quantity?` <small style="color:var(--muted)">× ${{esc(r.quantity)}}</small>`:''}}<br>${{vendor}}</td><td class="ag" data-l="Agency">${{esc(r.agency)}}, ${{esc(r.state)}}</td><td class="num${{r.price_usd==null?' e':''}}" data-l="Price">${{money(r.price_usd)}}</td><td class="${{r.lead_time?'':'e'}}" data-l="Lead time">${{esc(r.lead_time||'')}}</td><td><div class="reason">“${{esc(r.reason)}}”</div></td><td class="dt" data-l="Date">${{esc(r.date)}}</td><td class="src"><a href="${{esc(r.source_url)}}" target="_blank" rel="noopener">source PDF</a></td></tr>`;
}}
function draw(reset){{
  if(reset)page=1;
  const f=filtered(),show=f.slice(0,page*PAGE);
  rows.innerHTML=show.map(row).join('')||`<tr><td colspan="8" class="empty">Nothing matches. Try fewer words.</td></tr>`;
  const sum=f.reduce((s,r)=>s+(r.price_usd||0),0);
  count.textContent=`${{f.length.toLocaleString()}} of ${{R.length.toLocaleString()}} records${{sum?` · ${{money(sum)}} stated`:''}}`;
  more.hidden=show.length>=f.length;
  const u=new URL(location);['q','mfr','agency'].forEach((k,i)=>{{const v=[q,mfr,ag][i].value;v?u.searchParams.set(k,v):u.searchParams.delete(k)}});
  obs.checked?u.searchParams.set('obs','1'):u.searchParams.delete('obs');cls.size?u.searchParams.set('class',[...cls].join('|')):u.searchParams.delete('class');
  history.replaceState(null,'',u);
}}
[q,mfr,ag,obs,soft].forEach(el=>el.addEventListener('input',()=>draw(true)));
document.querySelectorAll('.chip').forEach(b=>b.addEventListener('click',()=>{{const c=b.dataset.c;cls.has(c)?cls.delete(c):cls.add(c);b.setAttribute('aria-pressed',cls.has(c));draw(true)}}));
document.querySelectorAll('th[data-k]').forEach(th=>th.addEventListener('click',()=>{{const k=th.dataset.k;if(sortK===k)sortD=-sortD;else{{sortK=k;sortD=k==='price_usd'||k==='date'?-1:1}}draw(true)}}));
more.addEventListener('click',()=>{{page++;draw(false)}});
// restore state from the URL
const p=new URL(location).searchParams;q.value=p.get('q')||'';mfr.value=p.get('mfr')||'';ag.value=p.get('agency')||'';obs.checked=p.get('obs')==='1';
(p.get('class')||'').split('|').filter(Boolean).forEach(c=>{{cls.add(c);const b=document.querySelector(`.chip[data-c="${{c}}"]`);if(b)b.setAttribute('aria-pressed','true')}});
draw(true);
</script>
</body>
</html>
"""


def main():
    recs = load()
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(render(recs))
    (SITE / "records.json").write_text(json.dumps(recs, indent=0))
    print(f"site/index.html: {len(recs)} records, {len({r['agency'] for r in recs})} agencies, "
          f"{(SITE / 'index.html').stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
