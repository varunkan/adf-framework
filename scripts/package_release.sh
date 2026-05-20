#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(cat "$ROOT/VERSION")"
mkdir -p "$ROOT/dist"
tar -czf "$ROOT/dist/adf-framework-${VERSION}.tar.gz" -C "$(dirname "$ROOT")" "$(basename "$ROOT")" \
  --exclude='.git' --exclude='dist' --exclude='build' --exclude='.dart_tool' 2>/dev/null || \
tar -czf "$ROOT/dist/adf-framework-${VERSION}.tar.gz" \
  --exclude='.git' --exclude='dist' --exclude='build' --exclude='.dart_tool' -C "$ROOT" .
echo "dist/adf-framework-${VERSION}.tar.gz"
