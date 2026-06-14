#!/usr/bin/env bash
# Install ADF v3 into a project for a given IDE and agent runner.
# Usage:
#   install.sh --target DIR --ide cursor|vscode|windsurf|claude|generic|all
#              [--runner auto|cursor|claude|ollama|custom] [--framework DIR] [--global]
set -euo pipefail

IDE="cursor"
RUNNER=""        # empty → derive a sensible default from the IDE
TARGET=""
FRAMEWORK=""
GLOBAL=false

ALL_IDES=(cursor vscode windsurf claude generic)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target|-t) TARGET="$2"; shift 2 ;;
    --ide|-i) IDE="$2"; shift 2 ;;
    --runner|-r) RUNNER="$2"; shift 2 ;;
    --framework|-f) FRAMEWORK="$2"; shift 2 ;;
    --global|-g) GLOBAL=true; shift ;;
    -h|--help)
      echo "Usage: $0 --target DIR --ide cursor|vscode|windsurf|claude|generic|all [--runner auto|cursor|claude|ollama|custom] [--framework DIR]"
      exit 0 ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_FW="$(cd "$SCRIPT_DIR/.." && pwd)"
FRAMEWORK="${FRAMEWORK:-$DEFAULT_FW}"
VERSION="$(cat "$FRAMEWORK/VERSION" 2>/dev/null || echo 3.2.0)"

# Default runner per IDE when --runner not given (back-compat: cursor for cursor).
default_runner_for() {
  case "$1" in
    claude) echo "claude" ;;
    cursor) echo "cursor" ;;
    *) echo "auto" ;;
  esac
}

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

# Copy framework into project once (shared by every adapter).
FW_IN_PROJECT="$TARGET/adf-framework"
if [[ ! -d "$FW_IN_PROJECT" ]]; then
  rsync -a --exclude='.git' "$FRAMEWORK/" "$FW_IN_PROJECT/"
  echo "Copied framework to $FW_IN_PROJECT"
fi

# Resolve the list of IDEs to install.
if [[ "$IDE" == "all" || "$IDE" == "universal" ]]; then
  IDES=("${ALL_IDES[@]}")
else
  IDES=("$IDE")
fi

PRIMARY_IDE="${IDES[0]}"
EFFECTIVE_RUNNER="${RUNNER:-$(default_runner_for "$PRIMARY_IDE")}"

for ide in "${IDES[@]}"; do
  ADAPTER="$SCRIPT_DIR/adapters/$ide.sh"
  if [[ ! -x "$ADAPTER" ]]; then
    echo "ERROR: unknown IDE '$ide'. Supported: ${ALL_IDES[*]} all" >&2
    exit 1
  fi
  ide_runner="${RUNNER:-$(default_runner_for "$ide")}"
  # claude.sh accepts a runner arg; others take (framework, target).
  if [[ "$ide" == "claude" ]]; then
    "$ADAPTER" "$FW_IN_PROJECT" "$TARGET" "$ide_runner"
  else
    "$ADAPTER" "$FW_IN_PROJECT" "$TARGET"
  fi
done

# Always write a runner.env so `adf start` knows which CLI to drive.
"$FRAMEWORK/install/write_runner_env.sh" "$TARGET" "$EFFECTIVE_RUNNER" >/dev/null
echo "Runner: $EFFECTIVE_RUNNER (.adf/runner.env)"

# Manifest reflects the primary IDE's paths.
ORCH_DIR=".cursor/orchestration"
SKILLS_DIR=".cursor/skills"
HOOKS_FILE=".cursor/hooks.json"
case "$PRIMARY_IDE" in
  vscode|windsurf|generic|claude) ORCH_DIR=".adf/orchestration"; SKILLS_DIR=""; HOOKS_FILE="" ;;
esac
[[ "$PRIMARY_IDE" == claude ]] && SKILLS_DIR=".claude/skills"

IDES_JSON="$(printf '"%s",' "${IDES[@]}")"; IDES_JSON="[${IDES_JSON%,}]"

python3 - << PY
import json, datetime
m = {
  "schema": 1,
  "version": "$VERSION",
  "ide": "$PRIMARY_IDE",
  "ides": $IDES_JSON,
  "runner": "$EFFECTIVE_RUNNER",
  "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
  "framework_root": "adf-framework",
  "orchestration_dir": "$ORCH_DIR",
  "skills_dir": "$SKILLS_DIR" or None,
  "hooks_file": "$HOOKS_FILE" or None,
  "runner_env": ".adf/runner.env",
}
with open("$TARGET/.adf-install.json", "w") as f:
    json.dump(m, f, indent=2)
print("Wrote $TARGET/.adf-install.json")
PY

chmod +x "$FW_IN_PROJECT/scripts/orch/"*.sh "$FW_IN_PROJECT/scripts/"*.sh "$FW_IN_PROJECT/install/"*.sh 2>/dev/null || true
echo ""
echo "ADF $VERSION installed for ${IDES[*]} (runner: $EFFECTIVE_RUNNER) in $TARGET"
echo "  Next: cd $TARGET && set -a && . .adf/runner.env && set +a && ./adf-framework/bin/adf doctor"
