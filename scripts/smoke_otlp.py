"""Real, no-Docker OTLP SDK -> HTTP API -> durable storage smoke test.

Uses an isolated temporary SQLite database and local loopback HTTP only.
This intentionally does NOT claim Collector/PostgreSQL/Compose validation.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import httpx
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import SpanKind

PORT=8944
KEY='smoke-'+('causaltrace'*4)

def main():
    with tempfile.TemporaryDirectory(prefix='causaltrace-smoke-') as td:
        env=os.environ.copy()
        env.update({'CAUSALTRACE_API_KEY':KEY,'DATABASE_URL':f'sqlite:///{Path(td)/"test.db"}'})
        migrate=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=env,capture_output=True,text=True)
        if migrate.returncode:raise RuntimeError('Migration failed: '+migrate.stderr)
        server=subprocess.Popen([sys.executable,'-m','uvicorn','causaltrace.api:app','--host','127.0.0.1','--port',str(PORT)],env=env,
                                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            with httpx.Client(timeout=3,trust_env=False,headers={'x-api-key':KEY}) as client:
                for _ in range(80):
                    if server.poll() is not None:raise RuntimeError('API exited unexpectedly')
                    try:
                        if client.get(f'http://127.0.0.1:{PORT}/ready').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise RuntimeError('API readiness timed out')
                def provider(service):
                    instance=TracerProvider(resource=Resource.create({'service.name':service}))
                    instance.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(
                        endpoint=f'http://127.0.0.1:{PORT}/v1/traces',headers={'x-api-key':KEY},timeout=3)))
                    return instance
                p1=provider('gateway');p2=provider('payment')
                with p1.get_tracer('smoke').start_as_current_span('checkout',kind=SpanKind.SERVER):
                    with p2.get_tracer('smoke').start_as_current_span('authorize-test-payment',kind=SpanKind.SERVER):
                        pass
                p1.shutdown();p2.shutdown()
                top=client.get(f'http://127.0.0.1:{PORT}/api/topology');top.raise_for_status()
                edges=top.json()['edges']
                assert any(e['source']=='gateway' and e['target']=='payment' for e in edges),edges
                traces=client.get(f'http://127.0.0.1:{PORT}/api/traces').json()['items']
                assert traces and traces[0]['spans']==2,traces
                detailed=client.get(f'http://127.0.0.1:{PORT}/api/traces/{traces[0]["trace_id"]}').json()
                assert not detailed['missing_parent_span_ids']
                print(json.dumps({'status':'passed','transport':'actual OTel Python SDK OTLP HTTP',
                                  'database':'real SQLite file + Alembic migrations',
                                  'spans':traces[0]['spans'],'observed_edges':edges},indent=2))
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()

if __name__=='__main__':main()
