#!/usr/bin/env bash
# Self-contained test for the micro-change fast path. Builds a throwaway git
# repo with a small Dart dependency graph + synthetic lcov, then asserts
# detection, blast radius, and scoped coverage behave. Needs only bash+git+python3.
set -uo pipefail

ORCH_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { echo "  ok: $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- scaffold a fake project --------------------------------------------------
mkdir -p "$WORK/lib/services" "$WORK/lib/screens" "$WORK/lib/models" "$WORK/coverage" "$WORK/scripts/orch"
cp "$ORCH_DIR/change_scope.sh" "$WORK/scripts/orch/"
cp "$ORCH_DIR/coverage_gate.sh" "$WORK/scripts/orch/"
cp "$ORCH_DIR/security_gate.sh" "$WORK/scripts/orch/"
cp "$ORCH_DIR/blast_radius.sh" "$WORK/scripts/orch/"
cp "$ORCH_DIR/micro_change_detect.sh" "$WORK/scripts/orch/"
chmod +x "$WORK/scripts/orch/"*.sh

cat > "$WORK/pubspec.yaml" <<'YML'
name: ai_pos_system
YML

# order_sync (the file we'll edit) <- imported by checkout_screen and order_repo
cat > "$WORK/lib/services/order_sync.dart" <<'DART'
class OrderSync {
  int retryLimit = 3;
}
DART
cat > "$WORK/lib/screens/checkout_screen.dart" <<'DART'
import 'package:ai_pos_system/services/order_sync.dart';
class CheckoutScreen {}
DART
cat > "$WORK/lib/models/order_repo.dart" <<'DART'
import '../services/order_sync.dart';
class OrderRepo {}
DART
# an unrelated, deliberately UNCOVERED file that must NOT block a micro change
cat > "$WORK/lib/models/legacy_unrelated.dart" <<'DART'
class Legacy { int x = 0; }
DART

# synthetic lcov: order_sync + its two importers are 100%; legacy is 0%
cat > "$WORK/coverage/lcov.info" <<'LCOV'
SF:lib/services/order_sync.dart
LF:2
LH:2
end_of_record
SF:lib/screens/checkout_screen.dart
LF:1
LH:1
end_of_record
SF:lib/models/order_repo.dart
LF:1
LH:1
end_of_record
SF:lib/models/legacy_unrelated.dart
LF:5
LH:0
end_of_record
LCOV

( cd "$WORK"
  git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm base
  # the one-line change: bump retryLimit 3 -> 5
  sed -i.bak 's/retryLimit = 3/retryLimit = 5/' lib/services/order_sync.dart && rm -f lib/services/order_sync.dart.bak
)

export ORCH_REPO_ROOT="$WORK"

echo "=== 1. micro detection ==="
# Capture to a file OUTSIDE the repo so it doesn't register as a change itself.
DET="$WORK.det.json"
"$WORK/scripts/orch/micro_change_detect.sh" --json > "$DET"
cat "$DET"
if grep -q '"micro":true' "$DET"; then
  ok "one-line change detected as micro"
else
  bad "one-line change should be micro"
fi
grep -q '"changed_files":1' "$DET" && ok "changed_files=1" || bad "changed_files should be 1"
rm -f "$DET"

echo "=== 2. blast radius ==="
BR="$("$WORK/scripts/orch/blast_radius.sh")"
echo "$BR" | grep -q 'lib/services/order_sync.dart' && ok "includes changed file" || bad "missing changed file"
echo "$BR" | grep -q 'lib/screens/checkout_screen.dart' && ok "found package: importer" || bad "missing package importer"
echo "$BR" | grep -q 'lib/models/order_repo.dart' && ok "found relative importer" || bad "missing relative importer"
echo "$BR" | grep -q 'legacy_unrelated' && bad "unrelated file should NOT be in blast radius" || ok "unrelated file excluded"

echo "=== 3. coverage gate auto-scopes (micro) — unrelated 0% file must not fail ==="
OUT="$("$WORK/scripts/orch/coverage_gate.sh" my-fix 100 2>&1)"; RC=$?
echo "$OUT" | sed 's/^/    /'
[[ $RC -eq 0 ]] && ok "micro coverage gate PASSED despite legacy 0%" || bad "micro gate should pass (rc=$RC)"
echo "$OUT" | grep -q 'micro mode' && ok "ran in micro mode" || bad "did not select micro mode"
echo "$OUT" | grep -q 'PASS: lib/services/order_sync.dart' && ok "enforced 100% on changed file" || bad "changed file not enforced"

echo "=== 4. forcing repo mode still fails on the uncovered legacy file ==="
OUT2="$(ADF_SCOPE_MODE=repo "$WORK/scripts/orch/coverage_gate.sh" my-fix 100 --mode=repo 2>&1)"; RC2=$?
[[ $RC2 -ne 0 ]] && ok "repo mode correctly FAILS on legacy 0%" || bad "repo mode should fail"
echo "$OUT2" | grep -q 'FAIL: lib/models/legacy_unrelated.dart' && ok "legacy file flagged in repo mode" || bad "legacy not flagged"

echo "=== 5. enforcing dependents (ADF_MICRO_COVER_DEPS=1) still passes (deps are 100%) ==="
OUT3="$(ADF_MICRO_COVER_DEPS=1 "$WORK/scripts/orch/coverage_gate.sh" my-fix 100 2>&1)"; RC3=$?
[[ $RC3 -eq 0 ]] && ok "dependents enforced and pass" || { bad "should pass"; echo "$OUT3" | sed 's/^/    /'; }
echo "$OUT3" | grep -q 'PASS: lib/screens/checkout_screen.dart' && ok "dependent checked when enforced" || bad "dependent not checked"

echo "=== 6. non-micro change uses full repo gate (and fails on legacy) ==="
( cd "$WORK"
  printf '\n// pad\nclass A{}\nclass B{}\nclass C{}\nclass D{}\nclass E{}\nclass F{}\nclass G{}\nclass H{}\nclass I{}\nclass J{}\nclass K{}\n' >> lib/services/order_sync.dart )
OUT4="$("$WORK/scripts/orch/coverage_gate.sh" my-fix 100 2>&1)"; RC4=$?
echo "$OUT4" | grep -q 'micro mode' && bad "12-line change should NOT be micro" || ok "large change not treated as micro"
[[ $RC4 -ne 0 ]] && ok "large change hits full gate (fails on legacy)" || bad "expected full-gate failure"

echo ""
echo "RESULT: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
