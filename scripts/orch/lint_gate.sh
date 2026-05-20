#!/usr/bin/env bash
# Zero-tolerance static analysis on lib/ and testcases/.
set -euo pipefail

FEATURE_ID="${1:-_repo}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "=== lint_gate: flutter analyze --fatal-infos ==="
if ! flutter analyze --fatal-infos 2>&1 | tee /tmp/orch_lint_"$FEATURE_ID".log; then
  echo "FAIL: flutter analyze reported issues"
  exit 1
fi

if grep -qE '^\s*(error|warning|info)\s•' /tmp/orch_lint_"$FEATURE_ID".log 2>/dev/null; then
  echo "FAIL: analyze output contains issues"
  exit 1
fi

echo "PASS: lint_gate zero issues for $FEATURE_ID"
