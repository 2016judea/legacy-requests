# Discontinued Equipment

A searchable index of the equipment public agencies could buy from only one
supplier — the manufacturer, the model, what they paid, how long they waited,
and the agency's own words on why nobody else could sell it to them.

Cities and utilities must justify every purchase that skips competitive
bidding. Those justifications ("sole source", "single source", "proprietary",
"obsolete", "no longer manufactured") are public, filed as council agenda
items, and they name the part. This repo pulls them off the Legistar public
API, turns each one into a structured record with Claude, and publishes a
static page anyone can search.

## How it works

    make ingest    # Legistar API -> data/cache/ (JSON + PDFs; never re-downloaded)
    make ingest-granicus  # Granicus agenda sites (granicus.json) -> data/matters/granicus-*.json
    make extract   # Claude -> data/records.db + data/records.jsonl (one call per matter, cached)
    make site      # data/records.jsonl -> site/index.html (generated; never hand-edit)
    make supply    # surplus/dealer listings for indexed makes+models -> data/supply/ (cached), then join
    make check     # prove the supply join: fixed cases + live match counts
    make deploy    # site/ -> Vercel

- `clients.json` lists the Legistar clients that answer on the public API
  (`https://webapi.legistar.com/v1/<client>/matters`). Add a slug to add a city.
  `scripts/probe_legistar.py` finds more: it asks the API about a candidate list and
  prints the slugs that answer with 2024+ matters (crt.sh cannot enumerate them; one
  wildcard cert covers every client). 2026-09-25: 338 probed, 32 added, 100 clients.
- `scripts/ingest_granicus.py` walks each `granicus.json` site's public meeting list
  (`<host>.granicus.com/ViewPublisher.php`), opens every agenda since 2024, and keeps
  the items whose staff report or packet pages use sole-source language. Agendas a
  Granicus site serves from a Legistar host are left to `ingest.py`. Sites tried that
  yielded nothing (no attachment links, or Legistar-backed) are listed with 0 matters.
- `boarddocs.json` lists BoardDocs sites (`go.boarddocs.com/<state>/<site>/Board.nsf`),
  weighted to water, wastewater and utility agencies. `scripts/ingest_boarddocs.py`
  runs each site's own full-text search (which covers attachments) for sole-source
  phrases, keeps agenda items from 2024 on, and caches each item's HTML and PDFs.
  Output is `data/matters/boarddocs-<state>-<site>.json`, tagged `platform: boarddocs`.
  No login: the public endpoints need only an ordinary browser User-Agent.
- `scripts/ingest.py` searches matter titles since 2024-01-01 for sole-source
  and equipment keywords, then fetches each matter's text and PDF attachments.
- `scripts/extract.py` sends a matter to the model only if it or one of its
  PDFs uses sole-source language. Scanned PDFs with no text layer are sent as
  documents so the model reads the image. Output is schema-validated; every
  record carries its `source_url` and a verbatim `reason`, so no number on the
  page was typed by hand. Needs `ANTHROPIC_API_KEY` in the environment.
- **Supply side.** Each source writes `data/supply/<source>.jsonl` in one
  schema (source, title, manufacturer, model, part_number, price, currency,
  url, seen_at, location) via `scripts/supply_<source>.py`.
  `scripts/join_supply.py` reads every file and matches listings to records
  on manufacturer AND an exact part number; a false "who has one" is worse
  than a miss, so the rule is strict (see its docstring).
- Any agenda platform can feed extraction: write `data/matters/<slug>.json` in the
  shape documented at the top of `scripts/extract.py` (agency, state and
  platform may sit in the file itself; attachments may be cached files or inline
  text). `scripts/extract.py --cached-only` rebuilds the store from cached model
  responses without spending anything.
- State sole-source notice boards (platform `state-<xx>`, one ingester each, no login):
  `scripts/ingest_state_fl.py` reads every "Single Source" posting on Florida's
  Vendor Bid System through its public JSON API and parses the standard PUR 7776
  form's labelled fields, keeping only notices whose UNSPSC codes are physical
  equipment; `scripts/ingest_state_ms.py` reads Mississippi's "Sole Source Notices"
  grid and its justification PDFs. Each writes `data/matters/state-<xx>.json`
  for `make extract`. Run them by hand; they are not in `make ingest`.
- `scripts/ingest_civicclerk.py` and `scripts/ingest_primegov.py` (`make ingest-civicclerk`,
  `make ingest-primegov`) read every agenda since 2024 off those two platforms' public,
  unauthenticated APIs, keep the items whose own text uses sole-source language or buys
  named hardware, and cache those items' PDFs under `data/cache/<platform>/`. Tenants
  are listed at the top of each script; add a row to add an agency.
- `scripts/build_site.py` writes the page. The first page of the default view is
  inline (~100KB); `site/data.json` (every record, page fields only) loads right
  after first paint and search runs over it in the browser; `site/records.json` is
  the full download. No framework, no build step.
- `extract.py` keeps a row only if its `reason` states a sole-source, proprietary,
  standardization or obsolescence justification (`JUSTIFY_RE`); full board packets
  (Metrolink, Caltrain) otherwise leak capital-budget list items into the index.
- `scripts/reread_part_numbers.py` re-reads matters extracted before `part_numbers`
  existed. `make extract` cannot: its per-matter cache returns the old response. The
  script calls the model fresh, keeps the raw reply under `data/cache/extract/<model>/reread-pn/`,
  and merges only `part_numbers` (verbatim-checked against the text layer) into the
  cached response; then `extract.py --cached-only`.

- **Federal (platform `federal-sam`).** `scripts/ingest_sam.py` lists a year of SAM.gov notices that are
  a J&A, or say sole source / single source / brand name in the title: active ones off the keyed
  Opportunities API (`SAM_API_KEY` in the main checkout's `.env.local`; ~1 call per 1,000 notices),
  archived ones off SAM.gov's keyless bulk CSV (search drops a notice once it is archived). Descriptions
  and attachments come from sam.gov's keyless public endpoints, so the key's quota is spent only on the
  listing. PSC screen to equipment (goods groups 10-99 minus consumables, plus J repair codes), ranked so
  notices printing a part number reach the model first. 2026-09-25: 14,263 notices, 6,074 equipment,
  700 extracted ($21.18) -> 1,530 records. Resume more with `scripts/extract.py federal-sam --limit N`,
  then ALWAYS `scripts/extract.py --cached-only` (a single-slug run rewrites the store with that slug only).

- **Open notices (`make open`, page `/open`).** `scripts/ingest_sam_open.py` catches federal sole-source
  purchases BEFORE they happen: Special Notices ("intent to sole source"), Presolicitations, Sources Sought
  and brand-name solicitations whose response deadline is still ahead (keyed search with `rdlfrom`, 4 calls a
  day). Extracted with `extract.py`'s schema and cache (slug `open-sam`, never written into records.jsonl),
  then matched to supply listings (the join's rule), to the dealers' sitemaps by printed part number, and to
  the makers each dealer carries. Writes `data/open_notices.jsonl`; `build_site.py` renders `site/open/`.
  Contracting-officer contact goes to `outreach/open_contacts.jsonl` (gitignored), never the page.
  2026-09-30: 79 notices listed, 14 buying a physical part, 5 print a part number, 5 name a maker a dealer
  lists, 2 both, 0 on a dealer's shelf by exact part number. $0.69 of extraction.

## Record fields

agency, state, date, manufacturer, model, part_numbers (every catalog/part number printed, verbatim; absent on 336 older rows the 2026-09-25 re-read could not pair, and on older service contracts), part, quantity, price_usd,
lead_time, sole_source_vendor, reason (verbatim quote), equipment_class,
installed_location, is_obsolete, source_url, legistar_url.

A field is null when the document did not state it. Duplicate filings (the
same purchase reported to a committee and then to the board) are collapsed.

## Not in v1

State portals beyond FL and MS, eBay (no API key), OEM catalogs, and
monitoring/alerts.

## Licence

Code: MIT. The records are derived from public agency documents; each row
links to its source.

