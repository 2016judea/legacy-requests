#!/usr/bin/env python3
"""/dates: the OEM's legacy date, before any agency files an RFP.

A water utility's Chief of Operations, 2026-09-08: "If we know that the OEM has a
legacy date, we buy items in advance." So demand starts at the OEM's notice, not at
the RFP. This page lists those notices for the gear water and wastewater agencies run,
soonest order-by date first, each row citing the maker's own words, and joins each
one to the agencies whose filings say they run that family. DATA_MODEL.md has the model.

Inputs (all cached, $0 to rebuild):
  data/eol/rockwell/*.json      scripts/eol_rockwell.py  (Rockwell's public lifecycle search)
  data/eol/notices_manual.json  hand-read notices from Siemens, Schneider, ABB, Hach, Yaskawa, Rockwell
  data/eol/cache/*.txt          scripts/eol_fetch.py     (every manual quote is checked against this)
  data/eol/installs.json        scripts/eol_installs.py  (agencies whose filings name the family)
Outputs: data/eol/notices.json, site/dates/index.html
"""
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from eol_families import FAMILIES  # noqa: E402
from eol_fetch import fetch  # noqa: E402

TODAY = date.today()
RECENT = (TODAY - timedelta(days=730)).isoformat()  # "just discontinued" = within two years
LIFECYCLE = "https://www.rockwellautomation.com/en-us/support/product/product-compatibility-migration/product-lifecycle-status.html"
FAM = {f[0]: {"oem": f[1], "name": f[2], "rx": re.compile(f[3], re.I)} for f in FAMILIES}

# Rockwell bulletin -> (family id for the join, the name on the cabinet door)
BULLETINS = [
    (r"^20A", "ab-pf70-700", "PowerFlex 70 drives"), (r"^20B", "ab-pf70-700", "PowerFlex 700 drives"),
    (r"^22A", "ab-pf4-40", "PowerFlex 4 drives"), (r"^22B", "ab-pf4-40", "PowerFlex 40 drives"),
    (r"^22C", "ab-pf4-40", "PowerFlex 400 drives"), (r"^1336", "ab-1336", "1336 drives"),
    (r"^1785-", "ab-plc5", "PLC-5 controllers"), (r"^1771-", "ab-plc5", "PLC-5 1771 I/O"),
    (r"^1747-", "ab-slc500", "SLC 500 controllers and modules"), (r"^1746-", "ab-slc500", "SLC 500 I/O"),
    (r"^1761-", "ab-micrologix", "MicroLogix 1000"), (r"^1762-", "ab-micrologix", "MicroLogix 1200"),
    (r"^1763-", "ab-micrologix", "MicroLogix 1100"), (r"^1764-", "ab-micrologix", "MicroLogix 1500"),
    (r"^1766-", "ab-micrologix", "MicroLogix 1400"), (r"^1756-", "ab-controllogix", "ControlLogix"),
    (r"^1769-", "ab-compactlogix", "CompactLogix"), (r"^1794-", "ab-flexio", "FLEX I/O"),
    (r"^2711P", "ab-panelview", "PanelView Plus"), (r"^2711-", "ab-panelview", "PanelView Standard"),
    (r"^(150-|1503E)", "ab-smc", "SMC soft starters"), (r"^1485", "ab-devicenet", "DeviceNet cable and media"),
]
CATEGORY = {"Direct_Replacement": "Drop-in", "Functional_Replacement": "Same function, check fit",
            "Engineering_Replacement": "Engineering project", "No_planned_RA_replacement": "No replacement planned"}


def _esc(v) -> str:
    return str(v if v is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("–", "-").replace("—", "-").replace("®", "").replace("™", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def rockwell_rows() -> list[dict]:
    docs = {}
    for f in sorted((ROOT / "data/eol/rockwell").glob("*.json")):
        d = json.loads(f.read_text())
        for x in d["docs"]:
            x["_fetched"] = d.get("fetched")
            docs[x["catalogNumber"]] = x
    groups, active = defaultdict(list), defaultdict(int)
    for x in docs.values():
        if x.get("productLifeCycleStatus") in ("ACTIVE", "ACTIVE_MATURE"):
            b = next((label for rx, _, label in BULLETINS if re.match(rx, x["catalogNumber"])), None)
            if b:
                active[b] += 1
        st, dd = x.get("productLifeCycleStatus"), (x.get("discontinuedDate") or "")[:10]
        if st == "END_OF_LIFE" and dd >= TODAY.isoformat():
            status = "eol"
        elif st == "DISCONTINUED" and dd >= RECENT:
            status = "discontinued"
        else:
            continue
        hit = next(((fid, label) for rx, fid, label in BULLETINS if re.match(rx, x["catalogNumber"])), None)
        if not hit:
            continue
        groups[(hit[0], hit[1], status, dd)].append(x)
    rows = []
    for (fid, label, status, dd), xs in groups.items():
        xs.sort(key=lambda x: x["catalogNumber"])
        reps = defaultdict(int)
        for x in xs:
            rt = (x.get("replacementText") or "").strip()
            # a catalog-like replacement only: the field also carries notes ("Spare Part for Disc Drive", "Migrate to ...")
            if rt and re.search(r"\d", rt) and not re.search(r"spare|migrate|not applicable", rt, re.I):
                reps[x["replacementText"].strip()] += 1
        cats = defaultdict(int)
        for x in xs:
            cats[CATEGORY.get(x.get("replacementCategory") or "", "")] += 1
        kind = max(cats, key=cats.get) if cats else ""
        titles = defaultdict(int)
        for x in xs:
            titles[re.sub(r"\s+", " ", x.get("title") or "").strip()] += 1
        rows.append({
            "oem": "Rockwell / Allen-Bradley", "family": fid, "label": label, "status": status, "legacy_date": dd,
            "support_until": "", "successor": ", ".join(sorted(reps, key=reps.get, reverse=True)[:3]),
            "successor_kind": kind, "catalogs": [x["catalogNumber"] for x in xs],
            "what": [t for t, _ in sorted(titles.items(), key=lambda kv: -kv[1])[:3]],
            "url": f"{LIFECYCLE}?keyword={quote(xs[0]['catalogNumber'])}",
            "source": "Rockwell Product Lifecycle Status",
            "quote": f"{xs[0]['catalogNumber']} · {'End of Life' if status == 'eol' else 'Discontinued'} · discontinued date {dd}"
                     + (f" · replacement {xs[0]['replacementText']}" if xs[0].get("replacementText") else ""),
            "fetched": xs[0].get("_fetched"),
            "still_sold": active.get(label, 0),
        })
    return rows


def manual_rows() -> list[dict]:
    rows, bad = [], []
    for n in json.loads((ROOT / "data/eol/notices_manual.json").read_text()):
        text = fetch(n["url"])
        if _norm(n["quote"]) not in _norm(text):
            bad.append(n["url"])
            continue
        rows.append({**n, "catalogs": [], "what": [], "source": n["oem"] + " notice", "fetched": TODAY.isoformat()})
    for u in bad:
        print(f"  DROPPED (quote not on page): {u}")
    return rows


def asks_for(fid: str, recs: list[dict]) -> int:
    rx = FAM[fid]["rx"]
    return sum(1 for r in recs if rx.search(" ".join(str(r.get(k) or "") for k in ("manufacturer", "model", "part", "part_numbers"))))


def build() -> list[dict]:
    recs = [json.loads(l) for l in open(ROOT / "data/records.jsonl")]
    installs = defaultdict(list)
    for i in json.loads((ROOT / "data/eol/installs.json").read_text()):
        installs[i["family"]].append(i)
    rows = rockwell_rows() + manual_rows()
    for r in rows:
        r["installs"] = installs.get(r["family"], [])
        r["asks"] = asks_for(r["family"], recs)
        r["ask_q"] = FAM[r["family"]]["name"].split(" (")[0].split(" / ")[0]
        r["days_left"] = (date.fromisoformat(r["legacy_date"]) - TODAY).days if r["legacy_date"] else None
    order = {"eol": 0, "discontinued": 1, "successor": 2}
    rows.sort(key=lambda r: (order[r["status"]],
                             (r["legacy_date"] or "0000") if r["status"] == "eol" else "",
                             "" if r["status"] == "eol" else "".join(chr(255 - ord(c)) for c in (r["legacy_date"] or "0000")),
                             -len(r["installs"]), -len(r["catalogs"])))
    (ROOT / "data/eol/notices.json").write_text(json.dumps(rows, indent=1))
    return rows


def fmt(d: str) -> str:
    return date.fromisoformat(d).strftime("%b %-d, %Y") if d else ""


def head(r: dict) -> str:
    if r["status"] == "eol":
        return f'Order by {fmt(r["legacy_date"])} <small>{r["days_left"]:,} days left</small>'
    if r["status"] == "discontinued":
        return f'Stopped selling {fmt(r["legacy_date"])}' if r["legacy_date"] else "No longer sold new"
    return "Successor named"


def card(r: dict) -> str:
    hay = " ".join([r["label"], r["oem"], r["successor"], *r["catalogs"], *r["what"], FAM[r["family"]]["name"]]).lower()
    cats = r["catalogs"]
    cat_html = ""
    if cats:
        shown = "".join(f"<code>{_esc(c)}</code>" for c in cats[:6])
        more = (f'<details><summary>+{len(cats) - 6} more catalog numbers</summary><div class="pns">'
                + "".join(f"<code>{_esc(c)}</code>" for c in cats[6:200]) + "</div></details>") if len(cats) > 6 else ""
        cat_html = f'<div class="pns">{shown}</div>{more}'
    what = f'<div class="pp">{_esc(" · ".join(r["what"]))}</div>' if r["what"] else ""
    succ = (f'<div class="rep"><b>Replace with</b> {_esc(r["successor"])}'
            + (f' <small>{_esc(r["successor_kind"])}</small>' if r["successor_kind"] else "") + "</div>") if r["successor"] else (
        f'<div class="rep"><b>Replacement</b> <small>{_esc(r["successor_kind"])}</small></div>' if r["successor_kind"] else "")
    sup = f'<div class="pp">Support: {_esc(r["support_until"])}</div>' if r.get("support_until") else ""
    ins = ""
    if r["installs"]:
        lis = "".join(
            f'<li><b>{_esc(i["agency"])}</b>{", " + _esc(i["state"]) if i.get("state") else ""}'
            f'<q>{_esc(i["cites"][0]["quote"][:180])}</q>'
            f'<a href="{_esc(i["cites"][0]["url"])}" target="_blank" rel="noopener">their filing, {_esc(i["cites"][0]["date"])} &rarr;</a></li>'
            for i in r["installs"][:4])
        ins = (f'<div class="ins"><b>On record running {_esc(FAM[r["family"]]["name"])}</b><ul>{lis}</ul>'
               + (f'<small>+{len(r["installs"]) - 4} more agencies</small>' if len(r["installs"]) > 4 else "") + "</div>")
    asks = (f'<a class="asks" href="/?q={quote(r["ask_q"])}#index">{r["asks"]} ask{"s" if r["asks"] != 1 else ""} for {_esc(r["ask_q"])} already filed &rarr;</a>'
            if r["asks"] else "")
    src = (f'<div class="src"><q>{_esc(r["quote"])}</q> <a href="{_esc(r["url"])}" target="_blank" rel="noopener">{_esc(r["source"])} &#8599;</a></div>')
    return (f'<article class="{r["status"]}" data-s="{r["status"]}" data-h="{_esc(hay)}">'
            f'<div class="due">{head(r)}</div>'
            f'<h2>{_esc(r["label"])}</h2><div class="who">{_esc(r["oem"])}'
            f'{" · " + str(len(cats)) + " catalog number" + ("s" if len(cats) != 1 else "") if cats else ""}'
            f'{" · " + format(r["still_sold"], ",") + " others in this line still sold" if r.get("still_sold") else ""}</div>'
            f'{what}{cat_html}{succ}{sup}{ins}{asks}{src}</article>')


def render(rows: list[dict], va_tag: str, title: str) -> str:
    n_eol = sum(r["status"] == "eol" for r in rows)
    n_cat = sum(len(r["catalogs"]) for r in rows if r["status"] == "eol")
    n_ag = len({i["agency"] for r in rows for i in r["installs"]})
    oems = sorted({r["oem"].split()[0] for r in rows})
    example = "PowerFlex 70"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Legacy dates</title>
<meta name="description" content="The date the maker stops selling it, for the drives, PLCs and analyzers water agencies run. Every row cites the maker's own notice.">
<style>
:root{{--ink:#141414;--muted:#6b6b6b;--line:#e3e0da;--bg:#faf9f6;--card:#fff;--accent:#b4451d;--accent-bg:#fbeee6;--ok:#1d6b3a;--ok-bg:#e7f3ea}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}}
header,main,footer{{max-width:860px;margin:0 auto;padding:0 16px}}
header{{padding-top:24px}}
.back{{font-size:13px;color:var(--muted)}}
h1{{font-size:clamp(26px,5.5vw,40px);line-height:1.1;margin:8px 0;letter-spacing:-.02em}}
.lede{{color:var(--muted);margin:0 0 14px;max-width:62ch;font-size:17px}}
.lede b{{color:var(--ink)}}
input[type=search]{{display:block;width:100%;font:inherit;font-size:18px;padding:14px 16px;border:2px solid var(--ink);border-radius:12px;background:var(--card);min-width:0}}
input[type=search]:focus{{outline:2px solid var(--accent);outline-offset:1px}}
.hint{{color:var(--muted);font-size:14px;margin:10px 0 0}}
.chips{{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 0}}
.chip{{font:inherit;font-size:13px;padding:6px 10px;border-radius:999px;border:1px solid var(--line);background:var(--card);cursor:pointer;color:var(--ink)}}
.chip[aria-pressed=true]{{background:var(--ink);color:#fff;border-color:var(--ink)}}
.count{{color:var(--muted);font-size:13px;margin:14px 0 0}}
.count button{{font:inherit;color:var(--accent);background:none;border:0;padding:0;cursor:pointer;text-decoration:underline}}
article{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:12px 0}}
article[hidden]{{display:none}}
.due{{font-weight:700;color:var(--accent);font-size:17px}}
.due small{{font-weight:600;color:var(--ink);background:var(--accent-bg);border-radius:6px;padding:1px 7px;margin-left:6px;font-size:13px}}
.discontinued .due,.successor .due{{color:var(--muted)}}
h2{{font-size:19px;line-height:1.25;margin:4px 0 2px}}
.who{{color:var(--muted);font-size:13px}}
.pp{{color:var(--muted);font-size:14px;margin-top:6px}}
.pns code{{display:inline-block;font:600 12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--accent-bg);color:var(--accent);border-radius:5px;padding:1px 6px;margin:6px 4px 0 0;overflow-wrap:anywhere;max-width:100%}}
details summary{{cursor:pointer;color:var(--accent);font-size:14px;padding:6px 0}}
.rep{{margin-top:10px;font-size:15px}}
.rep b,.ins>b{{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}}
.rep small{{display:inline-block;font-size:12px;font-weight:600;background:var(--ok-bg);color:var(--ok);border-radius:6px;padding:1px 7px;margin-left:4px}}
.ins{{margin-top:12px}}
.ins ul{{list-style:none;margin:4px 0 0;padding:0}}
.ins li{{border-top:1px dashed var(--line);padding:6px 0}}
.ins q{{display:block;color:var(--muted);font-size:14px;font-style:italic;margin:2px 0}}
.ins a{{font-size:13px}}
.ins small{{color:var(--muted)}}
.asks{{display:inline-block;margin-top:10px;font-weight:600}}
.src{{margin-top:12px;padding-top:10px;border-top:1px solid var(--line);font-size:13px;color:var(--muted);overflow-wrap:anywhere}}
.src q{{font-style:italic}}
.src a{{font-weight:600;white-space:nowrap}}
a{{color:var(--accent)}}
.empty{{padding:30px 0;color:var(--muted)}}
footer{{color:var(--muted);font-size:13px;padding-bottom:40px}}
@media (max-width:900px){{
  /* 16px inputs (iOS zoom) and 44px targets on the phone (mobile-ui-audit 2026-10-04/06) */
  input[type=search]{{font-size:16px;padding:14px}}
  .back{{display:inline-flex;align-items:center;min-height:44px}}
  .chips{{flex-wrap:nowrap;overflow-x:auto;margin:10px -16px 0;padding:0 16px 6px;scrollbar-width:none}}
  .chips::-webkit-scrollbar{{display:none}}
  .chip{{white-space:nowrap;min-height:44px;padding:8px 14px;font-size:14px}}
  .hint a{{display:inline-block;padding:12px 4px;margin:-12px 0}}
  .count button{{min-height:44px}}
  details summary{{display:flex;align-items:center;min-height:44px}}
  .asks,.ins a,.src a{{display:inline-flex;align-items:center;min-height:44px}}
}}
</style>
{va_tag}
</head>
<body>
<header>
<a class="back" href="/">&larr; {title}</a>
<h1>Buy it before they stop making it.</h1>
<p class="lede">The date the maker stops selling it. <b>{n_eol} last-time buys are open now</b>, {n_cat:,} catalog numbers, for the drives, PLCs and analyzers water agencies run. Each row quotes the maker.</p>
<input id="q" type="search" value="{example}" placeholder="Make, model or catalog number" autocomplete="off" enterkeyhint="search" aria-label="Make, model or catalog number">
<p class="hint">Try <a href="?q=S7">Siemens S7</a> · <a href="?q=SLC">SLC 500</a> · <a href="?q=CL17">Hach CL17</a> · <a href="?q=ACQ550">ABB ACQ550</a></p>
<div class="chips"><button class="chip" data-f="eol" aria-pressed="false">Last-time buy open {n_eol}</button><button class="chip" data-f="discontinued" aria-pressed="false">Stopped selling {sum(r["status"] == "discontinued" for r in rows)}</button><button class="chip" data-f="ins" aria-pressed="false">Agencies on record {sum(bool(r["installs"]) for r in rows)}</button></div>
<div class="count" id="count"></div>
</header>
<main>
{"".join(card(r) for r in rows)}
<p class="empty" id="none" hidden>No notice matches. Try the family name on the cabinet door, or a catalog number.</p>
</main>
<footer>Rockwell rows come from Rockwell Automation's public Product Lifecycle Status search, one row per product line and discontinued date; only the catalog numbers listed on a row are ending, and the link opens Rockwell's own answer for that catalog number. Other rows quote the maker's notice word for word, and a quote is checked against the page before it ships. "On record running" means that agency's own filing names the product family; it does not mean the agency runs the exact catalog numbers above. {len(oems)} makers, {n_ag} agencies on record. Read {TODAY.isoformat()}.</footer>
<script>
const q=document.getElementById('q'),arts=[...document.querySelectorAll('article')],cnt=document.getElementById('count');
let f='';
const p=new URLSearchParams(location.search);if(p.has('q'))q.value=p.get('q');
function draw(){{const t=q.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);let n=0;
  arts.forEach(a=>{{const h=a.dataset.h;let ok=t.every(w=>h.includes(w));
    if(f==='ins')ok=ok&&!!a.querySelector('.ins');else if(f)ok=ok&&a.dataset.s===f;a.hidden=!ok;n+=ok}});
  document.getElementById('none').hidden=n>0;
  cnt.innerHTML=(t.length||f)?`${{n}} of ${{arts.length}} notices <button id="all">Show all</button>`:`${{arts.length}} notices, soonest order-by date first`;
  const b=document.getElementById('all');if(b)b.onclick=()=>{{q.value='';f='';document.querySelectorAll('.chip').forEach(c=>c.setAttribute('aria-pressed','false'));draw()}};}}
q.addEventListener('input',draw);
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{{const on=c.getAttribute('aria-pressed')!=='true';document.querySelectorAll('.chip').forEach(x=>x.setAttribute('aria-pressed','false'));c.setAttribute('aria-pressed',on);f=on?c.dataset.f:'';draw()}});
draw();
</script>
</body>
</html>
"""


def main(va_tag: str, title: str) -> list[dict]:
    rows = build()
    out = ROOT / "site/dates"
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render(rows, va_tag, title))
    print(f"site/dates/index.html: {len(rows)} notices, {sum(r['status'] == 'eol' for r in rows)} last-time buys open, "
          f"{sum(bool(r['installs']) for r in rows)} with agencies on record")
    return rows


if __name__ == "__main__":
    from build_site import VA_TAG, TITLE
    main(VA_TAG, TITLE)
