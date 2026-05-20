#!/usr/bin/env bash
set -euo pipefail
FRAMEWORK_ROOT="$1"
TARGET="$2"
mkdir -p "$TARGET/.adf" "$TARGET/.windsurf/rules"
ln -sfn "$FRAMEWORK_ROOT/orchestration" "$TARGET/.adf/orchestration"
cp -f "$FRAMEWORK_ROOT/AGENTS.md" "$TARGET/AGENTS.md"
{
  echo "# ADF v3 rules"
  cat "$FRAMEWORK_ROOT/orchestration/constitution.md" 2>/dev/null | head -80
} > "$TARGET/.windsurf/rules/adf.md"
echo "Windsurf: rules in .windsurf/rules/adf.md"
