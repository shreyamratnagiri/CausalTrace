"""Source-level guardrails for known CI security and persistence regressions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_live_browser_receives_ephemeral_api_key_in_its_own_step():
    workflow = (ROOT / '.github/workflows/lab-e2e.yml').read_text()
    browser_step = workflow.split('- name: Browser-to-actual-API validation', 1)[1].split('      - name:', 1)[0]
    assert 'source ../.env' in browser_step
    assert 'export CAUSALTRACE_API_KEY' in browser_step
    assert '${CAUSALTRACE_API_KEY:?Missing lab operator API key}' in browser_step
    assert 'x-api-key: ${CAUSALTRACE_API_KEY}' in browser_step
    assert 'npm run test:e2e' in browser_step
    assert 'CAUSALTRACE_REQUIRE_LIVE: "1"' in browser_step
    assert 'echo "$CAUSALTRACE_API_KEY"' not in workflow
    browser_test = (ROOT / 'web/tests/live-telemetry.spec.ts').read_text()
    assert "if (!apiKey) throw new Error" in browser_test
    assert "'x-api-key':apiKey" in browser_test


def test_postgres_verification_has_a_separate_ephemeral_database():
    compose = (ROOT / 'docker-compose.yml').read_text()
    verification = compose.split('  postgres-test:', 1)[1].split('  api:', 1)[0]
    assert 'profiles: [verification]' in verification
    assert 'postgres-test:5432/causaltrace_test' in verification
    assert '/var/lib/postgresql/data' in verification
    assert 'postgres:5432/causaltrace\n' not in verification
    test_image = (ROOT / 'Dockerfile.tests').read_text()
    assert 'alembic upgrade head && pytest' in test_image
    postgres_test = (ROOT / 'tests/test_postgres.py').read_text()
    assert 'tx.rollback()' in postgres_test
    assert 'session.commit()' not in postgres_test
