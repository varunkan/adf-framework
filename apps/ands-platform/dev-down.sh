#!/usr/bin/env bash
# Stop the whole ANDS Studio local mesh (every service + web).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# clear the self-heal marker first, so the Stop hook won't resurrect the mesh
# after an intentional shutdown.
rm -f "$ROOT/.dev-logs/.mesh-active"
for port in 3000 8010 8011 8012 8013 8014 8016 8017 8018; do
  pid=$(lsof -tiTCP:"$port" -sTCP:LISTEN -P -n 2>/dev/null | head -1)
  if [ -n "$pid" ]; then
    # kill the whole process group — npm/uvicorn(--reload) spawn children a
    # single-pid kill would orphan, leaving the port held.
    pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
    if [ -n "$pgid" ]; then kill -TERM "-$pgid" 2>/dev/null; else kill "$pid" 2>/dev/null; fi
    echo "stopped :$port (pid $pid${pgid:+ pgid $pgid})"
  fi
done
echo "ANDS Studio stopped."
