#!/usr/bin/env bash
# ADF v3 path resolution — source: . "$(adf-framework/lib/resolve_paths.sh)"
adf_resolve_repo_root() {
  if [[ -n "${ORCH_REPO_ROOT:-}" ]]; then echo "$(cd "$ORCH_REPO_ROOT" && pwd)"; return 0; fi
  local dir="$(pwd)"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.cursor/orchestration" || -d "$dir/adf-framework/orchestration" || -d "$dir/.adf/orchestration" ]]; then echo "$dir"; return 0; fi
    if [[ -f "$dir/.adf-install.json" ]]; then echo "$dir"; return 0; fi
    dir="$(dirname "$dir")"
  done
  echo "ADF: set ORCH_REPO_ROOT or run: adf install" >&2; return 1
}
adf_orchestration_dir() {
  local root="${1:-$(adf_resolve_repo_root)}"
  if [[ -n "${ORCH_ORCHESTRATION_DIR:-}" ]]; then echo "$(cd "$ORCH_ORCHESTRATION_DIR" && pwd)"; return 0; fi
  if [[ -f "$root/.adf-install.json" ]]; then
    local rel; rel="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('orchestration_dir',''))" "$root/.adf-install.json" 2>/dev/null || true)"
    [[ -n "$rel" && -d "$root/$rel" ]] && { echo "$(cd "$root/$rel" && pwd)"; return 0; }
  fi
  for rel in .cursor/orchestration adf-framework/orchestration .adf/orchestration; do
    [[ -d "$root/$rel" ]] && { echo "$(cd "$root/$rel" && pwd)"; return 0; }
  done
  echo "$root/.cursor/orchestration"
}
adf_features_dir() { echo "$(adf_orchestration_dir "$1")/features"; }
adf_framework_root() {
  local root="${1:-$(adf_resolve_repo_root)}"
  [[ -d "$root/adf-framework" ]] && { echo "$(cd "$root/adf-framework" && pwd)"; return 0; }
  echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
}
