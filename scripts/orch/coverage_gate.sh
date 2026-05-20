#!/usr/bin/env bash
# L100 gate: feature-scoped or repo-wide line coverage.
# Usage: coverage_gate.sh <feature-id> [min_percent=100] [--mode=repo|feature|both]
set -euo pipefail

FEATURE_ID="${1:?Usage: coverage_gate.sh <feature-id> [min_percent] [--mode=repo|feature|both]}"
MIN_PCT="${2:-100}"
MODE="both"
if [[ "${3:-}" == --mode=* ]]; then
  MODE="${3#--mode=}"
elif [[ "${3:-}" == "--mode" && -n "${4:-}" ]]; then
  MODE="$4"
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FEAT_DIR="$ROOT/.cursor/orchestration/features/$FEATURE_ID"
STATE_FILE="$FEAT_DIR/state.json"
LCOV="$ROOT/coverage/lcov.info"
BASELINE="$ROOT/scripts/orch/coverage_baseline.json"

resolve_spec_dir() {
  local spec_rel="specs/$FEATURE_ID"
  if [[ -f "$STATE_FILE" ]] && command -v python3 >/dev/null 2>&1; then
    spec_rel="$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('spec_feature_dir','specs/$FEATURE_ID'))")"
  fi
  echo "$ROOT/$spec_rel"
}

resolve_tasks_file() {
  local spec_dir
  spec_dir="$(resolve_spec_dir)"
  if [[ -f "$spec_dir/tasks.md" ]]; then
    echo "$spec_dir/tasks.md"
  elif [[ -f "$FEAT_DIR/03-tasks.md" ]]; then
    echo "$FEAT_DIR/03-tasks.md"
  else
    echo ""
  fi
}

lcov_pct() {
  local f="$1"
  local lf lh
  lf=$(grep -A999 "^SF:.*${f//\//\\/}\$" "$LCOV" 2>/dev/null | grep '^LF:' | head -1 | cut -d: -f2 || echo 0)
  lh=$(grep -A999 "^SF:.*${f//\//\\/}\$" "$LCOV" 2>/dev/null | grep '^LH:' | head -1 | cut -d: -f2 || echo 0)
  if [[ "${lf:-0}" -eq 0 ]]; then
    echo "-1"
    return
  fi
  echo $(( lh * 100 / lf ))
}

is_baseline_allowed() {
  local f="$1"
  [[ ! -f "$BASELINE" ]] && return 1
  python3 - "$BASELINE" "$f" <<'PY' 2>/dev/null || return 1
import json, sys
from datetime import date
path, f = sys.argv[1], sys.argv[2]
with open(path) as fp:
    data = json.load(fp)
for entry in data.get("allowlist", []):
    if entry.get("path") == f:
        exp = entry.get("expires", "2099-12-31")
        if date.today().isoformat() <= exp:
            print("yes")
            sys.exit(0)
sys.exit(1)
PY
}

check_file() {
  local f="$1"
  local pct
  pct="$(lcov_pct "$f")"
  if [[ "$pct" == "-1" ]]; then
    if is_baseline_allowed "$f"; then
      echo "BASELINE: $f (no lcov data, allowlisted)"
      return 0
    fi
    echo "FAIL: no lcov data for $f"
    return 1
  fi
  if [[ "$pct" -lt "$MIN_PCT" ]]; then
    if is_baseline_allowed "$f"; then
      echo "BASELINE: $f ${pct}% < ${MIN_PCT}% (allowlisted until expiry)"
      return 0
    fi
    echo "FAIL: $f line coverage ${pct}% < ${MIN_PCT}%"
    return 1
  fi
  echo "PASS: $f ${pct}%"
  return 0
}

check_feature_mode() {
  local tasks fail=0
  tasks="$(resolve_tasks_file)"
  if [[ -z "$tasks" || ! -f "$tasks" ]]; then
    echo "WARN: no tasks.md for feature mode — skip feature L100"
    return 0
  fi
  echo "=== L100 feature mode ($tasks) ==="
  mapfile -t FILES < <(grep -oE '(lib|testcases)/[a-zA-Z0-9_./-]+\.dart' "$tasks" | sort -u || true)
  if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "WARN: no lib/ paths in tasks.md"
    return 0
  fi
  for f in "${FILES[@]}"; do
    [[ "$f" == testcases/* ]] && continue
    check_file "$f" || fail=1
  done
  return $fail
}

check_repo_mode() {
  local fail=0
  echo "=== L100 repo mode (lib/**/*.dart) ==="
  while IFS= read -r -d '' fpath; do
    local rel="${fpath#"$ROOT"/}"
    check_file "$rel" || fail=1
  done < <(find "$ROOT/lib" -name '*.dart' -print0 2>/dev/null)
  return $fail
}

if [[ ! -f "$LCOV" ]]; then
  echo "ERROR: run: flutter test testcases/ --coverage"
  exit 1
fi

FAIL=0
case "$MODE" in
  feature) check_feature_mode || FAIL=1 ;;
  repo) check_repo_mode || FAIL=1 ;;
  both)
    check_feature_mode || FAIL=1
    check_repo_mode || FAIL=1
    ;;
  *) echo "ERROR: unknown mode $MODE"; exit 1 ;;
esac

if [[ $FAIL -eq 0 ]]; then
  echo "PASS: coverage_gate ($MODE) for $FEATURE_ID at ${MIN_PCT}%"
else
  exit 1
fi
