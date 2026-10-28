"""Measured isolated SQLite/loopback performance; NOT Docker/PostgreSQL figures.

Runs both existing benchmark programs against a temporary migrated API. Designed
for clean-clone hosts without Docker; refuses a pre-existing service on port 8000.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'benchmarks' / 'results.sqlite-smoke.measured.json'


def main():
    with httpx.Client(timeout=0.5, trust_env=False) as client:
        try:
            client.get('http://127.0.0.1:8000/health')
        except httpx.HTTPError:
            pass
        else:
            raise RuntimeError('Refusing to use occupied loopback port 8000; stop your API first')
    with tempfile.TemporaryDirectory(prefix='causaltrace-perf-') as tmp:
        env=os.environ.copy()
        env.update({'DATABASE_URL':f'sqlite:///{Path(tmp) / "perf.db"}',
                    'CAUSALTRACE_API_KEY':'local-perf-only-'+'p'*28})
        migrated=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],
                cwd=ROOT,env=env,capture_output=True,text=True)
        if migrated.returncode:
            raise RuntimeError('SQLite migration failed: '+migrated.stderr[-1000:])
        child=subprocess.Popen([sys.executable,'-m','uvicorn','causaltrace.api:app',
                     '--host','127.0.0.1','--port','8000'],cwd=ROOT,env=env,
                     stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            with httpx.Client(timeout=1.0,trust_env=False) as client:
                for _ in range(80):
                    if child.poll() is not None:
                        raise RuntimeError('API process terminated early')
                    try:
                        if client.get('http://127.0.0.1:8000/ready').status_code==200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError('API failed readiness')
            results={}
            for key,script,args in [
                ('ingestion','scripts/benchmark_ingestion.py',['--batches','20','--batch-size','50']),
                ('query','scripts/perf_probe.py',['--repeats','30'])]:
                command=subprocess.run([sys.executable,script,*args],cwd=ROOT,env=env,
                                       capture_output=True,text=True)
                if command.returncode:
                    raise RuntimeError(script+' failed: '+command.stderr[-2000:])
                results[key]=json.loads(command.stdout)
            db_files=Path(tmp).glob('perf.db*')
            results['storage_bytes_after']=sum(f.stat().st_size for f in db_files)
            results['environment']={
                'captured_at':datetime.now(timezone.utc).isoformat(),
                'python':sys.version.split()[0],
                'platform':platform.platform(),
                'data_origin':'real loopback API and SQLite, synthetic request/event inputs',
                'not_equivalent_to':'PostgreSQL, OTLP Collector, distributed fault lab, production capacity'}
            OUTPUT.write_text(json.dumps(results,indent=2))
            print(json.dumps(results,indent=2))
        finally:
            child.terminate()
            try:
                child.wait(timeout=6)
            except subprocess.TimeoutExpired:
                child.kill();child.wait()


if __name__=='__main__':
    main()
