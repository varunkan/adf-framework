#!/usr/bin/env bash
set -euo pipefail
FRAMEWORK_ROOT="$1"
TARGET="$2"
mkdir -p "$TARGET/.adf"
ln -sfn "$FRAMEWORK_ROOT/orchestration" "$TARGET/.adf/orchestration"
cp -f "$FRAMEWORK_ROOT/AGENTS.md" "$TARGET/AGENTS.md"
echo "Generic: .adf/orchestration + AGENTS.md (any IDE with agent support)"
