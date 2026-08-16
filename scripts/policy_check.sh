#!/usr/bin/env bash
# ADF framework repository policy checks.
#
# ONE implementation, THREE callers:
#   .githooks/pre-commit        — staged files, fast, blocks the commit
#   .github/workflows/ci.yml    — whole tree, unbypassable
#   manual: scripts/policy_check.sh [--staged]
#
# WHY BOTH A HOOK AND CI: `git commit --no-verify` skips every hook, and hooks
# live in per-clone local config. A policy enforced only by a hook is a policy on
# the honour system.
#
# Self-contained by design. This repo depends on nothing outside itself, so this
# script is DUPLICATED (not shared) across the three products — sharing it would
# itself be the cross-repo dependency POLICY 2 forbids.
set -uo pipefail

MODE="${1:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FAIL=0

if [[ "$MODE" == "--staged" ]]; then
  FILES=$(git diff --cached --name-only --diff-filter=ACMR)
  SCOPE="staged"
else
  FILES=$(git ls-files)
  SCOPE="tracked tree"
fi
[[ -z "$FILES" ]] && { echo "policy_check: nothing to check"; exit 0; }

say()  { printf '  %s\n' "$1"; }
fail() { printf '\nPOLICY VIOLATION: %s\n' "$1"; FAIL=1; }
content_of() { if [[ "$MODE" == "--staged" ]]; then git show ":$1" 2>/dev/null; else cat "$1" 2>/dev/null; fi; }

# Files that necessarily NAME the patterns they police.
is_self() {
  case "$1" in
    .githooks/*|scripts/policy_check.sh|scripts/test_policy_check.sh) return 0 ;;
    *) return 1 ;;
  esac
}
# Test fixtures may legitimately use a sample domain — framework BEHAVIOUR may not.
is_test() {
  case "$1" in
    */test/*|*/test_*|test_*|*_test.dart|*_test.py|*/tests/*) return 0 ;;
    *) return 1 ;;
  esac
}

# ---------------------------------------------------------------- POLICY 1
# NO PRODUCT DOMAIN KNOWLEDGE IN GENERIC CODE.
# This framework builds arbitrary apps. It has leaked in BOTH directions: every
# test-agent prompt once asserted the app under test was a Canadian drug
# submission portal, and the gates once grepped for POS order schema. Ask of any
# new check, prompt or default: would this still be correct for an app in a
# completely different domain?
DOMAIN='\bANDS\b|Abbreviated New Drug|eCTD|CESG|dossier-ID|DELETE FROM orders|is_deleted'
HITS=""
for f in $FILES; do
  is_self "$f" && continue
  is_test "$f" && continue
  case "$f" in
    docs/*|*.md|apps/*|.adf-proof.json|*/.adf-proof.json) continue ;;   # prose, generated apps, records
    scripts/orch/ands_*|scripts/ands/*) continue ;;                     # explicitly product-scoped tools
  esac
  case "$f" in
    scripts/*|tools/*|templates/*|lib/*|bin/*|install/*|orchestration/*) ;;
    *) continue ;;
  esac
  content_of "$f" | grep -qE "$DOMAIN" && HITS="$HITS $f"
done
[[ -n "$HITS" ]] && { fail "product domain knowledge in generic framework code"
                      for f in $HITS; do say "$f"; done
                      say "This builds arbitrary apps — it must not assume what the app IS."
                      say "Move it to the consumer repo, or phrase it generically."; }

# ---------------------------------------------------------------- POLICY 2
# NO CROSS-REPO / ABSOLUTE PATHS. Twelve config files once pointed at a deleted
# vendored location and kept doing so silently. Prefer self-locating paths.
PHITS=""
for f in $FILES; do
  is_self "$f" && continue
  case "$f" in docs/*|*.md) continue ;; esac
  content_of "$f" | grep -qE '/Users/[^/]+/(ai_pos_system|ands-platform)' && PHITS="$PHITS $f"
done
[[ -n "$PHITS" ]] && { fail "absolute path into another repository"
                       for f in $PHITS; do say "$f"; done
                       say 'Use $(git rev-parse --show-toplevel) or a path relative to this file.'; }

# ---------------------------------------------------------------- POLICY 3
# ORCH_REPO_ROOT CONTRACT. A gate that resolves its scan root only from its own
# location scans THIS repo when a consumer invokes it, finds nothing, prints PASS
# and exits 0 — a false green indistinguishable from a real pass by exit code.
# v3.1.0 shipped exactly that and silently disabled a consumer's merge gate.
for f in $FILES; do
  case "$f" in scripts/orch/*_gate.sh) ;; *) continue ;; esac
  c=$(content_of "$f"); [[ -z "$c" ]] && continue
  if ! printf '%s' "$c" | grep -q 'ORCH_REPO_ROOT'; then
    fail "gate does not honour ORCH_REPO_ROOT: $f"
    say 'Required: ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"'
    say "Without it a consumer gets a PASS having scanned nothing."
  fi
done

# ---------------------------------------------------------------- POLICY 4
# NO .cursor/orchestration REGRESSION. While it coexisted with .adf/orchestration
# the Dart and Python resolvers disagreed, so LearningStore wrote to one path and
# agent_runner.py read the other — recall returned nothing on every build.
# Matches BOTH the slash form and the join form; the latter evades a naive grep
# and mkdir -p's on write, so the directory reappears silently.
CHITS=""
for f in $FILES; do
  is_self "$f" && continue
  case "$f" in docs/activity-log/*|docs/ARCHIVE*|*.adf-proof.json|docs/gaps/*|README.md|*/README.md) continue ;; esac
  content_of "$f" | grep -qE '\.cursor/orchestration|"\.cursor"[,[:space:]]*"orchestration"|'"'"'\.cursor'"'"'[,[:space:]]*'"'"'orchestration'"'"'' \
    && CHITS="$CHITS $f"
done
[[ -n "$CHITS" ]] && { fail "legacy .cursor/orchestration path reintroduced"
                       for f in $CHITS; do say "$f"; done
                       say "Use .adf/orchestration. The split-brain it caused killed learning recall."; }

# ---------------------------------------------------------------- POLICY 5
# NO LIVE SECRETS. The repo is PUBLIC, so anything committed is permanently
# disclosed. The known synthetic policy-gate fixture is allowed by name.
SHITS=""
for f in $FILES; do
  is_self "$f" && continue
  case "$f" in docs/*|*policy_gate*|*proof_check*) continue ;; esac
  content_of "$f" | grep -qE '(gsk_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9-]{20,}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY)' \
    && SHITS="$SHITS $f"
done
[[ -n "$SHITS" ]] && { fail "possible live credential (this repo is PUBLIC)"
                       for f in $SHITS; do say "$f"; done; }

# ---------------------------------------------------------------- POLICY 6
# ACTIVITY LOG (staged mode only).
if [[ "$MODE" == "--staged" ]]; then
  CODE=$(printf '%s\n' "$FILES" | grep -E '^(scripts|tools|lib|bin|install|templates|\.github)/' || true)
  LOG=$(printf '%s\n' "$FILES" | grep -E '^docs/activity-log/' || true)
  [[ -n "$CODE" && -z "$LOG" ]] && { fail "code changed but docs/activity-log/ was not updated"
                                     say "changed: $(printf '%s\n' "$CODE" | head -3 | tr '\n' ' ')"; }
fi

if [[ $FAIL -ne 0 ]]; then
  printf '\npolicy_check FAILED (%s). See CLAUDE.md.\n' "$SCOPE"
  printf 'Hook bypass: git commit --no-verify (say why). CI runs this too.\n\n'
  exit 1
fi
echo "policy_check: PASS ($SCOPE)"
