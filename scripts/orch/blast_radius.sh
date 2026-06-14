#!/usr/bin/env bash
# blast_radius.sh — "what does this change touch?"
#
# Prints the files affected by the current working diff: the changed lib files
# plus everything that imports them (out to ADF_BLAST_DEPTH hops). The single
# most useful thing to know before a one-line change in a large codebase.
#
# Usage:
#   ./scripts/orch/blast_radius.sh                 # current uncommitted change
#   ADF_DIFF_BASE=origin/main ./scripts/orch/blast_radius.sh
#   ADF_BLAST_DEPTH=2 ./scripts/orch/blast_radius.sh
set -euo pipefail

ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
# shellcheck source=/dev/null
. "$(dirname "$0")/change_scope.sh"

changed="$(adf_changed_dart_lib_files)"
deps="$(adf_dependent_files)"
nf="$(adf_changed_file_count)"
nl="$(adf_changed_line_count)"

echo "=== blast radius (base: ${ADF_DIFF_BASE:-HEAD}, depth: ${ADF_BLAST_DEPTH:-1}) ==="
echo "changed files: $nf   changed lines: $nl"

if [[ -z "$changed" ]]; then
  echo "no changed lib/*.dart files in the diff."
  exit 0
fi

echo ""
echo "changed:"
printf '  %s\n' $changed
echo ""
if [[ -n "$deps" ]]; then
  echo "dependents (importers, $(printf '%s\n' $deps | grep -c .)):"
  printf '  %s\n' $deps
else
  echo "dependents: none found (leaf file)"
fi

if adf_is_micro; then
  echo ""
  echo "→ MICRO change: gates will auto-scope to the files above."
else
  echo ""
  echo "→ not micro (exceeds ADF_MICRO_MAX_FILES/${ADF_MICRO_MAX_FILES:-1} or"
  echo "  ADF_MICRO_MAX_LINES/${ADF_MICRO_MAX_LINES:-10}); full repo gates apply."
fi
