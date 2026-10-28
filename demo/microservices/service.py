"""Actual HTTP e-commerce service process (one image, ten roles).

Fault control binds to internal-only Compose hostnames, requires a shared secret,
and expires automatically. Payment uses integer test amounts, never card data.
"""
import json
import os
import random
import secrets
import threading
import time
from contextlib import contextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from opentelemetry import metrics, trace, propagate
from opentelemetry.context import attach, detach
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.trace import SpanKind, Status, StatusCode

NAME=os.environ["SERVICE_NAME"]
LAB=os.getenv("CAUSALTRACE_LAB")=="isolated-compose-only"
KEY=os.environ["CAUSALTRACE_API_KEY"]
BASE=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT","http://collector:4318").rstrip("/")
resource=Resource.create({"service.name":NAME,"deployment.environment":"causaltrace-isolated-lab"})
provider=TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=BASE+"/v1/traces"),
                                              max_queue_size=1024,max_export_batch_size=128,
                                              schedule_delay_millis=500))
trace.set_tracer_provider(provider)
tracer=trace.get_tracer("causaltrace.ecommerce")
meter_provider=MeterProvider(resource=resource,metric_readers=[PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=BASE+"/v1/metrics"),export_interval_millis=2000)])
metrics.set_meter_provider(meter_provider)
meter=metrics.get_meter("causaltrace.ecommerce")
requests=meter.create_counter("http.server.requests",unit="1")
failures=meter.create_counter("http.server.errors",unit="1")
durations=meter.create_histogram("http.server.duration",unit="ms",description="Measured application request duration")
app=FastAPI(title=f"CausalTrace ecommerce — {NAME}")
lock=threading.Lock()
state={"mode":"none","delay_ms":0,"probability":1.0,"expires_at":0.,"seed":42}
randomizer=random.Random(42)
# A genuine two-connection lab-only client pool; exhaustion holds real SQL sessions.
DB_LIMIT=threading.BoundedSemaphore(2)
DB_STOP=threading.Event()
DB_READY=threading.Event()
DB_RESERVATION={"error":None,"connections":0}
DB_THREAD:threading.Thread|None=None

def reserve_db_connections(seconds:int):
    """Reserve both actual local PostgreSQL client-pool slots or fail closed.

    A verified fault starts only after the worker has opened two real SQL
    connections. A partial reservation is not reported as an injected fault.
    """
    acquired=0
    connections=[]
    try:
        import psycopg
        for _ in range(2):
            if not DB_LIMIT.acquire(timeout=2):
                raise RuntimeError("Cannot reserve both local SQL pool slots")
            acquired+=1
            conn=psycopg.connect(os.environ["LAB_DATABASE_URL"],connect_timeout=2)
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise RuntimeError("Database readiness query failed")
            connections.append(conn)
        DB_RESERVATION["connections"]=len(connections)
        DB_READY.set()
        DB_STOP.wait(timeout=seconds)
    except Exception as exc:
        DB_RESERVATION["error"]=type(exc).__name__
        DB_READY.set()
        print(json.dumps({"service":NAME,"lab_pool_error":type(exc).__name__}),flush=True)
    finally:
        for conn in connections:
            conn.close()
        for _ in range(acquired):
            DB_LIMIT.release()

class Fault(BaseModel):
    mode: str
    delay_ms: int=Field(default=0,ge=0,le=1200)
    probability: float=Field(default=1,ge=0,le=1)
    duration_seconds: int=Field(default=20,ge=1,le=120)
    seed: int=42

@app.get("/health")
def health():return {"service":NAME,"status":"ok"}

@app.post("/_lab/fault")
def fault(body:Fault,x_lab_key:str|None=Header(None)):
    if not LAB or not x_lab_key or not secrets.compare_digest(x_lab_key,KEY):
        raise HTTPException(403,"Lab access disabled")
    if body.mode not in {"none","timeout","latency","unavailable","db_exhaustion","cache_failure","saturation","error","config"}:
        raise HTTPException(422,"Unsupported fault mode")
    global DB_THREAD
    if NAME=="database":
        DB_STOP.set()
        if DB_THREAD and DB_THREAD.is_alive():
            DB_THREAD.join(timeout=5)
            if DB_THREAD.is_alive():
                # Never acknowledge cleanup while actual reserved SQL sessions
                # might still be held. Keep the cancellation event signalled.
                raise HTTPException(503,"Previous database fault is still shutting down")
        DB_STOP.clear()
        DB_READY.clear()
        DB_RESERVATION.update({"error":None,"connections":0})
    with lock:
        state.update({"mode":body.mode,"delay_ms":body.delay_ms,"probability":body.probability,
                      "expires_at":time.monotonic()+body.duration_seconds,"seed":body.seed})
        randomizer.seed(body.seed)
    if NAME=="database" and body.mode=="db_exhaustion":
        DB_THREAD=threading.Thread(target=reserve_db_connections,args=(body.duration_seconds,),daemon=True)
        DB_THREAD.start()
        if not DB_READY.wait(timeout=8) or DB_RESERVATION["connections"] != 2:
            DB_STOP.set()
            if DB_THREAD.is_alive():
                DB_THREAD.join(timeout=5)
            with lock:
                state["mode"]="none"
                state["expires_at"]=0.0
            raise HTTPException(503,"Database fault could not reserve two verified SQL connections")
    print(json.dumps({"service":NAME,"action":"lab_fault_changed","mode":body.mode,"ttl_seconds":body.duration_seconds}),flush=True)
    return {"service":NAME,"mode":body.mode,"expires_in_seconds":body.duration_seconds}

def apply_fault():
    with lock:
        mode=state["mode"] if time.monotonic()<state["expires_at"] else "none"
        affected=randomizer.random()<=state["probability"]
        delay=state["delay_ms"]
    if not affected:return
    if mode=="latency":time.sleep(delay/1000)
    if mode=="timeout":time.sleep(max(2.5,delay/1000))
    if mode=="saturation":
        stop=time.monotonic()+.2
        counter=0
        while time.monotonic()<stop:counter+=1
    if mode in {"error","unavailable","config"}:
        raise HTTPException(503,"Isolated laboratory failure")
    if mode=="cache_failure" and NAME=="cache":raise HTTPException(503,"Lab cache unavailable")

@contextmanager
def server_span(request:Request,operation:str):
    context=propagate.extract(dict(request.headers))
    token=attach(context)
    try:
        with tracer.start_as_current_span(operation,kind=SpanKind.SERVER,
                                          attributes={"http.route":request.url.path,"service.name":NAME}) as span:
            started=time.monotonic()
            try:
                apply_fault()
                yield
                requests.add(1,{"route":request.url.path})
            except Exception:
                requests.add(1,{"route":request.url.path})
                failures.add(1,{"route":request.url.path})
                span.set_status(Status(StatusCode.ERROR,"Request failed"))
                span.set_attribute("http.response.status_code",503)
                raise
            finally:
                elapsed_ms=round((time.monotonic()-started)*1000,3)
                span.set_attribute("request.duration_ms",elapsed_ms)
                durations.record(elapsed_ms,{"route":request.url.path})
    finally:detach(token)

def invoke(service:str,path:str="/work"):
    if service not in {"auth","catalog","inventory","cart","checkout","payment","notification","database","cache"}:
        raise RuntimeError("Invalid internal dependency")
    with tracer.start_as_current_span(f"HTTP {service}{path}",kind=SpanKind.CLIENT,
                                      attributes={"server.address":service}) as span:
        headers={}
        propagate.inject(headers)
        try:
            with httpx.Client(timeout=2.0,trust_env=False) as client:
                res=client.get(f"http://{service}:8100{path}",headers=headers)
                span.set_attribute("http.response.status_code",res.status_code)
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError:
            span.set_status(Status(StatusCode.ERROR,"Downstream HTTP request failed"))
            raise HTTPException(503,f"Dependency {service} unavailable") from None

@app.get("/checkout")
def checkout(request:Request):
    if NAME!="gateway":raise HTTPException(404,"Route only exists on gateway")
    with server_span(request,"gateway.checkout"):
        invoke("auth")
        invoke("catalog")
        invoke("cart")
        result=invoke("checkout")
        return {"order_id":result["order_id"],"status":"paid","currency":"TEST"}

@app.get("/work")
def work(request:Request):
    with server_span(request,NAME+".work"):
        if NAME=="auth":
            invoke("database")
        elif NAME=="catalog":
            invoke("cache")
        elif NAME=="cart":
            invoke("inventory")
        elif NAME=="inventory":
            invoke("database")
        elif NAME=="checkout":
            invoke("inventory")
            invoke("payment")
            invoke("notification")
            return {"service":NAME,"order_id":"TEST-ORDER","amount_minor":1299}
        elif NAME=="payment":
            invoke("database")
            return {"service":NAME,"approved":True,"amount_minor":1299,"currency":"TEST"}
        elif NAME=="database":
            # Actual bounded 2-connection pool. Fault reserves both real SQL sessions.
            if not DB_LIMIT.acquire(timeout=.3):
                raise HTTPException(503,"Lab client SQL pool is exhausted")
            try:
                import psycopg
                with psycopg.connect(os.environ["LAB_DATABASE_URL"],connect_timeout=2) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        assert cur.fetchone()==(1,)
            except Exception as exc:
                raise HTTPException(503,"Database unreachable") from exc
            finally:DB_LIMIT.release()
        elif NAME=="cache":
            # Real Redis RESP PING using stdlib socket, no extra dependency.
            import socket
            try:
                with socket.create_connection(("redis",6379),timeout=2) as sock:
                    sock.sendall(b"*1\r\n$4\r\nPING\r\n")
                    if not sock.recv(20).startswith(b"+PONG"):
                        raise OSError("Cache PING failed")
            except OSError as exc:
                raise HTTPException(503,"Cache unreachable") from exc
        return {"service":NAME,"status":"ok"}

@app.on_event("shutdown")
def flush():
    provider.force_flush(timeout_millis=3000)
    meter_provider.shutdown()
