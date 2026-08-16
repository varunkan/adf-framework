#!/usr/bin/env bash
# Security heuristics for the app under test (zero tolerance for listed patterns).
# Domain-agnostic: this framework builds arbitrary apps, so nothing here may
# assume a particular product's schema or vocabulary.
set -euo pipefail

FEATURE_ID="${1:-_repo}"
ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
LIB="$ROOT/lib"
FAIL=0

# Auto-scope: on a micro change, scan only the changed files + their dependents
# instead of all of lib/. Default (non-micro) behaviour is unchanged.
# shellcheck source=/dev/null
. "$(dirname "$0")/change_scope.sh" 2>/dev/null || true
SCAN=("$LIB")
if declare -f adf_is_micro >/dev/null 2>&1 && adf_is_micro; then
  mapfile -t _aff < <(adf_affected_files)
  if (( ${#_aff[@]} )); then
    SCAN=(); for _f in "${_aff[@]}"; do SCAN+=("$ROOT/$_f"); done
    echo "=== security_gate (micro-scoped: ${#SCAN[@]} file(s)) ==="
  else
    echo "=== security_gate ==="
  fi
else
  echo "=== security_gate ==="
fi

# Hardcoded secrets (common patterns)
if grep -rEn '(api[_-]?key|secret|password)\s*=\s*['\''"][^'\''"]{8,}' "${SCAN[@]}" --include='*.dart' 2>/dev/null | grep -v '// ignore' | grep -v 'example'; then
  echo "FAIL: possible hardcoded secret in lib/"
  FAIL=1
fi

# Insecure HTTP (allow localhost in comments only via exclusion)
if grep -rEn 'http://' "${SCAN[@]}" --include='*.dart' 2>/dev/null | grep -v 'localhost' | grep -v '127.0.0.1' | grep -v '//'; then
  echo "FAIL: http:// in lib/ (use https)"
  FAIL=1
fi

# eval / dart:mirrors abuse
if grep -rEn 'dart:mirrors' "${SCAN[@]}" --include='*.dart' 2>/dev/null; then
  echo "FAIL: dart:mirrors in lib/"
  FAIL=1
fi

# Destructive SQL without a soft-delete guard. Advisory only — some raw deletes
# are legitimate cleanup, and the right policy is app-specific.
if grep -rEn 'hardDelete|DELETE[[:space:]]+FROM' "${SCAN[@]}" --include='*.dart' 2>/dev/null; then
  echo "WARN: destructive delete detected — verify the app's soft-delete policy"
fi

if [[ $FAIL -eq 0 ]]; then
  echo "PASS: security_gate for $FEATURE_ID"
else
  exit 1
fi
