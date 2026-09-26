#!/usr/bin/env python3
"""Find Legistar clients that answer on the public web API, so clients.json grows by
evidence instead of guesses.

crt.sh cannot enumerate them: every <client>.legistar.com sits under one wildcard
cert (checked 2026-09-25: 391 certs, 6 hostnames, all Granicus-internal). So the only
proof a client exists is the API answering, and this script asks it.

Usage: scripts/probe_legistar.py [slug ...]
  With no args, probes CANDIDATES below minus clients.json. Prints one line per slug
  that answers with at least one matter introduced since 2024-01-01, as a clients.json
  row with the agency name blank: fill it by hand from the sample matter and body.
  (Do not read <slug>.legistar.com/Calendar.aspx for the name: that page takes
  minutes to render and hung the first run.) Slugs that answer 200 but hold no
  matter dated 2024+ (sfgov, longbeach, miamidade: MatterIntroDate is null there,
  the kingcounty problem in BACKLOG.md) go to stderr. Probes are cached under
  data/cache/probe/ so a re-run is free.
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "probe"
CLIENTS = {c["slug"] for c in json.loads((ROOT / "clients.json").read_text())}
API = "https://webapi.legistar.com/v1"
UA = {"User-Agent": "obsolete-parts/0.1 (public-records research; github.com/2016judea/obsolete-parts)"}
SINCE = "2024-01-01"

# Slugs worth asking about: the biggest US cities and counties, the water, transit and
# port districts whose packets carry hardware, and the Granicus-hosted agencies
# BACKLOG.md (2026-09-24) says are really Legistar. A miss costs one cached 404.
CANDIDATES = """
nyc chicago philadelphia phila sfgov sandiego longbeach miamidade miamifl tampa orlando atlantacityga
atlanta cincinnati cincinnatioh cleveland akron dayton lexington cityofno neworleans batonrouge
sanantonio elpasotx houston austin arlington plano garland irving lubbock laredo mcallen amarillo
detroit detroitmi a2gov grandrapids lansing kenosha racine greenbay tucson lasvegas clark clarkcounty
wichita omaha lincoln desmoines minneapolis hennepin ramsey saintpaul stlouis stlouis-mo kansascitymo
jacksonms littlerock oklahomacity okc tulsa boulder aurora fortcollins lakewood saltlakecity slc boise
spokane everett bellevue kingcounty kirkland renton kent piercecounty vancouverwa portland eugene salem
honolulu anchorage bakersfield modesto santarosa santacruz monterey salinas sanluisobispo slocounty ventura
oxnard burbank glendale glendaleca pasadena torrance anaheim santaana santa-ana irvine huntingtonbeach
fullerton costamesa ontario fontana morenovalley palmsprings temecula murrieta chulavista oceanside
carlsbad escondido sandiegocounty sdcounty vallejo fairfield berkeley richmondca sanleandro fremont
unioncity sunnyvaleca sunnyvale sccgov paloalto redwoodcity cityofsanmateo dalycity marin marincounty
sanjoaquin stanislaus kern kerncounty tulare merced monterey-county santacruzcounty ventura-county
sandiego-county riversidecounty rivco sbcounty orangecounty oc sacramento-county saccounty placer
yolo yolocounty
ebmud sfpuc ocwd irwd ieua sdcwa sfwater vta samtrans sfmta goldengate caltrain metrolink sandag mts
nctd rtd rtd-denver cta septa wmata mbta njtransit mta soundtransit kingcountymetro trimet
portla portofsandiego portseattle porttacoma portofla portofhouston massport panynj
visalia sanmarcos san-marcos corpus-christi lametro octa-ca
miami hialeah fortlauderdale pembrokepines hollywoodfl coralsprings clearwater stpete stpetersburg
tallahassee gainesville lakeland palmbeach palmbeachcounty leecounty collier hillsborough orangecountyfl
seminole volusia brevard polk pasco manatee sarasota
richmondva norfolk virginiabeach chesapeake newportnews alexandria arlingtonva fairfaxcounty
loudoun princewilliam montgomerycountymd howardcounty princegeorges baltimorecounty annearundel
dc dccouncil charlotte raleigh durham greensboro winstonsalem charlestonsc columbiasc greenville
savannah augusta macon gwinnett cobb clayton
birmingham montgomery mobile huntsville memphis knoxville chattanooga
buffalo rochester syracuse albany yonkers nassau suffolk westchester erie
jerseycity paterson elizabeth edison trenton camden
hartford newhaven bridgeport stamford providence worcester springfield lowell cambridge somerville
pittsburgh-pa allegheny harrisburg lancaster reading scranton
milwaukee-wi waukesha appleton oshkosh eauclaire
indianapolis fortwayne evansville southbend gary
stlouiscounty springfieldmo columbiamo jeffersoncity
denvergov jeffco arapahoe adams douglas larimer weld pueblo greeley
phoenixaz scottsdale chandler gilbert tempe glendaleaz peoria surprise goodyear flagstaff yuma
albuquerque santafe lascruces rioarancho bernalillo
reno sparks washoe henderson northlasvegas
saltlake sandy provo ogden westvalley utahcounty
""".split()


def cached(url: str) -> tuple[int, bytes]:
    key = hashlib.sha1(url.encode()).hexdigest()
    p = CACHE / f"{key}.json"
    if p.exists():
        d = json.loads(p.read_text())
        return d["status"], d["body"].encode()
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, headers=UA, timeout=30)
        status, body = r.status_code, r.text
    except requests.RequestException:
        status, body = 0, ""
    p.write_text(json.dumps({"url": url, "status": status, "body": body[:20000]}))
    time.sleep(0.3)
    return status, body.encode()


def probe(slug: str) -> dict | None:
    flt = f"MatterIntroDate ge datetime'{SINCE}'"
    url = f"{API}/{slug}/matters?" + requests.compat.urlencode({"$filter": flt, "$top": 1})
    status, body = cached(url)
    if status != 200:
        return None
    try:
        page = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(page, list):
        return None
    if not page:
        print(f"{slug}: answers, no matters dated {SINCE}+", file=sys.stderr)
        return None
    return {"slug": slug, "agency": "", "state": "", "body": page[0].get("MatterBodyName"), "sample": (page[0].get("MatterTitle") or "")[:80]}


def main(argv):
    slugs = argv or [s for s in dict.fromkeys(CANDIDATES) if s not in CLIENTS]
    hits = 0
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(probe, slugs):
            if r:
                hits += 1
                print(json.dumps(r), flush=True)
    print(f"probed {len(slugs)}, answering with 2024+ matters: {hits}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
