#!/usr/bin/env bash
# Run every service + gateway test suite with the platform venv.
# Mirrors what CI does; the SQLite + in-memory-bus adapters make it infra-free.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "platform venv missing — create with:"
  echo "  python3 -m venv $HERE/.venv && $HERE/.venv/bin/pip install -r $HERE/requirements-dev.txt"
  exit 2
fi

fail=0
for suite in services/identity services/collaboration services/dossier services/validation services/lifecycle services/fees services/transmission services/governance services/readiness services/registry services/webhooks gateway integration; do
  echo "== $suite =="
  "$PY" -m pytest "$HERE/$suite" -q || fail=1
done

if [ "$fail" -eq 0 ]; then echo "ALL SUITES GREEN"; else echo "SUITES FAILED"; fi
exit $fail
