"""Regressions for the release audit: scoped data, safety, malformed traces."""
import time

from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from causaltrace.analytics import reconstruct
from causaltrace.api import create_app, load_analysis, run_experiment
from causaltrace.db import Base, Experiment, Span
from .conftest import KEY, auth


def test_deep_trace_does_not_use_recursive_stack():
    spans=[]
    for i in range(1500):
        spans.append({'span_id':str(i),'parent_span_id':str(i-1) if i else None,
                      'trace_id':'f'*32,'service':'database','operation':'query',
                      'start_ns':i*10,'end_ns':i*10+8,'error':False})
    detail=reconstruct(list(reversed(spans)))
    assert len(detail['critical_path_span_ids'])==1500
    assert not detail['cyclic_parent_graph']


def test_corrupted_cycle_and_clock_skew_are_explicit():
    spans=[{'span_id':'a','parent_span_id':'b','start_ns':100,'end_ns':50},
           {'span_id':'b','parent_span_id':'a','start_ns':10,'end_ns':20}]
    detail=reconstruct(spans)
    assert detail['cyclic_parent_graph']
    assert detail['critical_path_upper_bound_ms']>=0
    assert detail['critical_path_span_ids']


def test_nonfinite_numeric_telemetry_rejected(client):
    event={'event_id':'time1','service':'checkout','timestamp':'NaN'}
    assert client.post('/api/telemetry/events',json={'events':[event]},headers=auth()).status_code==422
    metric={'service':'checkout','name':'p95','timestamp':time.time(),'value':'Infinity'}
    assert client.post('/api/telemetry/metrics',json={'metrics':[metric]},headers=auth()).status_code==422


def test_scoped_analysis_never_reads_prior_faults(client):
    now=time.time_ns()
    trace='f'*32
    with client.app.state.ct.sessions() as db:
        db.add_all([Span(trace_id=trace,span_id=f'{i:016x}',service='payment',operation='work',
                         start_ns=now+i*5_000_000_000,end_ns=now+i*5_000_000_000+10_000_000,
                         error=(i==0),attributes={'span.kind':'server'}) for i in range(12)])
        db.commit()
        recent,_,_,_=load_analysis(db,since_ns=now+7*5_000_000_000)
        assert recent and all(r['error_rate']==0 for r in recent)
        early,_,_,_=load_analysis(db,until_ns=now+1_000_000_000)
        assert early and early[0]['error_rate']==1


def test_unavailable_worker_and_cancelled_before_execution(client):
    cfg=client.app.state.ct
    from causaltrace.schemas import ExperimentCreate
    with cfg.sessions() as db:
        db.add(Experiment(id='stop-before-inject',target='payment',mode='error',status='stopping'))
        db.commit()
    assert cfg.experiment_slots.acquire(blocking=False)
    # No HTTP calls are made when the experiment was stopped while queued.
    run_experiment(cfg,'stop-before-inject',ExperimentCreate(target='payment',mode='error'))
    with cfg.sessions() as db:
        exp=db.get(Experiment,'stop-before-inject')
        assert exp.status=='cancelled'
        assert not exp.result['fault']
        assert exp.result['cleanup_verified']
    assert cfg.experiment_slots.acquire(blocking=False)
    cfg.experiment_slots.release()


def test_lab_rejects_mismatched_dependency_fault(tmp_path):
    from causaltrace.settings import Settings
    settings=Settings(database_url=f'sqlite:///{tmp_path / "faults.db"}',api_key=KEY,
                      retention_days=7,ingest_max_events=500,ingest_max_bytes=1048576,
                      lab_enabled=True,lab_services=('gateway','database','cache'))
    app=create_app(settings)
    Base.metadata.create_all(app.state.ct.engine)
    with TestClient(app) as client:
        res=client.post('/api/lab/experiments',json={'target':'payment','mode':'db_exhaustion'},headers=auth())
        assert res.status_code==422
        res=client.post('/api/lab/experiments',json={'target':'database','mode':'cache_failure'},headers=auth())
        assert res.status_code==422


def test_actual_otlp_payload_dedup_and_out_of_order_parent(client):
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    request=ExportTraceServiceRequest()
    root=request.resource_spans.add()
    attr=root.resource.attributes.add();attr.key='service.name';attr.value.string_value='checkout'
    scope=root.scope_spans.add()
    s=scope.spans.add();s.trace_id=bytes.fromhex('d'*32);s.span_id=bytes.fromhex('2'*16)
    s.parent_span_id=bytes.fromhex('1'*16);s.name='pay';s.start_time_unix_nano=time.time_ns();s.end_time_unix_nano=s.start_time_unix_nano+50_000
    resp=client.post('/v1/traces',content=request.SerializeToString(),headers={**auth(),'content-type':'application/x-protobuf'})
    assert resp.status_code==200,resp.text
    assert resp.headers['content-type'].startswith('application/x-protobuf')
    assert client.post('/v1/traces',content=request.SerializeToString(),headers={**auth(),'content-type':'application/x-protobuf'}).status_code==200
    root.resource.attributes[0].value.string_value='gateway'
    del scope.spans[:]
    parent=scope.spans.add();parent.trace_id=bytes.fromhex('d'*32);parent.span_id=bytes.fromhex('1'*16)
    parent.name='gateway';parent.start_time_unix_nano=s.start_time_unix_nano-50_000
    parent.end_time_unix_nano=s.end_time_unix_nano+50_000
    response=client.post('/v1/traces',content=request.SerializeToString(),headers={**auth(),'content-type':'application/x-protobuf'})
    assert response.status_code==200,response.text
    topology=client.get('/api/topology').json()['edges']
    assert any(e['source']=='gateway' and e['target']=='checkout' for e in topology)


def test_sensitive_telemetry_attributes_are_redacted(client):
    from causaltrace.db import Event
    event={'event_id':'scrub1','service':'payment','timestamp':time.time(),
           'detail':{'authorization':'Bearer must-not-store','nested':{'api_key':'must-not-store'},
                     'status':'ok'}}
    res=client.post('/api/telemetry/events',json={'events':[event]},headers=auth())
    assert res.status_code==200,res.text
    with client.app.state.ct.sessions() as db:
        detail=db.get(Event,'scrub1').detail
        assert detail['authorization']=='[REDACTED]'
        assert detail['nested']['api_key']=='[REDACTED]'
        assert detail['status']=='ok'


def test_otlp_histogram_is_not_reported_as_fabricated_percentile():
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from causaltrace.otlp import decode_metrics
    message=ExportMetricsServiceRequest()
    rm=message.resource_metrics.add()
    a=rm.resource.attributes.add();a.key='service.name';a.value.string_value='checkout'
    hist=rm.scope_metrics.add().metrics.add()
    hist.name='http.server.duration';hist.unit='ms'
    point=hist.histogram.data_points.add();point.time_unix_nano=time.time_ns()
    point.count=10;point.sum=540.
    records=decode_metrics(message.SerializeToString())
    assert {x['name'] for x in records}=={'http.server.duration.count','http.server.duration.sum'}
    assert {r['name']:r['value'] for r in records}['http.server.duration.sum']==540.
    assert all('.p95' not in r['name'] for r in records)
