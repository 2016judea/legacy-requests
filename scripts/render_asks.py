"""HTML for /asks/ (the free page + the unlock) and /for/<token>/ (one recipient's own ask).

Called by scripts/build_asks.py. Never hand-edit the output. Pay flow copied from
~/Desktop/msp-house-index (site/index.html "The gate"): Stripe embedded Checkout via
/api/checkout, password emailed by the webhook, rows from /api/data with x-password.
Funnel events (va.track AND posthog.capture): preview_open, checkout_open, paid, unlock.
"""
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
POSTHOG = (HERE / "posthog.html").read_text()
VA = ('<script>window.va=window.va||function(){(window.vaq=window.vaq||[]).push(arguments)};</script>'
      '<script defer src="/_vercel/insights/script.js"></script>')
PK = "pk_live_51TUvvcBzD4mN8eOD28H6oQkFwFHwF1SLtWxN1vHRmnSxntWFefgd33mEIVmjv8ekxWgkZft3OpPlzmVXMIeHPBwj003998hjTf"


def esc(v) -> str:
    return (str(v if v is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def money(v) -> str:
    if v is None:
        return ""
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"


def nice_date(iso) -> str:
    return date.fromisoformat(iso).strftime("%b %-d") if iso else ""


CSS = """
:root{--ink:#141414;--muted:#6b6b6b;--line:#e3e0da;--bg:#faf9f6;--card:#fff;--accent:#b4451d;--accent-bg:#fbeee6;--ok:#1d6b3a;--ok-bg:#e7f3ea;--lock:#efece6}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.w{max-width:760px;margin:0 auto;padding:0 16px}
.back{display:inline-flex;align-items:center;min-height:44px;font-size:14px;color:var(--muted)}
h1{font-size:clamp(28px,6.4vw,44px);line-height:1.08;margin:6px 0 12px;letter-spacing:-.02em}
.lede{color:var(--muted);font-size:18px;margin:0 0 18px;max-width:54ch}
.lede b{color:var(--ink)}
input[type=search]{display:block;width:100%;font:inherit;font-size:18px;padding:14px 16px;border:2px solid var(--ink);border-radius:12px;background:var(--card);min-width:0}
input[type=search]:focus{outline:2px solid var(--accent);outline-offset:1px}
.hint{color:var(--muted);font-size:14px;margin:8px 0 0}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 0}
.chip{font:inherit;font-size:14px;min-height:40px;padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:var(--card);cursor:pointer;color:var(--ink)}
.count{margin:22px 0 8px;font-size:15px;color:var(--muted)}
.count b{color:var(--ink)}
.ask{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0}
.ask .pt{font-weight:650;font-size:17px}
.ask .mk{color:var(--muted);font-size:14px;margin-top:2px;overflow-wrap:anywhere}
.ask code{font:600 13px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--accent-bg);color:var(--accent);border-radius:5px;padding:1px 6px;overflow-wrap:anywhere}
.ask .kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 14px;margin-top:10px;font-size:14px}
.ask .kv div span{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.ask .kv b{font-weight:600;overflow-wrap:anywhere}
.ask .paid b{color:var(--accent)}
.lockd{margin-top:10px;display:flex;flex-wrap:wrap;gap:6px}
.lockd span{font-size:13px;background:var(--lock);color:var(--muted);border-radius:6px;padding:3px 8px}
.lockd span::before{content:"\\1F512\\FE0E ";font-size:11px}
.sale{display:inline-block;margin-top:8px;font-size:13px;font-weight:600;color:var(--ok);background:var(--ok-bg);border-radius:6px;padding:2px 8px;text-decoration:none}
.go{display:inline-flex;align-items:center;min-height:44px;margin-top:4px;font-weight:600;color:var(--accent)}
.mine{border:2px solid var(--accent)}
.mine .tag{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--accent);margin-bottom:4px}
.rec{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:0 0 6px}
.rec span{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.rec a{font-weight:600;overflow-wrap:anywhere}
h2{font-size:clamp(21px,4.4vw,28px);line-height:1.15;margin:30px 0 6px;letter-spacing:-.01em}
.sub{color:var(--muted);margin:0 0 10px}
.pay{margin:26px 0 8px;border-radius:14px;background:var(--ink);color:var(--bg);padding:22px 18px 20px}
.pay h2{margin:0 0 6px;font-size:clamp(22px,5vw,30px);color:var(--bg)}
.pay p{margin:0 0 14px;opacity:.8}
.pay-act{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.pay-btn{font:600 16px/1.25 inherit;font-family:inherit;padding:15px 20px;border-radius:10px;border:1.5px solid var(--bg);background:var(--bg);color:var(--ink);cursor:pointer;min-height:54px;flex:1 1 220px}
.pay-btn.alt{background:transparent;color:var(--bg);flex:1 1 220px}
.pay-btn[disabled]{opacity:.6}
.pwf{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.pwf input{flex:1 1 200px;min-width:0;font:500 16px ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;padding:12px;border-radius:9px;border:1px solid #777;background:#222;color:#fff}
.pwf button{font:600 16px inherit;font-family:inherit;min-height:48px;padding:11px 18px;border-radius:9px;border:1px solid var(--bg);background:transparent;color:var(--bg);cursor:pointer}
.pwerr{flex-basis:100%;margin:4px 0 0;color:#ffb39a;font-size:14px;min-height:0}
.pay-co{margin-top:16px;border-radius:12px;overflow:hidden;background:#fff}
.pay-co:empty{display:none}
.paidbox{margin:20px 0;border:1px solid var(--line);background:var(--card);border-radius:14px;padding:18px}
.paidbox .pwf input{background:var(--bg);color:var(--ink);border-color:var(--line)}
.paidbox .pwf button{color:var(--ink);border-color:var(--ink)}
.paidbox .pwerr{color:var(--accent)}
.unl{display:inline-block;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--ok);background:var(--ok-bg);border-radius:6px;padding:2px 8px;margin-right:6px}
.dl{display:inline-flex;align-items:center;min-height:44px;font-weight:600;color:var(--accent);background:none;border:0;font:inherit;font-weight:600;cursor:pointer;padding:0}
footer{color:var(--muted);font-size:13px;padding:30px 0 50px}
.sr{position:absolute;left:-9999px}
@media (min-width:900px){.w{max-width:860px}.pay{padding:30px 36px}}
"""

PAY = """
<section class="paidbox" id="paid" hidden aria-live="polite"><h2 id="paidH" style="margin-top:0">Confirming your payment…</h2><p id="paidP" class="sub"></p>
<form class="pwf" hidden><label class="sr" for="pw2">Password</label><input id="pw2" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="XXXX-XXXX-XXXX"><button>Open the full list</button><p class="pwerr" role="alert"></p></form></section>
<section class="pay" id="pay">
<h2>All {n} open asks, ${price} once.</h2>
<p>Every part number they will accept, the date quotes are due, and the buyer's name, email and phone. Your password comes by email.</p>
<div class="pay-act"><button type="button" class="pay-btn" id="buy">Get the full list, ${price}</button>
<button type="button" class="pay-btn alt" id="havepw" aria-expanded="false">Already paid? Enter your password</button></div>
<form class="pwf" id="pwf" hidden><label class="sr" for="pw1">Password</label><input id="pw1" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="XXXX-XXXX-XXXX"><button>Open the full list</button><p class="pwerr" role="alert"></p></form>
<div class="pay-co" id="checkout"></div>
</section>
"""

JS_COMMON = """
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"})[c]);
function track(name,data){data=data||{};try{window.va("event",{name,data})}catch(e){}try{window.posthog&&posthog.capture&&posthog.capture(name,data)}catch(e){}}
const money=v=>v==null?"":(v>=100?"$"+Math.round(v).toLocaleString():"$"+v.toFixed(2));
const day=s=>s?new Date(s+"T12:00").toLocaleDateString("en-US",{month:"short",day:"numeric"}):"";
const left=s=>{if(!s)return"";const d=Math.round((new Date(s+"T23:59")-Date.now())/864e5);return d<=0?"due today":d===1?"1 day left":d+" days left"};
const PK=__PK__;
const store={get:()=>{try{return localStorage.getItem("lr_pw")}catch(e){return null}},set:v=>{try{v?localStorage.setItem("lr_pw",v):localStorage.removeItem("lr_pw")}catch(e){}}};
const BAD="That password didn't match. Check the email from Brick & Mortar, or reply to it for help.";
function lockedRow(r){
 const pn=r.pn?`<code>${esc(r.pn)}</code> `:"";
 return `<article class="ask"><div class="pt">${esc(r.part||"Part")}</div><div class="mk">${pn}${esc(r.maker||"")}${r.n_approved>1?` · ${r.n_approved} part numbers accepted`:""}</div>
 <div class="kv"><div><span>Qty</span><b>${esc(r.qty??"")} ${esc(r.unit||"")}</b></div><div><span>Buyer</span><b>${esc(r.agency)}</b></div>${r.last_paid?`<div class="paid"><span>Paid last time</span><b>${money(r.last_paid)} each</b> <small>${esc((r.last_paid_date||"").slice(0,7))}</small></div>`:""}</div>
 ${r.for_sale?`<span class="sale">For sale now on ${r.for_sale} listing${r.for_sale>1?"s":""}</span>`:""}
 <div class="lockd"><span>Due date</span><span>Buyer name, email, phone</span><span>RFQ number</span></div></article>`}
function fullRow(r,mine){
 const a=r.approved||[];const pns=a.map(x=>`<code>${esc(x.pn||"")}</code> ${esc(x.maker||x.cage||"")}`).join("<br>");
 const sale=(r.for_sale||[]).slice(0,3).map(s=>`<a class="sale" href="${esc(s.url)}" target="_blank" rel="noopener">For sale: ${esc(s.seller)}${s.price?" "+money(s.price):""}</a>`).join(" ");
 const who=r.buyer_name?`${esc(r.buyer_name)}${r.buyer_email?`<br><a href="mailto:${esc(r.buyer_email)}">${esc(r.buyer_email)}</a>`:""}${r.buyer_phone?`<br><a href="tel:${esc(r.buyer_phone)}">${esc(r.buyer_phone)}</a>`:""}`:(r.source==="SAM.gov"?"On the notice":"On the RFQ");
 return `<article class="ask${mine?" mine":""}">${mine?`<div class="tag">Your part</div>`:""}<div class="pt">${esc(r.part||"Part")}</div><div class="mk">${pns}</div>
 <div class="kv"><div><span>Quotes due</span><b>${day(r.due)}</b> <small>${left(r.due)}</small></div><div><span>Qty</span><b>${esc(r.qty??"")} ${esc(r.unit||"")}</b></div>
 <div><span>Buyer</span><b>${who}</b></div><div><span>Office</span><b>${esc(r.office||r.agency)}</b></div>
 ${r.last_paid?`<div class="paid"><span>Paid last time</span><b>${money(r.last_paid)} each</b> <small>${esc((r.last_paid_date||"").slice(0,7))}${r.last_qty?` · qty ${r.last_qty}`:""}</small></div>`:""}
 <div><span>${esc(r.source)}</span><b>${esc(r.solicitation)}</b>${r.nsn?`<br><small>NSN ${esc(r.nsn)}</small>`:""}</div></div>
 ${sale}<div><a class="go" href="${esc(r.rfq_url)}" target="_blank" rel="noopener">Open the RFQ &rarr;</a></div></article>`}
$("#havepw").onclick=()=>{const f=$("#pwf"),on=f.hidden;f.hidden=!on;$("#havepw").setAttribute("aria-expanded",on);$("#checkout").hidden=on;if(on){f.querySelector("input").focus();track("password_open",{})}};
let CO=null;
const loadStripe=()=>window.Stripe?Promise.resolve():new Promise((ok,no)=>{const sc=document.createElement("script");sc.src="https://js.stripe.com/dahlia/stripe.js";sc.onload=ok;sc.onerror=no;document.head.appendChild(sc)});
$("#buy").onclick=async()=>{
 const b=$("#buy");$("#pwf").hidden=true;$("#havepw").setAttribute("aria-expanded","false");$("#checkout").hidden=false;
 track("checkout_open",{from:FROM});
 if(CO){$("#checkout").scrollIntoView({behavior:"smooth",block:"start"});return}
 b.disabled=true;const t=b.textContent;b.textContent="Loading secure checkout…";
 try{
  await loadStripe();const st=Stripe(PK);
  const opts={fetchClientSecret:()=>fetch("/api/checkout",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({from:FROM})}).then(r=>r.json()).then(j=>{if(!j.clientSecret)throw new Error(j.error||"Checkout could not start.");return j.clientSecret})};
  CO=await (st.createEmbeddedCheckoutPage?st.createEmbeddedCheckoutPage(opts):st.initEmbeddedCheckout(opts));
  CO.mount("#checkout");setTimeout(()=>$("#checkout").scrollIntoView({behavior:"smooth",block:"start"}),300);
 }catch(x){CO=null;$("#pwf").hidden=false;$("#pwf .pwerr").textContent="Checkout didn't load. Refresh the page and try again, or email aidan@brickandmortar.dev.";}
 finally{b.disabled=false;b.textContent=t}
};
async function getFull(pw){
 const r=await fetch("/api/data",{headers:{"x-password":pw}});
 if(!r.ok){const j=await r.json().catch(()=>({}));throw new Error(r.status==401?BAD:(j.error||BAD))}
 const d=await r.json();store.set(pw);track("unlock",{kind:r.headers.get("X-Access")||"",from:FROM});return d}
document.querySelectorAll("form.pwf").forEach(f=>f.addEventListener("submit",async e=>{
 e.preventDefault();const inp=f.querySelector("input"),err=f.querySelector(".pwerr"),b=f.querySelector("button");
 const v=inp.value.trim();if(!v){err.textContent="Enter the password from your email.";return}
 b.disabled=true;err.textContent="";const t=b.textContent;b.textContent="Opening…";
 try{onFull(await getFull(v));scrollTo({top:0,behavior:"smooth"})}catch(x){err.textContent=x.message}finally{b.disabled=false;b.textContent=t}
}));
"""


def head(title: str, desc: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="robots" content="noindex">
<style>{CSS}</style>
{POSTHOG}{VA}
</head>"""


def page(meta: dict, ex: dict) -> str:
    n, price = meta["n"], meta["price_usd"]
    rows_html = "".join(locked_row(r) for r in ex["rows"])
    # Chips: the industrial lines a surplus dealer or repair shop actually stocks, not defense primes.
    LINES = ("PARKER", "CATERPILLAR", "EATON", "HONEYWELL", "CUMMINS", "ALLEN", "ROCKWELL", "SIEMENS", "GENERAL ELECTRIC",
             "SQUARE D", "SCHNEIDER", "ABB", "EMERSON", "MOOG", "TELEDYNE", "CURTISS", "AMPHENOL", "GLENAIR", "TE CONNECTIVITY", "DETROIT DIESEL")
    picks, seen = [], set()
    for m, _ in meta["makers"]:
        w = next((l for l in LINES if m.startswith(l)), None)
        exk = "".join(c for c in (ex["maker"] or "") if c.isalnum())
        if w and w not in seen and not exk.startswith("".join(c for c in w if c.isalnum())):
            seen.add(w); picks.append(w)
    picks = picks[:8]
    chips = "".join(f'<button type="button" class="chip" data-q="{esc(m)}">{esc(m.title())}</button>' for m in picks)
    js = JS_COMMON.replace("__PK__", json.dumps(PK)) + """
const FROM="asks";const META=__META__;let FULL=null;
track("preview_open",{from:FROM});
const out=$("#out"),cnt=$("#count");
function drawLocked(q,n,rows){cnt.innerHTML=n?`<b>${n.toLocaleString()}</b> open ask${n>1?"s":""} for <b>${esc(q)}</b>. ${Math.min(3,rows.length)} shown; the rest, with due dates and buyers, are in the full list.`:`No open ask names <b>${esc(q)}</b> today. Try a maker, a part number, or a word like "valve".`;out.innerHTML=rows.map(lockedRow).join("")}
let T=null,LAST="";
async function check(q){q=q.trim();if(q===LAST)return;LAST=q;if(!q)return;
 if(FULL)return drawFull(q);
 try{const j=await fetch("/api/check?q="+encodeURIComponent(q)).then(r=>r.json());if(q===LAST){drawLocked(q,j.n,j.rows||[]);track("search",{q:q.slice(0,60),n:j.n})}}catch(e){}}
$("#q").addEventListener("input",e=>{clearTimeout(T);T=setTimeout(()=>check(e.target.value),300)});
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{$("#q").value=c.dataset.q.toLowerCase();check(c.dataset.q.toLowerCase())});
const hay=r=>(r._h??=[r.part,r.office,r.agency,r.solicitation,r.nsn,...(r.approved||[]).flatMap(a=>[a.pn,a.maker,a.cage])].join(" ").toLowerCase().replace(/[-\\s\\/.]/g,""));
let SHOWN=[];
function drawFull(q){const k=q.toLowerCase().replace(/[-\\s\\/.]/g,"");SHOWN=k?FULL.rows.filter(r=>hay(r).includes(k)):FULL.rows;
 cnt.innerHTML=`<span class="unl">Full list</span><b>${SHOWN.length.toLocaleString()}</b> open ask${SHOWN.length==1?"":"s"}${k?` for <b>${esc(q)}</b>`:""}, soonest due first.${SHOWN.length>100?" Showing 100.":""} <button class="dl" id="csv">Download CSV</button>`;
 out.innerHTML=SHOWN.slice(0,100).map(r=>fullRow(r)).join("");$("#csv").onclick=csv}
function csv(){const H=["due","part","approved_pns","makers","qty","unit","buyer_name","buyer_email","buyer_phone","office","agency","last_paid","last_paid_date","solicitation","nsn","source","rfq_url"];
 const q=v=>'"'+String(v??"").replace(/"/g,'""')+'"';
 const lines=[H.join(",")].concat(SHOWN.map(r=>[r.due,r.part,(r.approved||[]).map(a=>a.pn).join(" | "),(r.approved||[]).map(a=>a.maker||a.cage).join(" | "),r.qty,r.unit,r.buyer_name,r.buyer_email,r.buyer_phone,r.office,r.agency,r.last_paid,r.last_paid_date,r.solicitation,r.nsn,r.source,r.rfq_url].map(q).join(",")));
 const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([lines.join("\\n")],{type:"text/csv"}));a.download="open-asks-"+FULL.built+".csv";a.click();track("download",{n:SHOWN.length})}
function onFull(d){FULL=d;$("#pay").hidden=true;$("#paid").hidden=true;LAST="";drawFull($("#q").value)}
async function confirmPaid(id){
 const P=$("#paid");P.hidden=false;$("#pay").hidden=true;const H=$("#paidH"),Tx=$("#paidP");
 for(let i=0;i<6;i++){try{const j=await fetch("/api/session-status?session_id="+encodeURIComponent(id)).then(r=>r.json());
  if(j.paid){H.textContent="Check your email for your password";Tx.innerHTML=`${j.email?`Sent to <b>${esc(j.email)}</b>. `:""}Stripe's invoice carries it too. Have it? Enter it here:`;P.querySelector(".pwf").hidden=false;track("paid",{});return}
  if(j.status=="expired"||j.error)break}catch(e){}await new Promise(r=>setTimeout(r,2500))}
 H.textContent="We couldn't confirm that payment yet";Tx.innerHTML=`If you were charged, the password is on its way to your email. Otherwise <a href="/asks/">go back</a> and try again, or write to aidan@brickandmortar.dev.`}
const qs=new URLSearchParams(location.search),pwq=qs.get("pw"),paidq=qs.get("paid");
if(pwq||paidq){history.replaceState(null,"",location.pathname)}
const first=pwq||store.get();
if(first)getFull(first).then(onFull).catch(x=>{if(pwq){$("#pwf").hidden=false;$("#pwf input").value=pwq;$("#pwf .pwerr").textContent=x.message}else store.set(null)});
if(paidq&&!pwq)confirmPaid(paidq);
""".replace("__META__", json.dumps({"n": n, "price": price}))
    return head("Open asks: government buyers asking for parts now",
                f"{n:,} open government requests for quotes on parts, each with the part numbers they accept.") + f"""
<body><div class="w">
<a class="back" href="/">&larr; Legacy Requests</a>
<h1>Government buyers asking for parts, right now.</h1>
<p class="lede"><b>{n:,} open requests for quotes</b>, due between {nice_date(meta['due_first'])} and {nice_date(meta['due_last'])}. Each names the part numbers they will accept and what they paid last time.</p>
<label class="sr" for="q">Search a maker or part number</label>
<input type="search" id="q" placeholder="A maker or part number you stock" value="{esc((ex['maker'] or '').lower())}" autocomplete="off" enterkeyhint="search">
<div class="chips">{chips}</div>
<p class="count" id="count"><b>{ex['n']:,}</b> open asks for <b>{esc((ex['maker'] or '').title())}</b>. 3 shown; the rest, with due dates and buyers, are in the full list.</p>
<div id="out">{rows_html}</div>
{PAY.replace('{n}', f'{n:,}').replace('{price}', str(price))}
<footer>Requests for quotes from the Defense Logistics Agency's bid board (DIBBS) still open on {meta['built']}, read from DLA's own daily files and each RFQ, plus federal sole-source notices on SAM.gov still taking responses. {meta['n_contact']:,} carry the buyer's email. "Paid last time" is the most recent award on the RFQ's own procurement history. Legacy Requests, by Brick &amp; Mortar · <a href="https://randomaidan.substack.com/p/business-prototypes">why this exists</a></footer>
</div>
<script>{js}</script>
</body></html>
"""


def locked_row(r: dict) -> str:
    pn = f"<code>{esc(r['pn'])}</code> " if r.get("pn") else ""
    paid = (f'<div class="paid"><span>Paid last time</span><b>{money(r["last_paid"])} each</b> <small>{esc((r["last_paid_date"] or "")[:7])}</small></div>'
            if r.get("last_paid") else "")
    sale = f'<span class="sale">For sale now on {r["for_sale"]} listing{"s" if r["for_sale"] > 1 else ""}</span>' if r.get("for_sale") else ""
    more = f' · {r["n_approved"]} part numbers accepted' if r.get("n_approved", 0) > 1 else ""
    return (f'<article class="ask"><div class="pt">{esc(r["part"] or "Part")}</div><div class="mk">{pn}{esc(r.get("maker") or "")}{more}</div>'
            f'<div class="kv"><div><span>Qty</span><b>{esc(r["qty"] if r["qty"] is not None else "")} {esc(r.get("unit") or "")}</b></div>'
            f'<div><span>Buyer</span><b>{esc(r["agency"])}</b></div>{paid}</div>{sale}'
            f'<div class="lockd"><span>Due date</span><span>Buyer name, email, phone</span><span>RFQ number</span></div></article>')


def for_page(meta: dict, rc: dict, own: list[dict], others: list[dict], n_line: int) -> str:
    n, price = meta["n"], meta["price_usd"]
    line = ", ".join(m.title() for m in rc.get("lines", [])[:3])
    o = own[0]
    pn = rc.get("pn") or next((a["pn"] for a in o["approved"] if a.get("pn")), "this part")
    rc.setdefault("headline", f"{o['agency'] if o['source'] == 'SAM.gov' else 'DLA'} is asking for {pn}.")
    paid = f" Last time they paid {money(o['last_paid'])} each." if o.get("last_paid") else ""
    u = "" if (o.get("unit") or "EA") == "EA" else " " + o["unit"].lower()
    rc.setdefault("lede", f"{o['qty']:,}{u} wanted, quotes due {nice_date(o['due'])}.{paid} You list it." if o.get("qty") else f"Quotes due {nice_date(o['due'])}.{paid} You list it.")
    own_json = json.dumps(own, separators=(",", ":")).replace("</", "<\\/")
    js = JS_COMMON.replace("__PK__", json.dumps(PK)) + f"""
const FROM={json.dumps(rc['token'])};
track("preview_open",{{from:FROM,token:FROM}});
const OWN={own_json};
$("#own").innerHTML=OWN.map(r=>fullRow(r,true)).join("");
function onFull(d){{location.href="/asks/"}}
"""
    rec = (f'<div class="rec"><span>Your listing</span><a href="{esc(rc["record_url"])}" target="_blank" rel="noopener">{esc(rc["their_record"])}</a></div>'
           if rc.get("record_url") else "")
    return head(f"For {rc['org']}: open asks", "Open government requests for quotes that match your part.") + f"""
<body><div class="w">
<a class="back" href="/asks/">&larr; Open asks</a>
<h1>{esc(rc['headline'])}</h1>
<p class="lede">{esc(rc['lede'])}</p>
{rec}
<div id="own"></div>
{f"""<h2>{n_line:,} more open asks name {esc(line)}.</h2>
<p class="sub">{'A few of them' if n_line > len(others) else 'Here they are'}. Due dates and buyers are in the full list.</p>
{"".join(locked_row(r) for r in others)}""" if others else ""}
{PAY.replace('{n}', f'{n:,}').replace('{price}', str(price))}
<footer>Read from the Defense Logistics Agency's bid board (DIBBS) and each RFQ on {meta['built']}. Legacy Requests, by Brick &amp; Mortar · <a href="https://randomaidan.substack.com/p/business-prototypes">why this exists</a></footer>
</div>
<script>{js}</script>
</body></html>
"""
