PY=.venv/bin/python
.PHONY: ingest extract site deploy all supply join check

.venv:
	uv venv .venv && VIRTUAL_ENV= uv pip install --python .venv/bin/python -r requirements.txt

ingest:      ## pull matters + PDFs off Legistar into data/cache (never re-downloads)
	$(PY) scripts/ingest.py

extract:     ## Claude turns each matter into records -> data/records.db + records.jsonl
	$(PY) scripts/extract.py

site:        ## regenerate site/index.html from data/records.jsonl
	$(PY) scripts/build_site.py

supply:      ## pull surplus listings for index makes/models -> data/supply/<source>.jsonl (cached), then join
	@for f in scripts/supply_*.py; do [ -e "$$f" ] || continue; $(PY) $$f || exit 1; done
	$(PY) scripts/join_supply.py

join:        ## match every data/supply/*.jsonl to records -> data/supply/matches.json
	$(PY) scripts/join_supply.py

check:       ## prove the supply join (fixed cases + live counts)
	$(PY) scripts/check_supply.py

deploy: site ## push site/ to Vercel production (REST API; the CLI returns BLOCKED here)
	$(PY) scripts/deploy.py

all: ingest extract site
