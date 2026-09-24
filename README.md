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
- `scripts/build_site.py` writes the page. Search runs in the browser over the
  embedded JSON; no framework, no build step.

## Record fields

agency, state, date, manufacturer, model, part_numbers (every catalog/part number printed, verbatim; empty on rows extracted before 2026-09-24), part, quantity, price_usd,
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
