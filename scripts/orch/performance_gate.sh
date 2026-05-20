#!/usr/bin/env bash
# Performance heuristics on lib/ (zero tolerance for listed anti-patterns).
set -euo pipefail

FEATURE_ID="${1:-_repo}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$ROOT/lib"
FAIL=0

echo "=== performance_gate ==="

# sleep in production lib (exclude test-only files if named)
if grep -rEn '\bsleep\s*\(' "$LIB" --include='*.dart' 2>/dev/null | grep -v test; then
  echo "FAIL: sleep() in lib/ production paths"
  FAIL=1
fi

# Synchronous file IO in widgets/services (heuristic)
if grep -rEn 'readAsStringSync|writeAsStringSync|readAsBytesSync' "$LIB" --include='*.dart' 2>/dev/null | grep -v '// orch:allow-sync-io'; then
  echo "FAIL: synchronous file IO in lib/ (add // orch:allow-sync-io if intentional)"
  FAIL=1
fi

# Unbounded retry without cap in order reload (heuristic)
if grep -rEn 'while\s*\(\s*true\s*\)' "$LIB" --include='*order*' 2>/dev/null; then
  echo "WARN: while(true) in order-related code — verify retry cap"
fi

if [[ $FAIL -eq 0 ]]; then
  echo "PASS: performance_gate for $FEATURE_ID"
else
  exit 1
fi
