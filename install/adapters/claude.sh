#!/usr/bin/env bash
set -euo pipefail
FRAMEWORK_ROOT="$1"
TARGET="$2"
mkdir -p "$TARGET/.adf" "$TARGET/.claude/skills"
ln -sfn "$FRAMEWORK_ROOT/orchestration" "$TARGET/.adf/orchestration"
for skill in "$FRAMEWORK_ROOT/skills"/*; do
  name="$(basename "$skill")"
  ln -sfn "$skill" "$TARGET/.claude/skills/$name"
done
cp -f "$FRAMEWORK_ROOT/AGENTS.md" "$TARGET/AGENTS.md"
{
  echo "# ADF v3 (Claude Code)"
  cat "$FRAMEWORK_ROOT/orchestration/ADF.md"
} > "$TARGET/CLAUDE.md"
echo "Claude: CLAUDE.md + .claude/skills/"
