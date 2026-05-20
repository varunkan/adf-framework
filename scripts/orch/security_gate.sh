#!/usr/bin/env bash
# POS security heuristics on lib/ (zero tolerance for listed patterns).
set -euo pipefail

FEATURE_ID="${1:-_repo}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$ROOT/lib"
FAIL=0

echo "=== security_gate ==="

# Hardcoded secrets (common patterns)
if grep -rEn '(api[_-]?key|secret|password)\s*=\s*['\''"][^'\''"]{8,}' "$LIB" --include='*.dart' 2>/dev/null | grep -v '// ignore' | grep -v 'example'; then
  echo "FAIL: possible hardcoded secret in lib/"
  FAIL=1
fi

# Insecure HTTP (allow localhost in comments only via exclusion)
if grep -rEn 'http://' "$LIB" --include='*.dart' 2>/dev/null | grep -v 'localhost' | grep -v '127.0.0.1' | grep -v '//'; then
  echo "FAIL: http:// in lib/ (use https)"
  FAIL=1
fi

# eval / dart:mirrors abuse
if grep -rEn 'dart:mirrors' "$LIB" --include='*.dart' 2>/dev/null; then
  echo "FAIL: dart:mirrors in lib/"
  FAIL=1
fi

# Order soft-delete: new deletes should use is_deleted pattern (advisory grep for .delete( without is_deleted nearby is noisy — check deleteOrder paths)
if grep -rEn 'hardDelete|DELETE FROM orders' "$LIB" --include='*.dart' 2>/dev/null; then
  echo "WARN: possible hard delete pattern — verify is_deleted soft-delete policy"
fi

if [[ $FAIL -eq 0 ]]; then
  echo "PASS: security_gate for $FEATURE_ID"
else
  exit 1
fi
