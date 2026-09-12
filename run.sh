#!/usr/bin/env bash
# Same targets as the Makefile, for machines without make (or where Makefile could not be written).
#   ./run.sh demo | seed | build-facts | serve | test | install
set -euo pipefail
PY="${PY:-python3}"
DB="${DB:-data/vendor_intelligence.db}"
PORT="${PORT:-8000}"
case "${1:-demo}" in
  install)      $PY -m pip install -r requirements.txt ;;
  seed)         $PY -m vi.seed.generate --db "$DB" --seed 42 ;;
  build-facts)  $PY -m vi.facts.build --db "$DB" ;;
  serve)        $PY -m vi.api --db "$DB" --port "$PORT" ;;
  test)         if $PY -c "import pytest" 2>/dev/null; then $PY -m pytest -q tests; else $PY -m unittest discover -s tests -v; fi ;;
  demo)         "$0" seed && "$0" build-facts && "$0" serve ;;
  clean)        rm -rf data/*.db data/*.db-* ;;
  *)            echo "usage: $0 {demo|seed|build-facts|serve|test|install|clean}"; exit 1 ;;
esac
