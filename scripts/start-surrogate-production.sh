#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${AIOS_PYTHON:-.venv/bin/python}"
: "${AIOS_DOCS_ROOT:?Set AIOS_DOCS_ROOT to organizer data before starting production}"
aios surrogate-check --output out/surrogate-runtime.json
if [ ! -f frontend/dist/index.html ]; then
  echo 'Build the frontend first: cd frontend && npm ci && npm run build' >&2
  exit 2
fi
mkdir -p frontend/dist/data
cp out/surrogate-runtime.json frontend/dist/data/surrogate-runtime.json
exec aios web \
  --dist frontend/dist --host "${AIOS_HOST:-127.0.0.1}" --port "${AIOS_PORT:-18080}"
