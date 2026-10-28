"""Two-process, real HTTP/OTLP contract smoke fixture; NOT the full Compose lab.

This is deliberately loopback-only. The experiment does not create fake spans:
OpenTelemetry context is sent over a real HTTP request between service processes.
"""
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from opentelemetry import propagate
from opentelemetry.context import attach, detach
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import SpanKind

ROLE = os.environ["SMOKE_SERVICE_ROLE"]
if ROLE not in {"gateway", "payment"}:
    raise RuntimeError("Only the fixed gateway/payment loopback roles are permitted")
API = os.environ["SMOKE_API_OTLP_ENDPOINT"]
KEY = os.environ["CAUSALTRACE_API_KEY"]
PAYMENT = os.getenv("SMOKE_PAYMENT_URL", "")
provider = TracerProvider(resource=Resource.create({"service.name": ROLE, "environment": "local-smoke"}))
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(
    endpoint=API, headers={"x-api-key": KEY}, timeout=4)))
tracer = provider.get_tracer("causaltrace.smoke.real-http")
app = FastAPI(title=f"Local real HTTP smoke {ROLE}")


@app.get('/health')
def health():
    return {"service": ROLE, "healthy": True}


@app.get('/charge')
def charge(request: Request):
    if ROLE != "payment":
        raise HTTPException(404)
    token = attach(propagate.extract(dict(request.headers)))
    try:
        with tracer.start_as_current_span("payment.charge", kind=SpanKind.SERVER) as span:
            span.set_attribute("test.payment", True)
            return {"approved": True, "currency": "TEST"}
    finally:
        detach(token)


@app.get('/checkout')
def checkout(request: Request):
    if ROLE != "gateway":
        raise HTTPException(404)
    with tracer.start_as_current_span("gateway.checkout", kind=SpanKind.SERVER) as parent:
        with tracer.start_as_current_span("gateway.payment", kind=SpanKind.CLIENT):
            headers = {}
            propagate.inject(headers)
            with httpx.Client(timeout=4, trust_env=False) as client:
                response = client.get(PAYMENT + '/charge', headers=headers)
                response.raise_for_status()
        return {"status": "paid", "trace_id": format(parent.get_span_context().trace_id, "032x"),
                "payment": response.json()}


@app.on_event("shutdown")
def shutdown():
    provider.shutdown()
