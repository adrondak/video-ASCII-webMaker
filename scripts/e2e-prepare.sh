#!/usr/bin/env bash
# Build the films used by the Playwright suite into dist/e2e/ and serve them.
# Playwright runs this as its webServer (see playwright.config.mjs).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
port="${1:-8790}"
scripts/make-fixture.sh tests/fixtures > /dev/null
"$PY" -m encoder.cli encode tests/fixtures/landscape.mp4 -o dist/e2e/silent --columns 120 \
  --title "E2E silent" --description "Synthetic test film" --force 2> /dev/null
exec "$PY" scripts/serve.py dist/e2e "$port"
