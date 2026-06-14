#!/usr/bin/env bash
# micro_change_detect.sh — decide the track for the current working diff and
# persist the chosen verification scope.
#
# This is the "auto-detect tiny diffs" entry point: the orchestration pipeline
# (or a pre-gate step) calls it once; if the change is small it selects Track S
# and writes the affected-file set to .adf/change-scope.txt so the gates scope
# themselves. Exit code: 0 = micro (fast path), 1 = full pipeline.
#
# Usage:
#   ./scripts/orch/micro_change_detect.sh            # human summary
#   ./scripts/orch/micro_change_detect.sh --json     # machine-readable
set -euo pipefail

ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
# shellcheck source=/dev/null
. "$(dirname "$0")/change_scope.sh"

JSON=0
[[ "${1:-}" == "--json" ]] && JSON=1

nf="$(adf_changed_file_count)"
nl="$(adf_changed_line_count)"
affected="$(adf_affected_files)"
n_aff="$(printf '%s\n' $affected | grep -c . || true)"

if adf_is_micro; then
  TRACK="S"; MICRO=true
else
  TRACK="full"; MICRO=false
fi

# Persist the scope for downstream gates (best-effort).
SCOPE_DIR="$ROOT/.adf"
mkdir -p "$SCOPE_DIR" 2>/dev/null || true
{ printf '%s\n' $affected; } > "$SCOPE_DIR/change-scope.txt" 2>/dev/null || true

if [[ "$JSON" == 1 ]]; then
  printf '{"micro":%s,"track":"%s","changed_files":%s,"changed_lines":%s,"affected_files":%s,"scope_file":"%s"}\n' \
    "$MICRO" "$TRACK" "$nf" "$nl" "$n_aff" "$SCOPE_DIR/change-scope.txt"
else
  echo "=== micro_change_detect ==="
  echo "changed files:  $nf (max ${ADF_MICRO_MAX_FILES:-1})"
  echo "changed lines:  $nl (max ${ADF_MICRO_MAX_LINES:-10})"
  echo "affected files: $n_aff (changed + dependents @ depth ${ADF_BLAST_DEPTH:-1})"
  echo "track:          $TRACK"
  if [[ "$MICRO" == true ]]; then
    echo "→ fast path: light phases + auto-scoped gates. Scope written to .adf/change-scope.txt"
  else
    echo "→ full pipeline: spec → decompose → implement → review → repo-wide gates."
  fi
fi

[[ "$MICRO" == true ]]
