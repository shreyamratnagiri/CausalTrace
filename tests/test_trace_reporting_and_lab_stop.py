"""Read integrity and cancellation races must be visible and durable."""
import time

from fastapi.testclient import TestClient

from causaltrace.api import create_app
from causaltrace.db import Base, Experiment, Span
from causaltrace.settings import Settings
from .conftest import KEY, auth


def test_bounded_trace_result_flags_truncation(client):
    now = time.time_ns()
    with client.app.state.ct.sessions() as db:
        db.add_all(Span(trace_id='c'*32, span_id=f'{i:016x}', service='worker',
                        operation='work', start_ns=now+i*100, end_ns=now+i*100+80,
                        error=False, attributes={'span.kind': 'server'}) for i in range(3001))
        db.commit()
    result = client.get('/api/traces/'+'c'*32)
    assert result.status_code == 200
    payload=result.json()
    assert payload['truncated'] is True
    assert payload['returned_spans'] == 3000
    assert payload['total_spans'] == 3001
    assert payload['warning_if_truncated']


def test_stop_marks_running_experiment_before_contacting_fault_target(tmp_path, monkeypatch):
    import causaltrace.api as api
    settings=Settings(database_url=f'sqlite:///{tmp_path / "stop.db"}', api_key=KEY,
                      retention_days=7, ingest_max_events=500, ingest_max_bytes=1024*1024,
                      lab_enabled=True, lab_services=('payment',))
    app=create_app(settings)
    Base.metadata.create_all(app.state.ct.engine)
    observed=[]
    def fake_stop(service, body, key):
        with app.state.ct.sessions() as db:
            record=db.get(Experiment,'active')
            observed.append((service, body['mode'], record.status))
    monkeypatch.setattr(api, 'set_lab_fault', fake_stop)
    with TestClient(app) as client:
        with app.state.ct.sessions() as db:
            db.add(Experiment(id='active', target='payment', mode='error', status='running'))
            db.commit()
        answer=client.post('/api/lab/experiments/active/stop',headers=auth())
        assert answer.status_code==200,answer.text
        assert answer.json()['status']=='stopping'
        assert observed==[('payment','none','stopping')]
        again=client.post('/api/lab/experiments/active/stop',headers=auth())
        assert again.status_code==200
        assert len(observed)==1


def test_lost_fault_activation_ack_still_attempts_cleanup(client, monkeypatch):
    """A timed-out control response may hide an applied fault; TTL alone is not enough."""
    import causaltrace.api as api
    from causaltrace.schemas import ExperimentCreate

    calls=[]
    def fake_fault(target, body, secret):
        calls.append(body['mode'])
        if body['mode']=='error':
            raise TimeoutError('Control response was lost after remote activation')

    class HealthyClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, url):
            return type('Response', (), {'status_code': 200})()

    monkeypatch.setattr(api, 'set_lab_fault', fake_fault)
    monkeypatch.setattr(api.httpx, 'Client', HealthyClient)
    monkeypatch.setattr(client.app.state.ct.shutdown_requested, 'wait', lambda _: False)
    cfg=client.app.state.ct
    with cfg.sessions() as db:
        db.add(Experiment(id='lost-ack', target='payment', mode='error', status='queued'))
        db.commit()
    assert cfg.experiment_slots.acquire(blocking=False)
    api.run_experiment(cfg, 'lost-ack', ExperimentCreate(target='payment', mode='error', duration_seconds=1))
    with cfg.sessions() as db:
        record=db.get(Experiment,'lost-ack')
        assert record.status=='failed'
        assert record.result['cleanup_verified'] is True
        assert record.result['error']['type']=='TimeoutError'
    assert calls==['error','none']
