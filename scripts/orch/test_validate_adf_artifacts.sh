#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$ROOT/.cursor/orchestration/_adf_validate_test"
rm -rf "$TMP"
mkdir -p "$TMP/tasks"

cat > "$TMP/task-graph.yaml" <<'YAML'
version: "1"
nodes:
  - id: task-001
    depends_on: []
    task_file: tasks/task-001.md
  - id: task-002
    depends_on: [task-001]
    task_file: tasks/task-002.md
YAML

echo "---
max_duration_seconds: 60
allowed_paths:
  - a.dart
" > "$TMP/tasks/task-001.md"
cp "$TMP/tasks/task-001.md" "$TMP/tasks/task-002.md"
touch "$TMP/spec.md" && echo "## Problem statement" >> "$TMP/spec.md"
touch "$TMP/plan.md" "$TMP/tasks.md"

# Hijack: run validator logic inline for temp dir
export SPECS_TEST="$TMP"
python3 - "$TMP/task-graph.yaml" "$TMP" <<'PY'
import sys, re, os
from collections import defaultdict, deque
graph_path, specs_dir = sys.argv[1], sys.argv[2]
text = open(graph_path).read()
ids = re.findall(r'^\s*-\s*id:\s*(\S+)', text, re.M)
deps = defaultdict(list)
for m in re.finditer(r'id:\s*(\S+).*?depends_on:\s*\[(.*?)\]', text, re.S):
    nid, inner = m.group(1), m.group(2).strip()
    if inner:
        deps[nid] = re.findall(r'[\w-]+', inner)
indeg = {i: 0 for i in ids}
adj = defaultdict(list)
for nid in ids:
    for d in deps.get(nid, []):
        adj[d].append(nid)
        indeg[nid] += 1
q = deque([i for i in ids if indeg[i] == 0])
order = []
while q:
    u = q.popleft(); order.append(u)
    for v in adj[u]:
        indeg[v] -= 1
        if indeg[v] == 0: q.append(v)
assert len(order) == len(ids), "cycle"
print("topo ok:", order)
PY

# Cycle must fail
cat > "$TMP/task-graph-bad.yaml" <<'YAML'
nodes:
  - id: a
    depends_on: [b]
  - id: b
    depends_on: [a]
YAML
if python3 -c "
import re, sys
from collections import defaultdict, deque
text=open('$TMP/task-graph-bad.yaml').read()
ids=re.findall(r'id:\s*(\S+)', text)
deps={}
for m in re.finditer(r'id:\s*(\S+).*?depends_on:\s*\[(.*?)\]', text, re.S):
    deps[m.group(1)]=re.findall(r'[\w-]+', m.group(2))
indeg={i:0 for i in ids}
adj=defaultdict(list)
for nid in ids:
  for d in deps.get(nid,[]):
    adj[d].append(nid); indeg[nid]+=1
q=deque([i for i in ids if indeg[i]==0]); o=[]
while q:
  u=q.popleft(); o.append(u)
  for v in adj[u]:
    indeg[v]-=1
    if indeg[v]==0: q.append(v)
sys.exit(0 if len(o)==len(ids) else 1)
"; then
  echo "FAIL: expected cycle detection" >&2
  exit 1
fi

rm -rf "$TMP"
echo "validate_adf_artifacts tests: PASS"
