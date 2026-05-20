#!/usr/bin/env bash
# Seed ADF v3 artifacts for a feature.
set -euo pipefail

FEATURE_ID="${1:-}"
if [[ -z "$FEATURE_ID" ]]; then
  echo "Usage: $0 <feature-id>" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SPECS="$ROOT/specs/$FEATURE_ID"
FEATURE="$ROOT/.cursor/orchestration/features/$FEATURE_ID"
TPL="$ROOT/.cursor/orchestration/templates"

mkdir -p "$SPECS/tasks" "$SPECS/checklists" "$FEATURE/judge-verdicts"

copy_if_missing() {
  local src="$1" dest="$2"
  if [[ ! -f "$dest" ]]; then
    cp "$src" "$dest"
    echo "created $dest"
  fi
}

substitute() {
  local src="$1" dest="$2"
  if [[ ! -f "$dest" ]]; then
    sed "s/{{FEATURE_ID}}/$FEATURE_ID/g; s/{{FEATURE_TITLE}}/$FEATURE_ID/g" "$src" > "$dest"
    echo "created $dest"
  fi
}

substitute "$TPL/01-spec.template.md" "$SPECS/spec.md"
if [[ ! -f "$SPECS/task-graph.yaml" ]]; then
  sed "s/{{FEATURE_ID}}/$FEATURE_ID/g" "$TPL/task-graph.template.yaml" > "$SPECS/task-graph.yaml"
  echo "created $SPECS/task-graph.yaml"
fi
sed "s/{{FEATURE_ID}}/$FEATURE_ID/g; s/task-NNN/task-001/g; s/{{TITLE}}/Bootstrap task/g" \
  "$TPL/micro-task.template.md" > "$SPECS/tasks/task-001.md" 2>/dev/null || true
if [[ ! -f "$SPECS/tasks/task-001.md" ]]; then
  cp "$TPL/micro-task.template.md" "$SPECS/tasks/task-001.md"
fi

if [[ ! -f "$SPECS/tasks.md" ]]; then
  cat > "$SPECS/tasks.md" <<EOF
# Tasks — $FEATURE_ID

See \`task-graph.yaml\` and \`tasks/*.md\` for micro-task DAG (ADF v3).
EOF
  echo "created $SPECS/tasks.md"
fi

if [[ ! -f "$SPECS/plan.md" ]]; then
  echo "# Plan — $FEATURE_ID" > "$SPECS/plan.md"
  echo "created $SPECS/plan.md"
fi

if [[ ! -f "$SPECS/chatroom.log" ]]; then
  echo "# ADF chatroom — $FEATURE_ID" > "$SPECS/chatroom.log"
  echo "created $SPECS/chatroom.log"
fi

if [[ ! -f "$SPECS/lessons-learned.md" ]]; then
  echo "# Lessons learned — $FEATURE_ID" > "$SPECS/lessons-learned.md"
  echo "created $SPECS/lessons-learned.md"
fi

copy_if_missing "$TPL/06-traceability-matrix.template.md" "$FEATURE/06-traceability-matrix.md"

echo "ADF artifacts seeded for $FEATURE_ID"
