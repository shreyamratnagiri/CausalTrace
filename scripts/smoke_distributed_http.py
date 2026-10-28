"""Actual two-process HTTP checkout trace persisted by the CausalTrace API.

Requires installed Python project dependencies; no Docker and no external hosts.
The Collector and full ten-role demo are deliberately NOT simulated here.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    ports = dict(api=free_port(), gateway=free_port(), payment=free_port())
    if len(set(ports.values())) != len(ports):
        raise RuntimeError("Failed to reserve distinct loopback ports")
    key = 'local-smoke-key-' + 'g'*24
    with tempfile.TemporaryDirectory(prefix='causaltrace-http-smoke-') as temporary:
        root = Path(temporary)
        env = os.environ.copy()
        env.update({'CAUSALTRACE_API_KEY': key, 'DATABASE_URL': f'sqlite:///{root / "smoke.db"}'})
        migration = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                                   env=env, capture_output=True, text=True)
        if migration.returncode:
            raise RuntimeError('Migration failed: ' + migration.stderr[-2000:])
        base = f'http://127.0.0.1:{ports["api"]}'
        endpoints = {'api': base, 'gateway': f'http://127.0.0.1:{ports["gateway"]}',
                     'payment': f'http://127.0.0.1:{ports["payment"]}'}
        processes = {}
        logs = {}
        try:
            for role in ('api', 'payment', 'gateway'):
                service_env = env.copy()
                if role != 'api':
                    service_env.update({'SMOKE_SERVICE_ROLE': role,
                                        'SMOKE_API_OTLP_ENDPOINT': base + '/v1/traces',
                                        'SMOKE_PAYMENT_URL': endpoints['payment']})
                module = 'causaltrace.api:app' if role == 'api' else 'scripts.smoke_distributed_service:app'
                log = (root / f'{role}.log').open('w+')
                logs[role] = log
                processes[role] = subprocess.Popen([
                    sys.executable, '-m', 'uvicorn', module, '--host', '127.0.0.1',
                    '--port', str(ports[role])], env=service_env, stdout=log, stderr=subprocess.STDOUT)
            with httpx.Client(timeout=5, trust_env=False, headers={"x-api-key": key}) as client:
                for role in ('api', 'payment', 'gateway'):
                    for _ in range(100):
                        if processes[role].poll() is not None:
                            raise RuntimeError(f'{role} exited before readiness')
                        try:
                            endpoint = '/ready' if role == 'api' else '/health'
                            if client.get(endpoints[role] + endpoint).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.1)
                    else:
                        raise RuntimeError(f'{role} readiness timed out')
                result = client.get(endpoints['gateway'] + '/checkout')
                result.raise_for_status()
                checkout = result.json()
                assert checkout['payment']['approved'] is True
                trace_id = checkout['trace_id']
                for _ in range(40):
                    response = client.get(base + '/api/traces/' + trace_id)
                    if response.status_code == 200 and len(response.json()['spans']) >= 3:
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('Cross-process spans were not ingested')
                detail = response.json()
                services = {s['service'] for s in detail['spans']}
                edges = client.get(base + '/api/topology').json()['edges']
                assert services == {'gateway','payment'}, services
                assert any(e['source'] == 'gateway' and e['target'] == 'payment' for e in edges), edges
                assert not detail['missing_parent_span_ids'], detail
                print(json.dumps({'result': 'VERIFIED PASS', 'kind': 'actual cross-process HTTP + OTLP HTTP',
                    'database': 'migrated SQLite', 'trace_id': trace_id,
                    'services': sorted(services), 'span_count': len(detail['spans']),
                    'observed_edges': [{'source': e['source'], 'target': e['target']} for e in edges]}, indent=2))
        except BaseException as exc:
            for log in logs.values():
                log.flush()
            for name, log in logs.items():
                log.seek(0)
                print(f'--- {name} process output ---\n{log.read()[-3000:]}', file=sys.stderr)
            raise
        finally:
            for proc in processes.values():
                if proc.poll() is None:
                    proc.terminate()
            for proc in processes.values():
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            for handle in logs.values():
                handle.close()


if __name__ == '__main__':
    main()
