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
    make extract   # Claude -> data/records.db + data/records.jsonl (one call per matter, cached)
    make site      # data/records.jsonl -> site/index.html (generated; never hand-edit)
    make deploy    # site/ -> Vercel

- `clients.json` lists the Legistar clients that answer on the public API
  (`https://webapi.legistar.com/v1/<client>/matters`). Add a slug to add a city.
- `scripts/ingest.py` searches matter titles since 2024-01-01 for sole-source
  and equipment keywords, then fetches each matter's text and PDF attachments.
- `scripts/extract.py` sends a matter to the model only if it or one of its
  PDFs uses sole-source language. Scanned PDFs with no text layer are sent as
  documents so the model reads the image. Output is schema-validated; every
  record carries its `source_url` and a verbatim `reason`, so no number on the
  page was typed by hand. Needs `ANTHROPIC_API_KEY` in the environment.
- `scripts/build_site.py` writes the page. Search runs in the browser over the
  embedded JSON; no framework, no build step.

## Record fields

agency, state, date, manufacturer, model, part, quantity, price_usd,
lead_time, sole_source_vendor, reason (verbatim quote), equipment_class,
installed_location, is_obsolete, source_url, legistar_url.

A field is null when the document did not state it. Duplicate filings (the
same purchase reported to a committee and then to the board) are collapsed.

## Not in v1

SAM.gov, state procurement portals, the supply side (eBay, auctions, surplus
dealers, OEM catalogs), and monitoring/alerts.

## Licence

Code: MIT. The records are derived from public agency documents; each row
links to its source.
