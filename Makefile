PY=.venv/bin/python
.PHONY: ingest extract site deploy all

.venv:
	uv venv .venv && VIRTUAL_ENV= uv pip install --python .venv/bin/python -r requirements.txt

ingest:      ## pull matters + PDFs off Legistar into data/cache (never re-downloads)
	$(PY) scripts/ingest.py

extract:     ## Claude turns each matter into records -> data/records.db + records.jsonl
	$(PY) scripts/extract.py

site:        ## regenerate site/index.html from data/records.jsonl
	$(PY) scripts/build_site.py

deploy: site ## push site/ to Vercel production (REST API; the CLI returns BLOCKED here)
	$(PY) scripts/deploy.py

all: ingest extract site
