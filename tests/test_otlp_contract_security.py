"""Contract and security regressions for untrusted OTLP collector payloads."""
import time

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from sqlalchemy import func, select

from causaltrace.api import sanitize_telemetry, set_lab_fault
from causaltrace.db import Span
from .conftest import auth


def make_span(*, trace_id=b"t" * 16, span_id=b"s" * 8, parent_id=b"",
              start_ns=None, end_ns=None, status="200"):
    message = ExportTraceServiceRequest()
    resource = message.resource_spans.add()
    resource.resource.attributes.append(KeyValue(key="service.name", value=AnyValue(string_value="checkout")))
    span = resource.scope_spans.add().spans.add()
    span.trace_id, span.span_id, span.parent_span_id = trace_id, span_id, parent_id
    span.name, span.kind = "charge", 2
    span.start_time_unix_nano = start_ns if start_ns is not None else time.time_ns()
    span.end_time_unix_nano = end_ns if end_ns is not None else span.start_time_unix_nano + 100_000
    span.attributes.append(KeyValue(key="http.response.status_code", value=AnyValue(string_value=status)))
    return message.SerializeToString()


def test_otlp_rejects_invalid_ids_and_timestamps_without_persisting(client):
    now = time.time_ns()
    candidates = [
        make_span(trace_id=b"short"),
        make_span(span_id=b"short"),
        make_span(parent_id=b"too-short"),
        make_span(start_ns=now, end_ns=now-1),
        make_span(start_ns=0, end_ns=now),
    ]
    for body in candidates:
        response = client.post('/v1/traces', content=body, headers=auth())
        assert response.status_code == 400, response.text
    with client.app.state.ct.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Span)) == 0


def test_otlp_rejects_unknown_content_type(client):
    response = client.post('/v1/traces', content=make_span(),
                           headers={**auth(), 'content-type': 'text/plain'})
    assert response.status_code == 400
    assert response.json()['detail'] == 'Invalid OTLP trace payload'


def test_malformed_http_status_does_not_drop_valid_spans(client):
    response = client.post('/v1/traces', content=make_span(status='unparseable'), headers=auth())
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/x-protobuf')
    with client.app.state.ct.sessions() as session:
        assert session.scalar(select(Span.error)) is False


def test_telemetry_non_finite_metadata_does_not_enter_json_storage():
    assert sanitize_telemetry({'x': float('nan'), 'y': float('inf')}) == {
        'x': '[invalid-nonfinite]', 'y': '[invalid-nonfinite]'
    }


def test_fault_dispatch_never_uses_external_host_even_with_key():
    import pytest
    with pytest.raises(ValueError):
        set_lab_fault('payment.evil.example', {'mode': 'error'}, 'not-a-real-key')
