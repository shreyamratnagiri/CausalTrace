"""Verify real isolated HTTP failure, control authentication, TTL and recovery.

Single notification service only, no multi-service Compose implication.
"""
import json
import os
import subprocess
import sys
import time
import httpx

PORT=8945
KEY='smoke-'+('causaltrace'*4)

def main():
    env=os.environ.copy()
    env.update({'SERVICE_NAME':'notification','CAUSALTRACE_LAB':'isolated-compose-only',
                'CAUSALTRACE_API_KEY':KEY,'OTEL_EXPORTER_OTLP_ENDPOINT':'http://127.0.0.1:9999'})
    server=subprocess.Popen([sys.executable,'-m','uvicorn','demo.microservices.service:app',
                             '--host','127.0.0.1','--port',str(PORT)],env=env,
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(timeout=4,trust_env=False) as client:
            for _ in range(80):
                try:
                    if client.get(f'http://127.0.0.1:{PORT}/health').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:raise RuntimeError('Service did not become ready')
            root=f'http://127.0.0.1:{PORT}'
            assert client.get(root+'/work').status_code==200
            assert client.post(root+'/_lab/fault',json={'mode':'error','duration_seconds':1}).status_code==403
            r=client.post(root+'/_lab/fault',headers={'x-lab-key':KEY},json={'mode':'error','duration_seconds':1})
            assert r.status_code==200,r.text
            assert client.get(root+'/work').status_code==503
            time.sleep(1.2)
            assert client.get(root+'/work').status_code==200
            print(json.dumps({'status':'passed','mode':'single actual instrumented HTTP service',
                              'checks':['healthy 200','unauthorized controls 403','real HTTP 503',
                                        'TTL expiration + recovery 200']}))
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill();server.wait()

if __name__=='__main__':main()
