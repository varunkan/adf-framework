#!/usr/bin/env bash
# Validate ADF v3 artifacts: shape, DAG topo sort, micro-task limits.
set -euo pipefail

FEATURE_ID="${1:-}"
PHASE=""
shift 2>/dev/null || true
if [[ "${1:-}" == --phase ]]; then
  PHASE="${2:-}"
fi
if [[ -z "$FEATURE_ID" ]]; then
  echo "Usage: $0 <feature-id> [--phase N]" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SPECS="$ROOT/specs/$FEATURE_ID"
ERRORS=0

fail() {
  echo "FAIL: $*" >&2
  ERRORS=$((ERRORS + 1))
}

warn() {
  echo "WARN: $*" >&2
}

check_file() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    fail "missing required file: $f"
    return 1
  fi
  return 0
}

# Phase-specific required artifacts
case "${PHASE:-all}" in
  2|all) check_file "$SPECS/spec.md" || true ;;
  3|all) check_file "$SPECS/plan.md" || true ;;
  4|all)
    check_file "$SPECS/tasks.md" || true
    check_file "$SPECS/task-graph.yaml" || true
    if [[ ! -d "$SPECS/tasks" ]]; then
      fail "missing directory: $SPECS/tasks"
    fi
    ;;
esac

# Shape: spec must have Problem statement
if [[ -f "$SPECS/spec.md" ]] && ! grep -qi 'problem statement' "$SPECS/spec.md"; then
  warn "spec.md may lack Problem statement heading"
fi

# DAG validation when task-graph present
GRAPH="$SPECS/task-graph.yaml"
if [[ -f "$GRAPH" ]]; then
  python3 - "$GRAPH" "$SPECS" <<'PY' || ERRORS=$((ERRORS + 1))
import sys, re, os
from collections import defaultdict, deque

graph_path, specs_dir = sys.argv[1], sys.argv[2]
text = open(graph_path).read()
ids = re.findall(r'^\s*-\s*id:\s*(\S+)', text, re.M)
if not ids:
    print("FAIL: task-graph.yaml has no node ids", file=sys.stderr)
    sys.exit(1)

deps = defaultdict(list)
for m in re.finditer(
    r'id:\s*(\S+).*?depends_on:\s*\[(.*?)\]',
    text,
    re.S,
):
    nid = m.group(1)
    inner = m.group(2).strip()
    if inner:
        for d in re.findall(r'[\w-]+', inner):
            deps[nid].append(d)

# Orphan depends_on
all_ids = set(ids)
for nid, ds in deps.items():
    for d in ds:
        if d not in all_ids:
            print(f"FAIL: orphan dependency {nid} -> {d}", file=sys.stderr)
            sys.exit(1)

# Cycle detection (Kahn)
indeg = {i: 0 for i in ids}
for nid in ids:
    for d in deps.get(nid, []):
        indeg[nid] = indeg.get(nid, 0)
for nid, ds in deps.items():
    for d in ds:
        indeg[nid] = indeg.get(nid, 0) + 1

# Rebuild indegree correctly
indeg = {i: 0 for i in ids}
adj = defaultdict(list)
for nid in ids:
    for d in deps.get(nid, []):
        adj[d].append(nid)
        indeg[nid] += 1

q = deque([i for i in ids if indeg[i] == 0])
order = []
while q:
    u = q.popleft()
    order.append(u)
    for v in adj[u]:
        indeg[v] -= 1
        if indeg[v] == 0:
            q.append(v)

if len(order) != len(ids):
    print("FAIL: cycle detected in task-graph.yaml", file=sys.stderr)
    sys.exit(1)

print("OK: topological order:", " -> ".join(order))

# Micro-task files
tasks_dir = os.path.join(specs_dir, "tasks")
for nid in ids:
    tf = os.path.join(tasks_dir, f"{nid}.md")
    if not os.path.isfile(tf):
        # allow task_file override in yaml
        m = re.search(rf'id:\s*{re.escape(nid)}.*?task_file:\s*(\S+)', text, re.S)
        if m:
            tf = os.path.join(specs_dir, m.group(1))
    if not os.path.isfile(tf):
        print(f"WARN: missing task file for {nid}", file=sys.stderr)
        continue
    body = open(tf).read()
    m = re.search(r'max_duration_seconds:\s*(\d+)', body)
    if m and int(m.group(1)) > 90:
        print(f"FAIL: {nid} max_duration_seconds > 90", file=sys.stderr)
        sys.exit(1)
    paths = re.findall(r'allowed_paths:\s*\n((?:\s*-\s*.+\n)+)', body)
    if paths:
        count = len(re.findall(r'^\s*-\s*', paths[0], re.M))
        if count > 8:
            print(f"FAIL: {nid} touches too many allowed_paths ({count})", file=sys.stderr)
            sys.exit(1)

sys.exit(0)
PY
fi

if [[ $ERRORS -gt 0 ]]; then
  echo "validate_adf_artifacts: $ERRORS error(s) for $FEATURE_ID" >&2
  exit 1
fi

echo "validate_adf_artifacts: PASS for $FEATURE_ID"
exit 0
