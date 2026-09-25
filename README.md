# The Google of obsolete infrastructure parts

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

## Record fields

agency, state, date, manufacturer, model, part_numbers (every catalog/part number printed, verbatim; absent on 336 older rows the 2026-09-25 re-read could not pair, and on older service contracts), part, quantity, price_usd,
lead_time, sole_source_vendor, reason (verbatim quote), equipment_class,
installed_location, is_obsolete, source_url, legistar_url.

A field is null when the document did not state it. Duplicate filings (the
same purchase reported to a committee and then to the board) are collapsed.

## Not in v1

SAM.gov, state portals beyond FL and MS, eBay (no API key), OEM catalogs, and
monitoring/alerts.

## Licence

Code: MIT. The records are derived from public agency documents; each row
links to its source.

## SAM ingest: resume here

- Done (2026-09-25): `scripts/ingest_sam.py` listed 14,263 federal sole-source/brand-name/J&A notices for 09/26/2025-09/25/2026 (1,609 active via the keyed search API in 4 calls + 12,654 archived via the keyless bulk CSV), screened 6,074 to equipment by PSC, wrote the top 1,500 to `data/matters/federal-sam.json`; 336 extracted ($10.68) = 1,045 raw rows, 656 with part_numbers. Not yet merged into records.jsonl, site or deploy.
- Left: extract the rest of the qualifying notices (952 of the 1,500 qualify; ~$14 budget left of $25), then `extract.py --cached-only` (all slugs, so the 5,312 other rows stay), `make site`, `make check`, commit by path, push main, `make deploy` from the main checkout. The keyless caches (data/cache/sam/, 2.2GB bulk) are local to this worktree; a fresh checkout re-downloads them.
- Resume: `caffeinate -dims .venv/bin/python scripts/extract.py federal-sam --limit 700 > extract_sam.log 2>&1 &` then `.venv/bin/python scripts/extract.py --cached-only`. Rate limit seen: none. 4 keyed calls, HTTP 200, no rate headers; descriptions and attachments come from sam.gov's keyless public endpoints, so the key's quota is spent only on the listing.
