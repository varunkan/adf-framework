#!/usr/bin/env bash
# Stop the whole ANDS Studio local mesh (every service + web).
set -u
for port in 3000 8010 8011 8012 8013 8014 8016 8017 8018; do
  pid=$(lsof -tiTCP:"$port" -sTCP:LISTEN -P -n 2>/dev/null | head -1)
  if [ -n "$pid" ]; then
    # kill the process group (npm/uvicorn spawn children)
    kill "$pid" 2>/dev/null && echo "stopped :$port (pid $pid)"
  fi
done
echo "ANDS Studio stopped."
