"""Rockwell Automation's public Product Lifecycle Status search, one query per family.

The lifecycle page (rockwellautomation.com/.../product-lifecycle-status.html) calls a
JSON API with a client id it prints in its own HTML (data-client-id). We read that id
off the page each run, exactly as a browser does, and cache every response under
data/eol/rockwell/. Output rows cite the public lifecycle page with ?keyword=<catalog>,
which opens Rockwell's own answer for that catalog number.
"""
import json, re, sys, time, urllib.parse, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/eol/rockwell"
PAGE = "https://www.rockwellautomation.com/en-us/support/product/product-compatibility-migration/product-lifecycle-status.html"
API = "https://api.rockwellautomation.com/ra-eapi-cx-public-dashboard-vpcprod/api/v1/rockwell/search"
KEEP = ("catalogNumber", "title", "productLifeCycleStatus", "discontinuedDate", "replacementText", "replacementCategory")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


def curl(url, headers=()):
    cmd = ["curl", "-s", "--max-time", "60", "-A", UA]
    for h in headers:
        cmd += ["-H", h]
    return subprocess.run(cmd + [url], capture_output=True, text=True).stdout


def creds():
    html = curl(PAGE)
    cid = re.search(r'data-client-id="([0-9a-f]+)"', html).group(1)
    sec = re.search(r'data-client-secret="([0-9A-Za-z]+)"', html).group(1)
    return [f"client_id: {cid}", f"client_secret: {sec}", "correlation_id: prod_ra_com_search",
            "Referer: https://www.rockwellautomation.com/", "content-type: application/json"]


def search(query, hdr, size=100):
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / (re.sub(r"[^A-Za-z0-9]+", "_", query) + ".json")
    if f.exists():
        return json.loads(f.read_text())
    docs, frm, total = [], 0, None
    while total is None or frm < min(total, 3400):
        q = urllib.parse.urlencode({"query": query, "tab": "lifecycle", "from": frm, "size": size, "locale": "en-US"})
        d = json.loads(curl(f"{API}?{q}", hdr))
        total = d.get("total", 0)
        for x in d.get("docs", []):
            docs.append({k: x.get(k) for k in KEEP})
        frm += size
        time.sleep(1)
    out = {"query": query, "total": total, "fetched": time.strftime("%Y-%m-%d"), "docs": docs}
    f.write_text(json.dumps(out, separators=(",", ":")))
    return out


if __name__ == "__main__":
    hdr = creds()
    for q in sys.argv[1:]:
        d = search(q, hdr)
        from collections import Counter
        c = Counter((x.get("productLifeCycleStatus"), (x.get("discontinuedDate") or "")[:7]) for x in d["docs"])
        print(q, d["total"], len(d["docs"]), c.most_common(8))
