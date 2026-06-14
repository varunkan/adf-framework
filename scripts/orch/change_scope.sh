#!/usr/bin/env bash
# change_scope.sh — ADF micro-change detection + blast-radius resolution.
#
# Sourced by the quality gates so a one-line change in a large repo gets
# *scoped* verification instead of repo-wide ceremony. Also runnable standalone
# via blast_radius.sh / micro_change_detect.sh.
#
# Contract: the caller sets $ROOT to the project root (the gates already do:
#   ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
# ). Every function operates relative to that root and prints lib/-relative
# paths (e.g. lib/services/order_sync.dart).
#
# Tunables (env):
#   ADF_DIFF_BASE        git ref to diff against (default: HEAD = uncommitted)
#   ADF_MICRO_MAX_FILES  max changed files to still count as "micro" (default 1)
#   ADF_MICRO_MAX_LINES  max changed lines (added+removed) for "micro" (default 10)
#   ADF_BLAST_DEPTH      how many import-hops of dependents to include (default 1)
#   ADF_SCOPE_MODE       auto|repo|off — force full gates (repo) or disable (off)
#   ADF_AFFECTED_FILES   newline/space list to use verbatim, skipping git/import
#                        discovery (useful for tests and CI overrides)

# Resolve project root if a caller forgot to set it.
: "${ROOT:=${ORCH_REPO_ROOT:-$(pwd)}}"

# --- helpers ----------------------------------------------------------------

adf_pkg_name() {
  grep -m1 '^name:' "$ROOT/pubspec.yaml" 2>/dev/null | awk '{print $2}'
}

# Paths that are build/coverage/runtime artifacts, never "source changes".
# A stray generated file must not flip a micro change into the full pipeline.
ADF_ARTIFACT_RE='^(coverage/|build/|\.dart_tool/|\.adf/|dist/|\.git/|node_modules/)'

# Files changed vs the base ref. Uncommitted (staged + unstaged) by default,
# plus untracked files so a brand-new one-liner still registers. Generated
# artifacts are filtered out either way.
adf_changed_files() {
  ( cd "$ROOT" 2>/dev/null || return 0
    local base="${ADF_DIFF_BASE:-HEAD}"
    git diff --name-only "$base" 2>/dev/null
    if [[ "$base" == "HEAD" ]]; then
      git ls-files --others --exclude-standard 2>/dev/null
    fi
  ) | sed '/^$/d' | grep -vE "$ADF_ARTIFACT_RE" | sort -u
}

adf_changed_dart_lib_files() {
  adf_changed_files | grep -E '^lib/.*\.dart$' || true
}

# Total added+removed lines across the diff (untracked files don't count here,
# but they already bump the file count, so a new file is never "micro").
adf_changed_line_count() {
  ( cd "$ROOT" 2>/dev/null || { echo 0; return 0; }
    git diff --numstat "${ADF_DIFF_BASE:-HEAD}" 2>/dev/null \
      | awk '{ if ($1 ~ /^[0-9]+$/) a+=$1; if ($2 ~ /^[0-9]+$/) d+=$2 } END { print a+d+0 }'
  )
}

adf_changed_file_count() { adf_changed_files | grep -c . ; }

# True (0) when the working change is small enough for the fast path.
adf_is_micro() {
  [[ "${ADF_SCOPE_MODE:-auto}" == "off"  ]] && return 1
  [[ "${ADF_SCOPE_MODE:-auto}" == "repo" ]] && return 1
  local nf nl
  nf="$(adf_changed_file_count)"
  nl="$(adf_changed_line_count)"
  [[ "$nf" -ge 1 \
     && "$nf" -le "${ADF_MICRO_MAX_FILES:-1}" \
     && "$nl" -le "${ADF_MICRO_MAX_LINES:-10}" ]]
}

# Files that import a given lib/-relative dart file. Matches both
#   package:<pkg>/<path-under-lib>   (precise)
#   import '.../<basename>'          (relative — conservative superset)
# Over-inclusion is safe for a gate: we'd rather check one extra file than miss
# a real dependent.
adf_importers_of() {
  local f="$1"
  local rel="${f#lib/}"          # e.g. services/order_sync.dart
  local base="${rel##*/}"        # e.g. order_sync.dart
  local pkg; pkg="$(adf_pkg_name)"
  ( cd "$ROOT" 2>/dev/null || return 0
    grep -rlE "import[[:space:]]+['\"](package:${pkg}/${rel}|[^'\"]*/${base}|${base})['\"]" \
      lib --include='*.dart' 2>/dev/null
  ) | sed '/^$/d' | grep -vxF "$f" | sort -u
}

# Changed lib files ∪ their dependents (BFS to ADF_BLAST_DEPTH hops).
adf_affected_files() {
  if [[ -n "${ADF_AFFECTED_FILES:-}" ]]; then
    printf '%s\n' $ADF_AFFECTED_FILES | sed '/^$/d' | sort -u
    return 0
  fi
  local depth="${ADF_BLAST_DEPTH:-1}"
  local -a frontier all next
  mapfile -t frontier < <(adf_changed_dart_lib_files)
  all=("${frontier[@]}")
  local d=0 f imp
  while (( d < depth )) && (( ${#frontier[@]} > 0 )); do
    next=()
    for f in "${frontier[@]}"; do
      while IFS= read -r imp; do
        [[ -z "$imp" ]] && continue
        if ! printf '%s\n' "${all[@]}" | grep -qxF "$imp"; then
          all+=("$imp"); next+=("$imp")
        fi
      done < <(adf_importers_of "$f")
    done
    frontier=("${next[@]}")
    (( d++ ))
  done
  ((${#all[@]})) && printf '%s\n' "${all[@]}" | sed '/^$/d' | sort -u
}

# Dependents only (affected minus the files actually changed).
adf_dependent_files() {
  local changed; changed="$(adf_changed_dart_lib_files)"
  adf_affected_files | grep -vxF "$changed" 2>/dev/null | sed '/^$/d' || true
}
