#!/usr/bin/env bash
# Single command to run the ADF orchestration Python UNIT tests (offline — deps
# injected, no model/server). Gives the requirements-crew / swarm / router /
# scraper suites a CI entrypoint instead of being run ad hoc (DRIFT guard).
# Exits non-zero if any suite fails.
set -uo pipefail
cd "$(dirname "$0")"

SUITES=(
  test_model_router test_web_scraper test_doc_ingest
  test_requirements_crew test_clarify_swarm test_build_crew test_agent_runner
)

fail=0
for s in "${SUITES[@]}"; do
  [ -f "$s.py" ] || { printf "%-26s SKIP (missing)\n" "$s"; continue; }
  printf "%-26s " "$s"
  if out=$(python3 "$s.py" 2>&1); then
    echo "$out" | grep -oE "Ran [0-9]+ tests" | tail -1
  else
    echo "FAILED"
    echo "$out" | tail -8
    fail=1
  fi
done

[ "$fail" = 0 ] && echo "ALL OFFLINE ORCH SUITES PASSED" || echo "SOME SUITES FAILED"
exit $fail
