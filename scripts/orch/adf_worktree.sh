#!/usr/bin/env bash
# Git worktree per micro-task (Principle E).
set -euo pipefail

CMD="${1:-}"
FEATURE_ID="${2:-}"
TASK_ID="${3:-}"

if [[ -z "$CMD" || -z "$FEATURE_ID" || -z "$TASK_ID" ]]; then
  echo "Usage: $0 create|destroy|path <feature-id> <task-id> [command...]" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WT_ROOT="$ROOT/.cursor/orchestration/worktrees/$FEATURE_ID"
WT_PATH="$WT_ROOT/$TASK_ID"
BRANCH="adf/$FEATURE_ID/$TASK_ID"

mkdir -p "$WT_ROOT"

case "$CMD" in
  create)
    if [[ -d "$WT_PATH" ]]; then
      echo "worktree exists: $WT_PATH"
      exit 0
    fi
    git -C "$ROOT" worktree add -B "$BRANCH" "$WT_PATH" HEAD
    echo "$WT_PATH"
    ;;
  destroy)
    if [[ -d "$WT_PATH" ]]; then
      git -C "$ROOT" worktree remove --force "$WT_PATH" 2>/dev/null || rm -rf "$WT_PATH"
      git -C "$ROOT" branch -D "$BRANCH" 2>/dev/null || true
    fi
    ;;
  path)
    if [[ ! -d "$WT_PATH" ]]; then
      echo "worktree missing; run: $0 create $FEATURE_ID $TASK_ID" >&2
      exit 1
    fi
    echo "$WT_PATH"
    ;;
  run)
    shift 3
    if [[ ! -d "$WT_PATH" ]]; then
      "$0" create "$FEATURE_ID" "$TASK_ID"
    fi
    (cd "$WT_PATH" && "$@")
    ;;
  *)
    echo "Unknown command: $CMD" >&2
    exit 1
    ;;
esac
