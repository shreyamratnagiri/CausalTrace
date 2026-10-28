"""OTLP/protobuf extraction from collector HTTP exporter. Reject oversize at API gateway."""
from hashlib import sha256
import json
import math
from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest


def _value(v):
    kind=v.WhichOneof("value")
    if kind=="string_value":return v.string_value
    if kind=="int_value":return v.int_value
    if kind=="double_value":return v.double_value
    if kind=="bool_value":return v.bool_value
    return "[redacted-complex-attribute]"

def _attrs(attrs):
    return {p.key:_value(p.value) for p in list(attrs)[:32] if 0 < len(p.key) <= 100}

def _decode(cls, data: bytes, content_type: str):
    obj=cls()
    media_type=content_type.split(";",1)[0].strip().lower()
    if media_type == "application/json":
        ParseDict(json.loads(data),obj)
    elif media_type in {"application/x-protobuf", "application/protobuf"}:
        obj.ParseFromString(data)
    else:
        raise ValueError(f"Unsupported OTLP Content-Type: {media_type}")
    return obj

def decode_traces(data: bytes, content_type="application/x-protobuf") -> list[dict]:
    obj=_decode(ExportTraceServiceRequest,data,content_type)
    output=[]
    for resource_spans in obj.resource_spans:
        resource=_attrs(resource_spans.resource.attributes)
        service=str(resource.get("service.name","unknown"))[:100]
        for scope in resource_spans.scope_spans:
            for span in scope.spans:
                if len(span.trace_id) != 16 or len(span.span_id) != 8 or len(span.parent_span_id) not in (0,8):
                    raise ValueError("OTLP spans require valid 16-byte trace and 8-byte span IDs")
                if span.start_time_unix_nano <= 0 or span.end_time_unix_nano < span.start_time_unix_nano:
                    raise ValueError("OTLP span timestamps are invalid")
                attrs=_attrs(span.attributes)
                attrs["span.kind"]=("server" if span.kind==2 else "client" if span.kind==3 else "internal")
                try:
                    http_status = int(attrs.get("http.response.status_code",0))
                except (TypeError, ValueError):
                    http_status = 0
                output.append({"trace_id":span.trace_id.hex(),"span_id":span.span_id.hex(),
                               "parent_span_id":span.parent_span_id.hex() or None,"service":service,
                               "operation":span.name[:180],"start_ns":span.start_time_unix_nano,
                               "end_ns":span.end_time_unix_nano,
                               "error":span.status.code==2 or http_status>=500,
                               "attributes":attrs})
    return output

def decode_metrics(data: bytes, content_type="application/x-protobuf") -> list[dict]:
    obj=_decode(ExportMetricsServiceRequest,data,content_type)
    result=[]
    for resource_metrics in obj.resource_metrics:
        service=str(_attrs(resource_metrics.resource.attributes).get("service.name","unknown"))[:100]
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                field=metric.WhichOneof("data")
                if field not in {"gauge","sum","histogram"}:
                    continue
                data_points=getattr(metric,field).data_points
                for point in data_points:
                    attrs=_attrs(point.attributes)
                    samples=[]
                    if field=="histogram":
                        # A distribution's count and sum are exact observed
                        # aggregates; avoid inventing p95 from bucket midpoints.
                        samples.append((metric.name+".count",float(point.count),"1"))
                        if point.HasField("sum"):
                            samples.append((metric.name+".sum",float(point.sum),metric.unit))
                    else:
                        value_field=point.WhichOneof("value")
                        if value_field in {"as_int","as_double"}:
                            samples.append((metric.name,float(getattr(point,value_field)),metric.unit))
                    for name,val,unit in samples:
                        if not math.isfinite(val):
                            continue
                        raw=f"{service}|{name}|{point.time_unix_nano}|{val}|{sorted(attrs.items())}"
                        result.append({"service":service,"name":name[:120],"timestamp_ns":point.time_unix_nano,
                                       "value":val,"unit":unit[:30],"attributes":attrs,
                                       "fingerprint":sha256(raw.encode()).hexdigest()})
    return result
