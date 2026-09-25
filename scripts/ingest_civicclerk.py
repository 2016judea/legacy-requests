#!/usr/bin/env python3
"""Pull sole-source / proprietary-equipment agenda items off CivicClerk's public OData API.

CivicClerk tenants answer unauthenticated at https://<tenant>.api.civicclerk.com/v1/:
  Events?$filter=...          meetings, each with an agendaId
  Meetings/<agendaId>         the agenda: nested items, each with its own text, attachments
                              (attachmentsList) and staff reports (reportsList) as PDFs
There is no server-side search, so every agenda since SINCE is read and filtered locally
(agenda_common.wanted). Only items that pass get their PDFs downloaded. Output is
data/matters/civicclerk-<tenant>.json in the shape documented in scripts/extract.py.

Tenants were found by probing <city><state> slugs (2026-09-24): a wrong slug is a 404,
a real one returns an OData Events document. Add a tenant by adding a row to TENANTS.

Usage: scripts/ingest_civicclerk.py [tenant ...]      (default: every tenant in TENANTS)
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from agenda_common import SINCE, MAX_ATTACHMENTS, cached_json, cached_pdf, strip_html, wanted, write_matters

P = "civicclerk"
# tenant -> agency. State is the slug's last two letters unless given.
TENANTS = {
    "mcallentx": "City of McAllen", "mobileal": "City of Mobile", "pensacolafl": "City of Pensacola",
    "santafenm": "City of Santa Fe", "colliercofl": "Collier County", "danvilleva": "City of Danville",
    "milpitasca": "City of Milpitas", "missoulacomt": "Missoula County", "portlandme": "City of Portland",
    "elpasotx": "City of El Paso", "garlandtx": "City of Garland", "amarillotx": "City of Amarillo",
    "midlandtx": "City of Midland", "odessatx": "City of Odessa", "abilenetx": "City of Abilene",
    "sugarlandtx": "City of Sugar Land", "edinburgtx": "City of Edinburg", "harlingentx": "City of Harlingen",
    "missiontx": "City of Mission", "pharrtx": "City of Pharr", "rowletttx": "City of Rowlett",
    "texarkanatx": "City of Texarkana", "collegestationtx": "City of College Station",
    "wichitafallstx": "City of Wichita Falls", "sanangelotx": "City of San Angelo",
    "scottsdaleaz": "City of Scottsdale", "surpriseaz": "City of Surprise", "avondaleaz": "City of Avondale",
    "prescottaz": "City of Prescott", "tallahasseefl": "City of Tallahassee", "gainesvillefl": "City of Gainesville",
    "melbournefl": "City of Melbourne", "leecofl": "Lee County", "pascocofl": "Pasco County",
    "escambiacofl": "Escambia County", "stluciecofl": "St. Lucie County", "indianrivercofl": "Indian River County",
    "cobbcoga": "Cobb County", "highpointnc": "City of High Point", "murfreesborotn": "City of Murfreesboro",
    "franklintn": "City of Franklin", "jacksontn": "City of Jackson", "tuscaloosaal": "City of Tuscaloosa",
    "jacksonms": "City of Jackson", "gulfportms": "City of Gulfport", "hattiesburgms": "City of Hattiesburg",
    "lakecharlesla": "City of Lake Charles", "fayettevillear": "City of Fayetteville", "jonesboroar": "City of Jonesboro",
    "normanok": "City of Norman", "lawtonok": "City of Lawton", "stlouismo": "City of St. Louis",
    "springfieldmo": "City of Springfield", "independencemo": "City of Independence", "davenportia": "City of Davenport",
    "waterlooia": "City of Waterloo", "greenbaywi": "City of Green Bay", "peoriail": "City of Peoria",
    "elginil": "City of Elgin", "fortwaynein": "City of Fort Wayne", "carmelin": "City of Carmel",
    "lansingmi": "City of Lansing", "buffalony": "City of Buffalo", "albanyny": "City of Albany",
    "springfieldma": "City of Springfield", "manchesternh": "City of Manchester", "nashuanh": "City of Nashua",
    "burlingtonvt": "City of Burlington", "norfolkva": "City of Norfolk", "roanokeva": "City of Roanoke",
    "lynchburgva": "City of Lynchburg", "charlestonwv": "City of Charleston", "charlestonsc": "City of Charleston",
    "columbiasc": "City of Columbia", "greenvillesc": "City of Greenville", "spartanburgsc": "City of Spartanburg",
    "fortcollinsco": "City of Fort Collins", "lakewoodco": "City of Lakewood", "arvadaco": "City of Arvada",
    "puebloco": "City of Pueblo", "greeleyco": "City of Greeley", "oremut": "City of Orem",
    "meridianid": "City of Meridian", "bismarcknd": "City of Bismarck", "vancouverwa": "City of Vancouver",
    "kennewickwa": "City of Kennewick", "juneauak": "City and Borough of Juneau", "anaheimca": "City of Anaheim",
    "oxnardca": "City of Oxnard", "escondidoca": "City of Escondido", "rosevilleca": "City of Roseville",
    "vallejoca": "City of Vallejo", "richmondca": "City of Richmond", "antiochca": "City of Antioch",
    "clovisca": "City of Clovis", "turlockca": "City of Turlock", "yubacityca": "City of Yuba City",
    "hanfordca": "City of Hanford", "folsomca": "City of Folsom",
}


def api(tenant: str, path: str) -> str:
    return f"https://{tenant}.api.civicclerk.com/v1/{path}"


def events(tenant: str) -> list[dict]:
    """Every published event with an agenda since SINCE. The listing is keyed by its URL and
    today's date so a re-run tomorrow sees new meetings; agendas themselves are cached forever."""
    import datetime
    today = datetime.date.today().isoformat()
    flt = f"startDateTime ge {SINCE}T00:00:00Z and startDateTime le {today}T23:59:59Z and hasAgenda eq true"
    url = api(tenant, f"Events?$filter={quote(flt)}&$orderby=startDateTime")  # $top caps the TOTAL, not the page
    out = []
    while url:
        page = cached_json(P, f"{today}:{url}", url)
        if not page:
            break
        out += page.get("value", [])
        url = page.get("@odata.nextLink")
    return out


def walk(items):
    for it in items or []:
        yield it
        yield from walk(it.get("childItems"))


def item_matters(tenant: str, ev: dict) -> list[dict]:
    aid = ev.get("agendaId")
    if not aid:
        return []
    mtg = cached_json(P, f"{tenant}:meeting:{aid}", api(tenant, f"Meetings/{aid}"))
    if not mtg:
        return []
    out = []
    for it in walk(mtg.get("items")):
        name = strip_html(it.get("agendaObjectItemName"))
        body = "\n".join(strip_html(it.get(k)) for k in
                         ("agendaObjectItemDescription", "agendaObjectItemHtmlContent", "fiscalImpactSummary") if it.get(k))
        why = wanted(name + "\n" + body, name)
        if not why or it.get("isSection"):
            continue
        atts = []
        files = [(a.get("fileName") or a.get("pdfVersionFileName"), a.get("mediaFullPath"), a.get("pdfVersionFullPath"), "attachment", a.get("id"))
                 for a in it.get("attachmentsList") or [] if (a.get("contentType") or "").endswith("pdf") or (a.get("pdfVersionFullPath") or "").split("?")[0].endswith(".pdf")]
        files += [(r.get("agendaObjItemReportName"), r.get("pdfMediaFileName"), r.get("pdfMediaFullPath"), "report", r.get("id"))
                  for r in it.get("reportsList") or []]
        for fname, stable, signed, kind, fid in files[:MAX_ATTACHMENTS]:
            if not signed:
                continue
            path = cached_pdf(P, f"{tenant}:{kind}:{stable or fid}", signed)
            if path:
                # the portal link is permanent; the blob link in `signed` expires in a week
                atts.append({"name": fname, "path": path,
                             "url": f"https://{tenant}.portal.civicclerk.com/event/{ev['id']}/files/{kind}/{fid}"})
        out.append({
            "matter_id": it["id"],
            "file": it.get("agendaObjectItemOutlineNumberFull") or None,
            "title": name[:500],
            "intro_date": (ev.get("startDateTime") or "")[:10],
            "body": ev.get("categoryName") or ev.get("eventName"),
            "keyword": why,
            "url": f"https://{tenant}.portal.civicclerk.com/event/{ev['id']}/overview",
            "text": body[:60_000],
            "attachments": atts,
        })
    return out


def ingest(tenant: str) -> tuple[str, int, int, int]:
    evs = events(tenant)
    with ThreadPoolExecutor(4) as pool:
        matters = [m for ms in pool.map(lambda e: item_matters(tenant, e), evs) for m in ms]
    seen, uniq = set(), []
    for m in matters:                      # the same item can be re-listed on a later agenda
        if m["matter_id"] not in seen:
            seen.add(m["matter_id"]); uniq.append(m)
    agency, state = TENANTS[tenant], tenant[-2:].upper()
    sent = write_matters(f"{P}-{tenant}", P, agency, state, uniq)
    return tenant, len(evs), len(uniq), len(sent)


def main(argv):
    tenants = argv or list(TENANTS)
    with ThreadPoolExecutor(6) as pool:
        for t, n_ev, n_m, n_pdf in pool.map(ingest, tenants):
            print(f"civicclerk-{t}: {n_ev} agendas, {n_m} items kept, {n_pdf} sent to extract", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
