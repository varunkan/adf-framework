#!/usr/bin/env bash
set -euo pipefail
# Claude Code adapter: CLAUDE.md, skills, and a Claude-flavoured runner.env.
FRAMEWORK_ROOT="$1"
TARGET="$2"
RUNNER="${3:-claude}"

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

# Drive the orchestration server with the Claude Code CLI by default.
"$FRAMEWORK_ROOT/install/write_runner_env.sh" "$TARGET" "${RUNNER:-claude}"

echo "Claude: CLAUDE.md + .claude/skills/ + .adf/runner.env (ADF_RUNNER=${RUNNER:-claude})"
