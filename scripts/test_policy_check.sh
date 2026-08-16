#!/usr/bin/env bash
# Tests for scripts/policy_check.sh (ADF framework).
#
# Each case builds a throwaway git repo, plants a violation (or a clean tree),
# stages it, runs the checker, and asserts the exit code. Both directions are
# asserted: violations blocked AND legitimate work allowed. A guardrail never
# tested against a real violation is one nobody has proven works.
#
# Usage: bash scripts/test_policy_check.sh
set -uo pipefail

CHECKER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/policy_check.sh"
PASS=0; FAIL=0

setup_repo() {
  local d; d=$(mktemp -d)
  git -C "$d" init -q
  git -C "$d" config user.email t@t; git -C "$d" config user.name t
  mkdir -p "$d/scripts/orch" "$d/tools/orchestration_server/lib" "$d/lib" "$d/docs/activity-log" "$d/templates"
  cp "$CHECKER" "$d/scripts/policy_check.sh"
  # a gate that DOES honour the external-root contract
  printf '#!/usr/bin/env bash\nROOT="${ORCH_REPO_ROOT:-$(pwd)}"\necho ok\n' > "$d/scripts/orch/security_gate.sh"
  echo "log" > "$d/docs/activity-log/ACTIVITY_LOG.md"
  git -C "$d" add -A >/dev/null 2>&1; git -C "$d" commit -qm base >/dev/null 2>&1
  echo "$d"
}

assert() {
  local name="$1" expect="$2" d="$3"
  ( cd "$d" && bash scripts/policy_check.sh --staged >/dev/null 2>&1 )
  local rc=$?
  local got; [[ $rc -ne 0 ]] && got=block || got=allow
  if [[ "$got" == "$expect" ]]; then
    printf '  PASS  %-56s (%s)\n' "$name" "$got"; PASS=$((PASS+1))
  else
    printf '  FAIL  %-56s expected %s, got %s\n' "$name" "$expect" "$got"; FAIL=$((FAIL+1))
  fi
  rm -rf "$d"
}

echo "=== policy_check.sh (adf-framework) ==="

# P1 NO PRODUCT DOMAIN KNOWLEDGE IN GENERIC CODE.
# Both directions of this leaked in real life: ANDS regulatory terms were baked
# into every test-agent prompt, and POS order/schema terms into the gates.
d=$(setup_repo); printf 'p = "This is the Canada ANDS regulatory submission portal"\n' > "$d/scripts/orch/prompt.py"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P1 ANDS domain term in generic code" block "$d"

d=$(setup_repo); printf "final s = 'implement the eCTD validation rules';\n" > "$d/tools/orchestration_server/lib/x.dart"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P1 eCTD in framework code" block "$d"

d=$(setup_repo); printf "grep -n 'DELETE FROM orders' lib/\n" > "$d/scripts/orch/gate2.sh"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P1 POS schema term (DELETE FROM orders)" block "$d"

d=$(setup_repo); mkdir -p "$d/scripts/orch/test"; printf 'fixture = "eCTD module 1 sample"\n' > "$d/scripts/orch/test_web_scraper.py"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P1 domain term in a TEST fixture is allowed" allow "$d"

# P2 NO CROSS-REPO PATHS. Twelve config files pointed at a deleted vendored
# location and stayed broken silently.
d=$(setup_repo); printf 'ROOT=/Users/someone/ai_pos_system/adf-framework\n' > "$d/scripts/orch/p.sh"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P2 absolute path into another repo" block "$d"

d=$(setup_repo); printf 'ROOT="$(git rev-parse --show-toplevel)"\n' > "$d/scripts/orch/p.sh"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P2 self-locating path is allowed" allow "$d"

# P3 ORCH_REPO_ROOT CONTRACT. A gate that resolves ROOT only from its own
# location scans THIS repo instead of the consumer's, finds nothing, and prints
# PASS — a false green indistinguishable from a real one by exit code.
d=$(setup_repo); printf '#!/usr/bin/env bash\nROOT="$(cd "$(dirname "$0")/../.." && pwd)"\necho ok\n' > "$d/scripts/orch/coverage_gate.sh"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P3 gate without ORCH_REPO_ROOT support" block "$d"

d=$(setup_repo); printf '#!/usr/bin/env bash\nROOT="${ORCH_REPO_ROOT:-$(pwd)}"\necho ok\n' > "$d/scripts/orch/lint_gate.sh"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P3 gate honouring ORCH_REPO_ROOT" allow "$d"

# P4 NO .cursor/orchestration REGRESSION. Its coexistence with .adf/orchestration
# split the resolvers and silently killed learning recall.
d=$(setup_repo); printf 'p = ".cursor/orchestration/learnings.jsonl"\n' > "$d/scripts/orch/l.py"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P4 .cursor/orchestration reintroduced" block "$d"

d=$(setup_repo); printf 'p = os.path.join(".cursor", "orchestration", "x.jsonl")\n' > "$d/scripts/orch/l.py"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P4 .cursor built without a slash (grep-evading)" block "$d"

d=$(setup_repo); printf 'p = ".adf/orchestration/learnings.jsonl"\n' > "$d/scripts/orch/l.py"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P4 .adf/orchestration is the correct path" allow "$d"

# A README that DOCUMENTS the policy necessarily names the banned path.
d=$(setup_repo); mkdir -p "$d/.adf/orchestration"; \
  printf 'The legacy `.cursor/orchestration` path was removed; do not reintroduce it.\n' > "$d/.adf/orchestration/README.md"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P4 README prose documenting the ban is allowed" allow "$d"

# P5 secrets
d=$(setup_repo); printf 'K=gsk_abcdefghijklmnopqrstuvwxyz012345\n' > "$d/scripts/orch/c.py"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P5 live-looking gsk_ key" block "$d"

d=$(setup_repo); printf "K = 'sk-abcdEFGH1234567890ZXCVbnmQWERtyui'  # fixture\n" > "$d/scripts/orch/test_policy_gate.py"; \
  echo "e" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P5 known synthetic fixture is allowed" allow "$d"

# P6 activity log
d=$(setup_repo); echo "x" > "$d/scripts/orch/new.sh"; git -C "$d" add -A >/dev/null 2>&1
assert "P6 code change without a log entry" block "$d"

d=$(setup_repo); echo "x" > "$d/scripts/orch/new.sh"; \
  echo "entry" >> "$d/docs/activity-log/ACTIVITY_LOG.md"; git -C "$d" add -A >/dev/null 2>&1
assert "P6 code change WITH a log entry" allow "$d"

echo
echo "  passed=$PASS failed=$FAIL"
[[ $FAIL -eq 0 ]] || exit 1
