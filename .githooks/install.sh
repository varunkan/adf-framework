#!/usr/bin/env bash
# Activate this repo's tracked git hooks. Git does not run hooks from a tracked
# directory by default, which is why "we agreed the rule" has never been the same
# as "the rule is enforced".
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
chmod +x .githooks/pre-commit 2>/dev/null || true
git config core.hooksPath .githooks
echo "hooks installed: core.hooksPath = $(git config core.hooksPath)"
