#!/usr/bin/env bash
set -euo pipefail
FRAMEWORK_ROOT="$1"
TARGET="$2"
mkdir -p "$TARGET/.adf" "$TARGET/.vscode" "$TARGET/.github"
ln -sfn "$FRAMEWORK_ROOT/orchestration" "$TARGET/.adf/orchestration"
cp -f "$FRAMEWORK_ROOT/AGENTS.md" "$TARGET/AGENTS.md"
if [[ ! -f "$TARGET/.github/copilot-instructions.md" ]]; then
  {
    echo "# ADF v3 — Copilot instructions"
    echo ""
    cat "$FRAMEWORK_ROOT/orchestration/ADF.md"
    echo ""
    echo "See AGENTS.md and .adf/orchestration/ for full pipeline."
  } > "$TARGET/.github/copilot-instructions.md"
  echo "created .github/copilot-instructions.md"
fi
cat > "$TARGET/.vscode/adf.settings.json" << JSON
{
  "adf.version": "$(cat "$FRAMEWORK_ROOT/VERSION")",
  "adf.orchestrationDir": ".adf/orchestration",
  "adf.apiPort": 3847,
  "adf.dashboardPort": 3848
}
JSON
echo "VS Code: use AGENTS.md + Copilot instructions; run API via adf start"
