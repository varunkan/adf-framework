#!/usr/bin/env bash
# Double-click this file (Finder) to start ANDS Studio and open it in your
# browser. Safe to run repeatedly — it only starts services that are down.
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

echo "Starting ANDS Studio…"
bash ./dev-up.sh

# wait (up to ~40s) for the web app to answer, then open it
printf "Waiting for http://localhost:3000 "
for _ in $(seq 1 40); do
  if curl -s -m 2 -o /dev/null http://localhost:3000/login; then
    echo " ready."
    open "http://localhost:3000"
    echo "ANDS Studio is open in your browser."
    exit 0
  fi
  printf "."
  sleep 1
done
echo
echo "Web didn't answer yet — check apps/ands-platform/.dev-logs/web.log"
exit 1
