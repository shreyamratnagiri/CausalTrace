"""SQL-pool exhaustion must be a measured reservation, not a success-shaped toggle."""
import os
import subprocess
import sys
import textwrap


def test_database_fault_rejects_unreserved_connections():
    # Separate process: the demo initializes global OTLP providers on import.
    code = textwrap.dedent('''
        import os
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        os.environ.update(SERVICE_NAME='database', CAUSALTRACE_LAB='isolated-compose-only',
                          CAUSALTRACE_API_KEY='0123456789abcdef0123456789abcdef',
                          LAB_DATABASE_URL='postgresql://unused:unused@localhost/unused')
        from demo.microservices.service import app, DB_LIMIT
        import sys, types
        psycopg=types.ModuleType('psycopg')
        psycopg.connect=lambda *args,**kwargs: (_ for _ in ()).throw(ConnectionError('refuse SQL'))
        sys.modules['psycopg']=psycopg
        with patch.object(psycopg, 'connect', side_effect=ConnectionError('local test refuses SQL connection')):
            with TestClient(app) as client:
                response=client.post('/_lab/fault',json={'mode':'db_exhaustion',
                                     'duration_seconds':1},headers={'x-lab-key':os.environ['CAUSALTRACE_API_KEY']})
                assert response.status_code == 503, response.text
                # A failed reservation leaves both local slots available.
                assert DB_LIMIT.acquire(blocking=False)
                assert DB_LIMIT.acquire(blocking=False)
                DB_LIMIT.release()
                DB_LIMIT.release()
                assert client.post('/_lab/fault',json={'mode':'none'},headers={
                    'x-lab-key':os.environ['CAUSALTRACE_API_KEY']}).status_code==200
    ''')
    result=subprocess.run([sys.executable,'-c',code],env={**os.environ,'PYTHONPATH':'.'},
                          capture_output=True,text=True,timeout=25,check=False)
    assert result.returncode == 0, result.stdout+'\n'+result.stderr
