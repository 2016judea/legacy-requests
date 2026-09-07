PY=.venv/bin/python

.venv:
	uv venv .venv && VIRTUAL_ENV= uv pip install --python .venv/bin/python -r requirements.txt

ingest:      ## pull matters + PDFs off Legistar into data/cache (never re-downloads)
	$(PY) scripts/ingest.py

extract:     ## Claude turns each matter into records -> data/records.db + records.jsonl
	$(PY) scripts/extract.py

site:        ## regenerate site/index.html from data/records.jsonl
	$(PY) scripts/build_site.py

deploy: site ## push site/ to Vercel production
	cd site && npx vercel deploy --prod --yes

all: ingest extract site
