#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(cat "$ROOT/VERSION")"
mkdir -p "$ROOT/dist"

# Never ship secrets, local runner config, or runtime telemetry in a release.
EXCLUDES=(
  --exclude='.git' --exclude='dist' --exclude='build' --exclude='.dart_tool'
  --exclude='.env' --exclude='.env.*'
  --exclude='runner.env' --exclude='.adf/runner.env'
  --exclude='*.jsonl' --exclude='otel-session.json'
)

tar -czf "$ROOT/dist/adf-framework-${VERSION}.tar.gz" "${EXCLUDES[@]}" \
  -C "$(dirname "$ROOT")" "$(basename "$ROOT")" 2>/dev/null || \
tar -czf "$ROOT/dist/adf-framework-${VERSION}.tar.gz" "${EXCLUDES[@]}" -C "$ROOT" .
echo "dist/adf-framework-${VERSION}.tar.gz"
