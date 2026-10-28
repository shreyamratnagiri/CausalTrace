import time
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import KeyValue,AnyValue
from causaltrace.otlp import decode_traces,decode_metrics
from .conftest import auth

def payload(trace='a'*32,reverse=False):
    now=int(time.time()*1e9)
    msg=ExportTraceServiceRequest()
    spans=[{'sid':bytes.fromhex('0'*15+'1'),'parent':b'','name':'checkout','service':'checkout','start':now},
           {'sid':bytes.fromhex('0'*15+'2'),'parent':bytes.fromhex('0'*15+'1'),'name':'payment-call','service':'payment','start':now+1_000_000}]
    for info in (reversed(spans) if reverse else spans):
        group=msg.resource_spans.add()
        group.resource.attributes.append(KeyValue(key='service.name',value=AnyValue(string_value=info['service'])))
        scope=group.scope_spans.add()
        s=scope.spans.add();s.trace_id=bytes.fromhex(trace);s.span_id=info['sid'];s.parent_span_id=info['parent'];s.name=info['name'];s.start_time_unix_nano=info['start'];s.end_time_unix_nano=info['start']+1_000_000;s.kind=2
    return msg.SerializeToString()

def test_otlp_ingestion_dedup_and_out_of_order(client):
    body=payload(reverse=True)
    r=client.post('/v1/traces',content=body,headers={**auth(),'content-type':'application/x-protobuf'})
    assert r.status_code==200,r.text
    assert r.headers['content-type'].startswith('application/x-protobuf')
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
    ExportTraceServiceResponse.FromString(r.content)
    duplicate=client.post('/v1/traces',content=body,headers=auth())
    assert duplicate.status_code==200
    trace=client.get('/api/traces/'+'a'*32).json()
    assert len(trace['spans'])==2
    assert trace['missing_parent_span_ids']==[]
    assert client.get('/api/topology').json()['edges']

def test_protobuf_decoder_no_fake_data():
    assert len(decode_traces(payload()))==2
    assert decode_metrics(ExportMetricsServiceRequest().SerializeToString())==[]

def test_otlp_bounds(client):
    r=client.post('/v1/traces',content=b'notprotobuf',headers=auth())
    assert r.status_code==400
    r=client.post('/v1/traces',content=b'a'*(1024*1024+1),headers=auth())
    assert r.status_code==413
