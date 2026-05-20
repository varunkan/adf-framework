#!/usr/bin/env bash
# Install ADF v3 into a project for a given IDE.
# Usage: install.sh --target DIR --ide cursor|vscode|windsurf|claude|generic [--framework DIR] [--global]
set -euo pipefail

IDE="cursor"
TARGET=""
FRAMEWORK=""
GLOBAL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target|-t) TARGET="$2"; shift 2 ;;
    --ide|-i) IDE="$2"; shift 2 ;;
    --framework|-f) FRAMEWORK="$2"; shift 2 ;;
    --global|-g) GLOBAL=true; shift ;;
    -h|--help)
      echo "Usage: $0 --target DIR --ide cursor|vscode|windsurf|claude|generic [--framework DIR]"
      exit 0 ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_FW="$(cd "$SCRIPT_DIR/.." && pwd)"
FRAMEWORK="${FRAMEWORK:-$DEFAULT_FW}"
VERSION="$(cat "$FRAMEWORK/VERSION" 2>/dev/null || echo 3.1.0)"

if $GLOBAL; then
  INSTALL_ROOT="${ADF_HOME:-$HOME/.adf}/$VERSION"
  mkdir -p "$INSTALL_ROOT"
  rsync -a --exclude='.git' "$FRAMEWORK/" "$INSTALL_ROOT/"
  FRAMEWORK="$INSTALL_ROOT"
  ln -sfn "$INSTALL_ROOT" "${ADF_HOME:-$HOME/.adf}/current"
  echo "Global ADF $VERSION -> $INSTALL_ROOT"
  if [[ -z "$TARGET" ]]; then
    echo "Global install done. Run: adf install -t /path/to/project -i $IDE"
    exit 0
  fi
fi

if [[ -z "$TARGET" ]]; then
  echo "ERROR: --target required" >&2
  exit 1
fi

TARGET="$(cd "$TARGET" && pwd)"
ADAPTER="$SCRIPT_DIR/adapters/$IDE.sh"
if [[ ! -x "$ADAPTER" ]]; then
  echo "ERROR: unknown IDE '$IDE'. Supported: cursor vscode windsurf claude generic" >&2
  exit 1
fi

# Copy framework into project (or symlink if --link-only)
FW_IN_PROJECT="$TARGET/adf-framework"
if [[ ! -d "$FW_IN_PROJECT" ]]; then
  rsync -a --exclude='.git' "$FRAMEWORK/" "$FW_IN_PROJECT/"
  echo "Copied framework to $FW_IN_PROJECT"
fi

"$ADAPTER" "$FW_IN_PROJECT" "$TARGET"

# Manifest
ORCH_DIR=".cursor/orchestration"
SKILLS_DIR=".cursor/skills"
HOOKS_FILE=".cursor/hooks.json"
case "$IDE" in
  vscode|windsurf|generic|claude) ORCH_DIR=".adf/orchestration"; SKILLS_DIR=""; HOOKS_FILE="" ;;
esac
[[ "$IDE" == claude ]] && SKILLS_DIR=".claude/skills"

python3 - << PY
import json, datetime
m = {
  "schema": 1,
  "version": "$VERSION",
  "ide": "$IDE",
  "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
  "framework_root": "adf-framework",
  "orchestration_dir": "$ORCH_DIR",
  "skills_dir": "$SKILLS_DIR" or None,
  "hooks_file": "$HOOKS_FILE" or None,
}
with open("$TARGET/.adf-install.json", "w") as f:
    json.dump(m, f, indent=2)
print("Wrote $TARGET/.adf-install.json")
PY

chmod +x "$FW_IN_PROJECT/scripts/orch/"*.sh "$FW_IN_PROJECT/scripts/"*.sh 2>/dev/null || true
echo ""
echo "ADF $VERSION installed for $IDE in $TARGET"
echo "  Next: cd $TARGET && ./adf-framework/bin/adf doctor"
