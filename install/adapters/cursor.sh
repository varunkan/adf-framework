#!/usr/bin/env bash
set -euo pipefail
# Cursor: symlink orchestration, skills, hooks from ADF package
FRAMEWORK_ROOT="$1"
TARGET="$2"
link_dir() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [[ -e "$dest" && ! -L "$dest" ]]; then
    echo "SKIP (exists): $dest — remove manually to reinstall" >&2
    return 0
  fi
  ln -sfn "$src" "$dest"
  echo "linked $dest -> $src"
}
link_dir "$FRAMEWORK_ROOT/orchestration" "$TARGET/.cursor/orchestration"
link_dir "$FRAMEWORK_ROOT/skills" "$TARGET/.cursor/skills"
mkdir -p "$TARGET/.cursor"
link_dir "$FRAMEWORK_ROOT/hooks" "$TARGET/.cursor/hooks"
cp -f "$FRAMEWORK_ROOT/hooks.json" "$TARGET/.cursor/hooks.json"
cp -f "$FRAMEWORK_ROOT/AGENTS.md" "$TARGET/AGENTS.md"
