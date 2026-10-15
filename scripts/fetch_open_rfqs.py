#!/usr/bin/env python3
"""Fetch the RFQ PDF for every OPEN DLA DIBBS solicitation (cached; never re-fetched).

Open = return-by date today or later, across every issue day DIBBS still lists
(RFQDates.aspx?category=recent, ~30 days). The PDF is the only place DIBBS prints the
buyer (name, email, phone), each approved source's NAME, and the NSN's procurement
history (last price paid). scripts/build_open_asks.py reads what this caches.

Order: lines with an approved part number first (what a parts dealer can quote), then
the rest; within each, latest return-by first. Polite: one request at a time, DELAY s apart.

Run: caffeinate -dims .venv/bin/python scripts/fetch_open_rfqs.py [--delay 0.7] [--limit N] [--shard 0/3]
(three shards in parallel took the 2026-10-15 backlog of ~18.7k PDFs)
"""
import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dibbs_match as D  # noqa: E402


def open_lines():
    today = date.today().isoformat()
    rows, approved = [], {}
    for d in D.issue_days(40):
        r, srcs = D.load_day(d)
        rows += [x for x in r if x["return_by"] and x["return_by"] >= today]
        for nsn, pairs in srcs.items():
            approved.setdefault(nsn, [])
            approved[nsn] += [p for p in pairs if p not in approved[nsn]]
    return rows, approved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.7)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", default="0/1", help="i/n: this process takes every n-th solicitation")
    a = ap.parse_args()
    D.DELAY = a.delay
    rows, approved = open_lines()
    sols = {}
    for r in rows:
        k = r["solicitation"]
        pri = (0 if approved.get(r["nsn"]) else 1, "~" if not r["return_by"] else "".join(chr(255 - ord(c)) for c in r["return_by"]))
        sols[k] = min(sols.get(k, pri), pri)
    order = sorted(sols, key=lambda s: sols[s])
    todo = [s for s in order if not (D.CACHE / "pdf" / f"{s}.txt").exists()]
    print(f"open lines {len(rows)}, solicitations {len(sols)}, to fetch {len(todo)}", flush=True)
    i0, n = map(int, a.shard.split("/"))
    todo = todo[i0::n]
    if a.limit:
        todo = todo[: a.limit]
    for i, sol in enumerate(todo, 1):
        pdf = D.get(f"{D.D2}/Downloads/RFQ/{sol[-1]}/{sol}.PDF", D.CACHE / "pdf" / f"{sol}.PDF")
        if pdf and pdf.startswith(b"%PDF"):
            txt = D.CACHE / "pdf" / f"{sol}.txt"
            txt.write_text(subprocess.run(["pdftotext", "-layout", str(D.CACHE / "pdf" / f"{sol}.PDF"), "-"],
                                          capture_output=True, text=True).stdout)
        if i % 200 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
