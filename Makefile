PY ?= python3
DB ?= data/vendor_intelligence.db
PORT ?= 8000

.PHONY: install seed build-facts train serve test demo clean

install:
	$(PY) -m pip install -r requirements.txt

seed:                 ## generate the synthetic Procol-shaped world (fixed seed)
	$(PY) -m vi.seed.generate --db $(DB) --seed 42

build-facts:          ## rebuild vendor_profiles (idempotent, no AI)
	$(PY) -m vi.facts.build --db $(DB)

train:                ## train the two ranker models and report honest AUC
	$(PY) -m vi.ranker.train --db $(DB)

serve:                ## run the demo server on http://127.0.0.1:$(PORT)
	$(PY) -m vi.api --db $(DB) --port $(PORT)

test:                 ## pytest if available, else stdlib unittest
	@if $(PY) -c "import pytest" 2>/dev/null; then $(PY) -m pytest -q tests; \
	else $(PY) -m unittest discover -s tests -v; fi

demo: seed build-facts train   ## full pipeline, then serve
	$(PY) -m vi.api --db $(DB) --port $(PORT)

clean:
	rm -rf data/*.db data/models/*.json
