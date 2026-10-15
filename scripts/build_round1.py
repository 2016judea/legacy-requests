#!/usr/bin/env python3
"""Round 1 of paid distribution (2026-10-15): ledger + one draft email per recipient.

Reads outreach/round1/recipients.json (gitignored; hand-built: each row a named seller, a
verified email and where it is printed, and THEIR OWN listing that names a part an open
ask wants). Reads the full open-asks set (private/bundle/rows.json.gz, scripts/build_asks.py)
for the facts each email quotes, so no number is typed.

Writes outreach/round1/ledger.csv and outreach/round1/drafts/<token>.txt. Sends nothing:
contacting a person is Aidan's gate. Sends go one-to-one from Zoho after 2026-10-19.
"""
import csv
import gzip
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outreach" / "round1"
HOST = "https://legacy-requests.vercel.app"
SUBSTACK = "https://randomaidan.substack.com/p/business-prototypes"


def money(v):
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"


def main():
    rows = {r["id"]: r for r in json.loads(gzip.decompress((ROOT / "private/bundle/rows.json.gz").read_bytes()))["rows"]}
    meta = json.loads((ROOT / "site/asks/meta.json").read_text())
    recips = json.loads((OUT / "recipients.json").read_text())
    (OUT / "drafts").mkdir(parents=True, exist_ok=True)
    out = []
    for rc in recips:
        own = [rows[i] for i in rc["ask_ids"] if i in rows]
        if not own:
            print(f"  ! {rc['token']} {rc['org']}: ask closed, skipped")
            continue
        r = own[0]
        pn = rc["pn"]
        unit = "" if (r.get("unit") or "EA") == "EA" else f" {r['unit'].lower()}"
        due = date.fromisoformat(r["due"]).strftime("%B %-d")
        who = "The Defense Logistics Agency" if r["source"] == "DLA DIBBS" else r["agency"]
        paid = (f" The last time they bought it they paid {money(r['last_paid'])} each." if r.get("last_paid") else "")
        line = set(rc.get("lines") or [])
        late = (date.today() + timedelta(days=7)).isoformat()  # same rule as scripts/build_asks.py
        n_others = min(5, sum(1 for x in rows.values() if x["id"] not in rc["ask_ids"] and line & set(x["makers"]) and x["due"] >= late))
        page = f"{HOST}/for/{rc['token']}/"
        subject = f"{pn}: {r['qty']:,}{unit} wanted, quotes due {due}"
        hello = f"Hi {rc['name'].split()[0]}," if rc.get("name") else "Hi,"
        body = "\n".join([
            hello,
            "",
            rc["their_record_line"],
            "",
            f"{who} has an open request for {r["qty"]:,}{unit} of the {pn} right now. Quotes are due {due}.{paid}",
            "",
            (f"That one and {n_others} more in the same line are open to poke at, no login: {page}" if n_others
             else f"It's open to poke at, no login: {page}"),
            "",
            f"The full list is every open government request for a part, {meta['n']:,} today, each with its due date and the buyer's email and phone. It's ${meta['price_usd']}, once.",
            "",
            "Best,",
            "Aidan",
            SUBSTACK,
        ])
        (OUT / "drafts" / f"{rc['token']}.txt").write_text(f"To: {rc['email']}\nSubject: {subject}\n\n{body}\n")
        out.append({"token": rc["token"], "segment": rc["segment"], "name": rc.get("name") or "", "org": rc["org"],
                    "email": rc["email"], "email_source": rc["email_source"], "their_record": rc["their_record"],
                    "record_url": rc["record_url"], "page_url": page, "subject": subject, "status": "drafted"})
    with (OUT / "ledger.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    seg = {}
    for o in out:
        seg[o["segment"]] = seg.get(o["segment"], 0) + 1
    print(f"{len(out)} drafts -> {OUT}/drafts, ledger {OUT}/ledger.csv; by segment {seg}")


if __name__ == "__main__":
    main()
