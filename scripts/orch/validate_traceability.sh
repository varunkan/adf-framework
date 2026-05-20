#!/usr/bin/env bash
# R100 gate: every FR/NFR/US in spec.md appears in 06-traceability-matrix.md with TC-*.
set -euo pipefail

FEATURE_ID="${1:?Usage: validate_traceability.sh <feature-id>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FEAT_DIR="$ROOT/.cursor/orchestration/features/$FEATURE_ID"
STATE_FILE="$FEAT_DIR/state.json"
MATRIX="$FEAT_DIR/06-traceability-matrix.md"

SPEC_REL="specs/$FEATURE_ID"
if [[ -f "$STATE_FILE" ]] && command -v python3 >/dev/null 2>&1; then
  SPEC_REL="$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('spec_feature_dir','specs/$FEATURE_ID'))")"
fi
SPEC="$ROOT/$SPEC_REL/spec.md"
LEGACY_SPEC="$FEAT_DIR/01-spec.md"

if [[ -f "$SPEC" ]]; then
  SPEC_FILE="$SPEC"
elif [[ -f "$LEGACY_SPEC" ]]; then
  SPEC_FILE="$LEGACY_SPEC"
else
  echo "ERROR: missing spec at $SPEC or $LEGACY_SPEC"
  exit 1
fi

if [[ ! -f "$MATRIX" ]]; then
  echo "ERROR: missing $MATRIX"
  exit 1
fi

REQS=$(grep -oE '(FR|NFR|US)-[0-9]{3}' "$SPEC_FILE" | sort -u || true)
if [[ -z "$REQS" ]]; then
  echo "WARN: no FR/NFR/US IDs found in $SPEC_FILE"
  exit 0
fi

FAIL=0
while IFS= read -r req; do
  [[ -z "$req" ]] && continue
  if ! grep -q "$req" "$MATRIX"; then
    echo "FAIL: $req not in traceability matrix"
    FAIL=1
    continue
  fi
  if ! grep "$req" "$MATRIX" | grep -qE 'TC-[0-9]{3}'; then
    echo "FAIL: $req has no TC-* mapping in matrix"
    FAIL=1
  fi
done <<< "$REQS"

if [[ $FAIL -eq 0 ]]; then
  echo "PASS: R100 traceability for $FEATURE_ID (spec: $SPEC_FILE)"
else
  exit 1
fi
