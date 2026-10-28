#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for binary in python npm docker; do
  command -v "$binary" >/dev/null 2>&1 || { echo "Missing prerequisite: $binary" >&2; exit 2; }
done
python scripts/bootstrap_env.py
if [ ! -f web/package-lock.json ]; then
  echo 'Resolving real npm package-lock.json (registry access required)' >&2
  (cd web && npm install --package-lock-only --ignore-scripts --no-audit --no-fund)
fi
docker compose -f docker-compose.yml -f docker-compose.lab.yml config -q
docker compose -f docker-compose.yml -f docker-compose.lab.yml up --build -d --wait --wait-timeout 180
printf '\nDashboard: http://127.0.0.1:8080\nAPI readiness: http://127.0.0.1:8000/ready\n'
