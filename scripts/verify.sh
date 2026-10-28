#!/usr/bin/env bash
# Executes actual release checks. Stops on any failure; does not invent results.
set -euo pipefail
cd "$(dirname "$0")/.."
for binary in python npm docker; do
  command -v "$binary" >/dev/null 2>&1 || { echo "Missing prerequisite: $binary" >&2; exit 2; }
done
python -m pip install -e '.[dev]'
python -m compileall -q causaltrace demo benchmarks scripts tests
python -m pytest -q
python -m ruff check causaltrace benchmarks scripts tests demo
python -m mypy causaltrace/analytics.py causaltrace/ml.py causaltrace/schemas.py
python scripts/smoke_otlp.py
python scripts/smoke_distributed_http.py
python -m benchmarks.evaluate
if [ ! -f web/package-lock.json ]; then
  echo "Resolving genuine npm lock metadata (requires registry access)..." >&2
  (cd web && npm install --package-lock-only --ignore-scripts --no-audit --no-fund)
  test -f web/package-lock.json || { echo "npm lockfile generation failed" >&2; exit 2; }
fi
(cd web && npm ci && npm run lint && npm run format:check && npm run typecheck && npm run test && npm run build)
python scripts/bootstrap_env.py
set -a; source .env; set +a
# This verification run owns its own Compose project and volumes. Never
# shut down or delete the operator's normal `causaltrace` database volume.
export COMPOSE_PROJECT_NAME="ctverify$$"
ct_verify_started=1
ct_verify_cleanup() {
  result=$?
  trap - EXIT
  if [ "${ct_verify_started:-0}" = 1 ]; then
    if [ "$result" -ne 0 ]; then
      mkdir -p benchmarks/local-verification-logs
      docker compose -f docker-compose.yml -f docker-compose.lab.yml logs \
        --no-color --tail=300 > benchmarks/local-verification-logs/failure.log 2>&1 || true
    fi
    # `ctverify$$` is a unique disposable project, never the user's default.
    docker compose -f docker-compose.yml -f docker-compose.lab.yml \
      down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  exit "$result"
}
trap ct_verify_cleanup EXIT
bash scripts/run_lab.sh
docker compose -f docker-compose.yml -f docker-compose.lab.yml exec -T gateway python -c 'import urllib.request; assert urllib.request.urlopen("http://collector:13133/", timeout=5).status == 200'
docker compose -f docker-compose.yml -f docker-compose.lab.yml --profile verification run --build --rm postgres-check
python scripts/verify_live.py
(cd web && npx playwright install chromium && CAUSALTRACE_REQUIRE_LIVE=1 npm run test:e2e)
python scripts/benchmark_ingestion.py
python scripts/perf_probe.py
