#!/usr/bin/env bash
set -euo pipefail
# Cursor: symlink orchestration, skills, hooks from ADF package
FRAMEWORK_ROOT="$1"
TARGET="$2"
link_dir() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [[ -e "$dest" && ! -L "$dest" ]]; then
    # A real directory already exists (e.g. the server created runtime state
    # before install ran). Merge: link each framework entry that is missing,
    # leave everything already there untouched.
    local merged=0 entry name
    for entry in "$src"/*; do
      name="$(basename "$entry")"
      if [[ ! -e "$dest/$name" ]]; then
        ln -sfn "$entry" "$dest/$name"
        merged=$((merged + 1))
      fi
    done
    echo "merged $merged framework entries into existing $dest"
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
