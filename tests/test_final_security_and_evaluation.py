"""Security, restart and real-vs-synthetic evaluation integrity regressions."""
from dataclasses import replace
from fastapi.testclient import TestClient
import pytest
from causaltrace.api import create_app
from causaltrace.db import Base, Experiment
from benchmarks.live_evaluate import evaluate_live
from .conftest import KEY, auth


def test_private_reads_requires_key_and_writes_still_require_key(client):
    cfg=client.app.state.ct.settings
    client.app.state.ct.settings=replace(cfg,protect_reads=True)
    for endpoint in ("/api/overview","/api/incidents","/api/traces", "/api/metrics",
                     "/api/topology","/api/lab/experiments","/metrics"):
        assert client.get(endpoint).status_code==401,endpoint
        assert client.get(endpoint,headers={'x-api-key':'incorrect'}).status_code==401
        assert client.get(endpoint,headers=auth()).status_code==200,endpoint
    assert client.get('/health').status_code==200
    assert client.get('/ready').status_code==200
    assert client.post('/api/incidents',json={'title':'private issue'}).status_code==401


def test_interrupted_fault_is_failed_not_marked_recovered(tmp_path):
    from causaltrace.settings import Settings
    cfg=Settings(database_url=f'sqlite:///{tmp_path / "restart.db"}',api_key=KEY,
                 retention_days=7,ingest_max_events=500,ingest_max_bytes=1048576,
                 lab_enabled=False,lab_services=('payment',))
    app=create_app(cfg)
    Base.metadata.create_all(app.state.ct.engine)
    with app.state.ct.sessions() as db:
        db.add(Experiment(id='unfinished',target='payment',mode='error',status='running'))
        db.commit()
    with TestClient(app) as client:
        result=client.app.state.ct.sessions().get(Experiment,'unfinished')
        assert result.status=='failed'
        assert result.result['cleanup_verified'] is False
        assert result.result['recovery_verified'] is False
        assert result.result['error']=='worker_interrupted_by_restart'


def _scenario(mode, target, ranking):
    return {'id':mode,'status':'completed','target':target,'mode':mode,'result':{
        'telemetry_provenance':'persisted OTLP spans, windowed by experiment time',
        'cleanup_verified':True,'recovery_verified':True,'ranking':ranking,
        'detection_delay_seconds':2.0,
        'detection_windows':[{'phase':'baseline','alert':False,'start_ns':10},
                             {'phase':'fault','alert':True,'start_ns':20}]}}


def test_measured_evaluation_separated_and_per_fault_category():
    result=evaluate_live([_scenario('error','payment',['payment','cache']),
                          _scenario('latency','cache',['payment','cache'])])
    assert result['detection']['f1']==1
    assert result['root_cause']['top1']==.5
    assert result['root_cause']['top3']==1
    assert result['by_fault_category']['latency']['root_cause']['top1']==0
    assert result['detection']['mean_detection_delay_seconds']==2


def test_measured_evaluation_rejects_unverified_data():
    with pytest.raises(ValueError):evaluate_live([])
    row=_scenario('error','payment',['payment'])
    row['result']['recovery_verified']=False
    with pytest.raises(ValueError,match='unverified'):evaluate_live([row])
    row['result']['recovery_verified']=True
    row['result']['telemetry_provenance']='synthetic fixture'
    with pytest.raises(ValueError,match='non-OTLP'):evaluate_live([row])


def test_measured_evaluation_does_not_claim_missing_collector_drop_count():
    example=_scenario('error','payment',['payment'])
    result=evaluate_live([example])
    assert result['dropped_events_reported'] is None
    assert result['dropped_events_coverage']==0
    assert result['by_fault_category']['error']['detection']['f1']==1
    assert result['recovery']['measured_successful_requests']==0
    example['result']['dropped_events']=3
    example['result']['recovery']=[{'http_status':200,'latency_ms':10},
                                   {'http_status':200,'latency_ms':22}]
    result=evaluate_live([example])
    assert result['dropped_events_reported']==3
    assert result['recovery']['median_latency_ms']==16
    assert result['recovery']['p95_latency_ms']==22
    example['result']['recovery'][0]['http_status']=503
    with pytest.raises(ValueError, match='Unhealthy recovery'):
        evaluate_live([example])


def test_live_evaluation_preserves_root_cause_misses_as_failures_not_missing_runs():
    row=_scenario('error','payment',['cache','catalog','checkout'])
    scores=evaluate_live([row])
    assert scores['root_cause']['cases']==1
    assert scores['root_cause']['top1']==0
    assert scores['root_cause']['top3']==0
    assert scores['root_cause']['mrr']==0
