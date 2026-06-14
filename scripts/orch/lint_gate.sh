#!/usr/bin/env bash
# Zero-tolerance static analysis on lib/ and testcases/.
set -euo pipefail

FEATURE_ID="${1:-_repo}"
ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
# shellcheck source=/dev/null
. "$(dirname "$0")/change_scope.sh" 2>/dev/null || true
cd "$ROOT"

# Auto-scope: analyze only the changed files + dependents on a micro change.
# `flutter/dart analyze` accepts explicit paths; with none it scans the project.
ANALYZE_PATHS=()
if declare -f adf_is_micro >/dev/null 2>&1 && adf_is_micro; then
  mapfile -t ANALYZE_PATHS < <(adf_affected_files)
fi

if (( ${#ANALYZE_PATHS[@]} )); then
  echo "=== lint_gate: flutter analyze --fatal-infos (micro-scoped: ${#ANALYZE_PATHS[@]} file(s)) ==="
else
  echo "=== lint_gate: flutter analyze --fatal-infos ==="
fi

if ! flutter analyze --fatal-infos "${ANALYZE_PATHS[@]}" 2>&1 | tee /tmp/orch_lint_"$FEATURE_ID".log; then
  echo "FAIL: flutter analyze reported issues"
  exit 1
fi

if grep -qE '^\s*(error|warning|info)\s•' /tmp/orch_lint_"$FEATURE_ID".log 2>/dev/null; then
  echo "FAIL: analyze output contains issues"
  exit 1
fi

echo "PASS: lint_gate zero issues for $FEATURE_ID"
