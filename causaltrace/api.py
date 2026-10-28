"""Persistent telemetry API and investigation service.

Writes and, by deployment default, private GET routes are operator-key protected.
Single-user loopback lab, not an enterprise multi-tenant authentication system.
"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import timezone
from hashlib import sha256
import json
import logging
import math
import os
import secrets
import threading
import time
import uuid

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import delete, func, select, inspect
from sqlalchemy.orm import Session

from . import analytics
from .db import (Audit, Benchmark, DependencyEdge, Deployment, Event, Experiment,
                 Incident, Metric, Span, Timeline, make_engine, session_factory, now_utc, insert_ignore)
from .otlp import decode_metrics, decode_traces
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceResponse
from .schemas import (BenchmarkInput, DeploymentInput, EventBatch, ExperimentCreate, IncidentCreate,
                      IncidentUpdate, MetricBatch)
from .settings import Settings

logger = logging.getLogger("causaltrace")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format='%(asctime)s %(levelname)s %(message)s')

class State:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = make_engine(settings.database_url)
        self.sessions = session_factory(self.engine)
        self.ingest_slots = threading.BoundedSemaphore(8)
        self.experiment_slots = threading.BoundedSemaphore(1)
        self.experiment_guard=threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix="lab-run")
        self.shutdown_requested = threading.Event()
    def close(self):
        self.shutdown_requested.set()
        self.pool.shutdown(wait=True,cancel_futures=True)
        self.engine.dispose()

def get_session(request: Request):
    with request.app.state.ct.sessions() as session:
        yield session

def admin(request: Request, x_api_key: str | None = Header(default=None)):
    expected = request.app.state.ct.settings.api_key
    if not x_api_key or not secrets.compare_digest(x_api_key,expected):
        raise HTTPException(401,"Administrative or ingestion key required")

def audit(session: Session, action: str, detail: dict):
    session.add(Audit(action=action,detail=detail))

def bounded_time(seconds: float):
    if abs(seconds-time.time())>86400:
        raise HTTPException(422,"Telemetry timestamp is outside the 24-hour accepted window")

SENSITIVE_FIELDS = ("authorization", "password", "secret", "token", "cookie",
                    "api_key", "apikey", "private_key", "credit_card", "card_number")


def sanitize_telemetry(value, depth: int = 0):
    """Bound nested custom event fields and redact common credential keys.

    Operator-owned telemetry must be minimized at source too: string values
    can contain PII even without recognizable attribute names.
    """
    if depth >= 4:
        return "[truncated-depth]"
    if isinstance(value, dict):
        return {str(key)[:100]: ("[REDACTED]" if any(term in str(key).lower() for term in SENSITIVE_FIELDS)
                                 else sanitize_telemetry(item,depth+1))
                for key,item in list(value.items())[:32]}
    if isinstance(value, list):
        return [sanitize_telemetry(item,depth+1) for item in value[:32]]
    if isinstance(value, float) and not math.isfinite(value):
        return "[invalid-nonfinite]"
    if isinstance(value, (int,float,bool)) or value is None:
        return value
    return str(value)[:500]


def record_spans(session: Session, spans: list[dict]) -> dict:
    unique={}
    for s in spans:
        bounded_time(s["start_ns"]/1e9)
        # Restrict high-cardinality telemetry attributes before persistence.
        s["attributes"]=sanitize_telemetry(s["attributes"])
        unique[(s["trace_id"],s["span_id"])]=s
    inserted=insert_ignore(session,Span,list(unique.values()),["trace_id","span_id"])
    session.flush()
    affected={s["trace_id"] for s in spans}
    for trace_id in affected:
        all_spans=[span_dict(s) for s in session.scalars(select(Span).where(Span.trace_id==trace_id).limit(3000))]
        pairs=analytics.extract_edges(all_spans)
        # The arrival of a late server span supersedes any corresponding
        # client-target inference. Rebuild inferred edges transactionally.
        session.execute(delete(DependencyEdge).where(
            DependencyEdge.trace_id==trace_id,
            DependencyEdge.provenance=="client-target-unconfirmed"))
        # Re-evaluate formerly missing parents on each out-of-order batch.
        dedup={(e["source"],e["target"],e["trace_id"],e["timestamp_ns"]):e for e in pairs}
        insert_ignore(session,DependencyEdge,list(dedup.values()),
                      ["source","target","trace_id","timestamp_ns"])
    return {"accepted":inserted,"duplicates":len(spans)-inserted}

def span_dict(s: Span) -> dict:
    return {"trace_id":s.trace_id,"span_id":s.span_id,"parent_span_id":s.parent_span_id,
            "service":s.service,"operation":s.operation,"start_ns":s.start_ns,
            "end_ns":s.end_ns,"error":s.error,"attributes":s.attributes or {}}

def page(query,session:Session, limit:int, offset:int):
    return session.scalars(query.offset(offset).limit(limit)).all()

def load_analysis(session: Session, limit: int=12000, since_ns: int | None=None,
                  until_ns: int | None=None):
    span_query=select(Span)
    edge_query=select(DependencyEdge)
    deployment_query=select(Deployment)
    if since_ns is not None:
        span_query=span_query.where(Span.start_ns>=since_ns)
        edge_query=edge_query.where(DependencyEdge.timestamp_ns>=since_ns)
        deployment_query=deployment_query.where(Deployment.timestamp_ns>=since_ns)
    if until_ns is not None:
        span_query=span_query.where(Span.start_ns<=until_ns)
        edge_query=edge_query.where(DependencyEdge.timestamp_ns<=until_ns)
        deployment_query=deployment_query.where(Deployment.timestamp_ns<=until_ns)
    samples=session.scalars(span_query.order_by(Span.start_ns.desc()).limit(limit)).all()
    rows=analytics.aggregate([span_dict(s) for s in samples])
    # Explicitly separate bounded computational scope from complete history.
    anomalies=analytics.robust_anomalies(rows)
    edges=session.scalars(edge_query.order_by(DependencyEdge.timestamp_ns.desc()).limit(50000)).all()
    topology=[{"source":e.source,"target":e.target,"timestamp_ns":e.timestamp_ns,
               "latency_ms":e.latency_ms,"error":e.error,"provenance":e.provenance} for e in edges]
    deploy=[{"service":d.service,"timestamp":d.timestamp_ns/1e9} for d in session.scalars(deployment_query.order_by(Deployment.timestamp_ns.desc()).limit(2000))]
    ranking=analytics.rank_causes(anomalies,topology,deploy)
    return rows,anomalies,topology,ranking

def purge(session: Session,days:int):
    cutoff=int((time.time()-days*86400)*1e9)
    # Controlled maintenance, no perpetual unbounded workers.
    counts={}
    for entity,field in [(Span,Span.start_ns),(Event,Event.timestamp_ns),
                         (Metric,Metric.timestamp_ns),(DependencyEdge,DependencyEdge.timestamp_ns)]:
        result=session.execute(delete(entity).where(field<cutoff))
        counts[entity.__tablename__]=result.rowcount
    return counts

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg=getattr(app.state,"ct",None)
    if cfg is None:
        app.state.ct=State(Settings.load())
    # Experiments are in-process workers, not durable queue consumers. If a
    # process died mid-fault, the lab-side TTL is the only guaranteed cleanup.
    # Never reclassify unfinished attempts as successful or verified cleanup.
    with app.state.ct.sessions() as session:
        if inspect(session.get_bind()).has_table("experiments"):
            stale=session.scalars(select(Experiment).where(
                Experiment.status.in_(("queued", "running", "stopping")))).all()
            for item in stale:
                item.status="failed"
                item.ended_at=now_utc()
                item.result={**(item.result or {}), "error": "worker_interrupted_by_restart",
                             "cleanup_verified": False,
                             "recovery_verified": False,
                             "note": "Lab TTL must expire; inspect actual service health before new experiments"}
                audit(session,"lab_interrupted",{"experiment_id":item.id})
            session.commit()
    # Schema creation is managed by Alembic; fail readiness if migrations absent.
    yield
    app.state.ct.close()

def create_app(settings: Settings | None = None) -> FastAPI:
    app=FastAPI(title="CausalTrace",version="1.0.0",lifespan=lifespan)
    if settings is not None:app.state.ct=State(settings)

    @app.middleware("http")
    async def body_limit(request:Request,call_next):
        maximum=request.app.state.ct.settings.ingest_max_bytes
        # All persisted investigations and telemetry are private by default.
        # No cookie-based auth (or CORS) is enabled: this is a single-operator,
        # loopback-bound lab, not a multi-tenant identity system.
        if (request.method in {"GET", "HEAD"} and
                (request.url.path.startswith("/api/") or request.url.path == "/metrics") and
                request.app.state.ct.settings.protect_reads):
            supplied=request.headers.get("x-api-key", "")
            if not supplied or not secrets.compare_digest(supplied, request.app.state.ct.settings.api_key):
                return JSONResponse({"detail":"Read access requires operator key"},status_code=401)
        if request.method in {"POST","PATCH","PUT"}:
            length=request.headers.get("content-length")
            try:
                size=int(length) if length is not None else 0
            except ValueError:
                return JSONResponse({"detail":"Invalid Content-Length"},status_code=400)
            if size<0 or size>maximum:
                return JSONResponse({"detail":"Request body too large or invalid"},status_code=413)
            # Bounded streaming: do not buffer arbitrarily large chunked uploads.
            buffer=bytearray()
            async for chunk in request.stream():
                if len(buffer)+len(chunk)>maximum:
                    return JSONResponse({"detail":"Request body too large"},status_code=413)
                buffer.extend(chunk)
            request._body=bytes(buffer)
        # OTLP routes implement their own semaphore. JSON ingestion also needs
        # backpressure instead of relying solely on worker-thread pool limits.
        requires_slot=request.url.path in {"/api/telemetry/events","/api/telemetry/metrics"}
        slots=request.app.state.ct.ingest_slots
        if requires_slot and not slots.acquire(blocking=False):
            return JSONResponse({"detail":"Ingestion busy; retry with backoff"},status_code=429)
        try:
            return await call_next(request)
        finally:
            if requires_slot:
                slots.release()

    @app.get("/health")
    def health():return {"status":"ok"}

    @app.get("/metrics",response_class=PlainTextResponse)
    def prometheus_metrics(session:Session=Depends(get_session)):
        count=session.scalar(select(func.count()).select_from(Span)) or 0
        metric_count=session.scalar(select(func.count()).select_from(Metric)) or 0
        return ("# HELP causaltrace_stored_spans Current persisted spans\n"
                "# TYPE causaltrace_stored_spans gauge\n"
                f"causaltrace_stored_spans {count}\n"
                "# TYPE causaltrace_stored_metric_points gauge\n"
                f"causaltrace_stored_metric_points {metric_count}\n")

    @app.get("/ready")
    def ready(session:Session=Depends(get_session)):
        try:session.execute(select(func.count()).select_from(Span)).scalar()
        except Exception:raise HTTPException(503,"Database unavailable or schema not migrated")
        return {"status":"ready"}

    @app.post("/api/telemetry/events",dependencies=[Depends(admin)])
    def telemetry_events(batch:EventBatch,request:Request,session:Session=Depends(get_session)):
        if len(batch.events)>request.app.state.ct.settings.ingest_max_events:
            raise HTTPException(413,"Too many telemetry events")
        unique={}
        for event in batch.events:
            bounded_time(event.timestamp)
            unique[event.event_id]={"event_id":event.event_id,"service":event.service,"kind":event.kind,
                "timestamp_ns":int(event.timestamp*1e9),"latency_ms":event.latency_ms,"error":event.error,
                "dependency":event.dependency,"trace_id":event.trace_id,"detail":sanitize_telemetry(event.detail)}
        accepted=insert_ignore(session,Event,list(unique.values()),["event_id"])
        duplicates=len(batch.events)-accepted
        session.commit()
        return {"accepted":accepted,"duplicates":duplicates,"semantics":"best-effort emission, bounded retries, idempotent storage"}

    @app.post("/api/telemetry/metrics",dependencies=[Depends(admin)])
    def telemetry_metrics(batch:MetricBatch,session:Session=Depends(get_session)):
        unique={}
        for m in batch.metrics:
            bounded_time(m.timestamp)
            safe_attrs=sanitize_telemetry(m.attributes)
            fingerprint=sha256(f"{m.service}|{m.name}|{m.timestamp}|{m.value}|{json.dumps(safe_attrs,sort_keys=True)}".encode()).hexdigest()
            unique[fingerprint]={"fingerprint":fingerprint,"service":m.service,"name":m.name,
                                 "timestamp_ns":int(m.timestamp*1e9),"value":m.value,"unit":m.unit,
                                 "attributes":safe_attrs}
        accepted=insert_ignore(session,Metric,list(unique.values()),["fingerprint"])
        duplicates=len(batch.metrics)-accepted
        session.commit()
        return {"accepted":accepted,"duplicates":duplicates}

    @app.post("/v1/traces",dependencies=[Depends(admin)])
    async def otlp_traces(request:Request,session:Session=Depends(get_session)):
        slots=request.app.state.ct.ingest_slots
        if not slots.acquire(blocking=False):raise HTTPException(429,"OTLP buffer full; retry with backoff")
        try:
            try:items=decode_traces(await request.body(),request.headers.get("content-type","application/x-protobuf"))
            except Exception as exc:raise HTTPException(400,"Invalid OTLP trace payload") from exc
            if len(items)>request.app.state.ct.settings.ingest_max_events:
                raise HTTPException(413,"Batch exceeds span ingestion limit")
            record_spans(session,items)
            session.commit()
            # OTLP/HTTP protobuf exporters (including Collector) require a
            # protobuf ExportTraceServiceResponse, not application/json.
            return Response(ExportTraceServiceResponse().SerializeToString(),
                            media_type="application/x-protobuf")
        finally:slots.release()

    @app.post("/v1/metrics",dependencies=[Depends(admin)])
    async def otlp_metrics(request:Request,session:Session=Depends(get_session)):
        slots=request.app.state.ct.ingest_slots
        if not slots.acquire(blocking=False):raise HTTPException(429,"OTLP buffer full")
        try:
            try:items=decode_metrics(await request.body(),request.headers.get("content-type","application/x-protobuf"))
            except Exception as exc:raise HTTPException(400,"Invalid OTLP metric payload") from exc
            if len(items)>request.app.state.ct.settings.ingest_max_events:raise HTTPException(413,"Batch exceeds limit")
            for item in items:bounded_time(item["timestamp_ns"]/1e9)
            unique={i["fingerprint"]:{**i,"attributes":sanitize_telemetry(i["attributes"])} for i in items}
            insert_ignore(session,Metric,list(unique.values()),["fingerprint"])
            session.commit()
            return Response(ExportMetricsServiceResponse().SerializeToString(),
                            media_type="application/x-protobuf")
        finally:slots.release()

    @app.get("/api/overview")
    def overview(session:Session=Depends(get_session)):
        rows,anomalies,edges,ranks=load_analysis(session)
        return {"spans":session.scalar(select(func.count()).select_from(Span)),
                "traces":session.scalar(select(func.count(func.distinct(Span.trace_id)))),
                "services":len({r["service"] for r in rows}),"anomalies":len(anomalies),
                "windows":rows[-500:],"edges":summarize_edges(edges),"candidates":ranks[:5],
                "scope":"last 12000 spans; last 50000 observed dependency calls"}

    @app.get("/api/services")
    def services(session:Session=Depends(get_session)):
        rows,_,_,_=load_analysis(session)
        by=defaultdict(list)
        for r in rows:by[r["service"]].append(r)
        return {"items":[{"id":s,"requests":sum(r["requests"] for r in v),
                            "error_rate":sum(r["error_rate"]*r["requests"] for r in v)/sum(r["requests"] for r in v),
                            "latency_ms":round(sum(r["latency_ms"] for r in v)/len(v),3),
                            "window_count":len(v)} for s,v in sorted(by.items())]}

    @app.get("/api/services/{service_id}")
    def service(service_id:str,session:Session=Depends(get_session)):
        rows,_,_,_=load_analysis(session)
        selected=[r for r in rows if r["service"]==service_id]
        if not selected:raise HTTPException(404,"Service has no observed telemetry")
        return {"id":service_id,"windows":selected[-250:]}

    @app.get("/api/topology")
    def topology(start:float|None=None,end:float|None=None,session:Session=Depends(get_session)):
        q=select(DependencyEdge).order_by(DependencyEdge.timestamp_ns.desc()).limit(50000)
        edges=[e for e in session.scalars(q) if (start is None or e.timestamp_ns>=start*1e9)
               and (end is None or e.timestamp_ns<=end*1e9)]
        return {"edges":summarize_edges([{"source":e.source,"target":e.target,"latency_ms":e.latency_ms,
                 "error":e.error,"provenance":e.provenance} for e in edges]),"limited_to":50000}

    @app.get("/api/traces")
    def traces(limit:int=Query(30,ge=1,le=100),offset:int=Query(0,ge=0,le=100000),session:Session=Depends(get_session)):
        q=select(Span.trace_id,func.min(Span.start_ns),func.max(Span.end_ns),func.count(),func.sum(Span.error.cast(__import__('sqlalchemy').Integer))).group_by(Span.trace_id).order_by(func.max(Span.end_ns).desc()).offset(offset).limit(limit)
        return {"items":[{"trace_id":r[0],"start_ns":r[1],"end_ns":r[2],"spans":r[3],"errors":r[4] or 0} for r in session.execute(q)]}

    @app.get("/api/traces/{trace_id}")
    def trace(trace_id:str,session:Session=Depends(get_session)):
        if len(trace_id)!=32 or any(c not in '0123456789abcdef' for c in trace_id):raise HTTPException(422,"Invalid trace id")
        # The endpoint must not imply a complete trace when its bounded span
        # budget is exhausted. Return the actual count and an explicit flag.
        total=session.scalar(select(func.count()).select_from(Span).where(Span.trace_id==trace_id)) or 0
        if not total:raise HTTPException(404,"Trace not found")
        spans=[span_dict(s) for s in session.scalars(select(Span).where(Span.trace_id==trace_id)
              .order_by(Span.start_ns,Span.id).limit(3000))]
        return {"trace_id":trace_id,**analytics.reconstruct(spans),"edges":analytics.extract_edges(spans),
                "total_spans":total,"returned_spans":len(spans),"truncated":total>len(spans),
                "warning_if_truncated":"Trace and topology may be incomplete" if total>len(spans) else None}

    @app.get("/api/metrics")
    def metrics(service:str|None=None,name:str|None=None,limit:int=Query(300,ge=1,le=1000),session:Session=Depends(get_session)):
        q=select(Metric).order_by(Metric.timestamp_ns.desc())
        if service:q=q.where(Metric.service==service)
        if name:q=q.where(Metric.name==name)
        return {"items":[{"service":m.service,"name":m.name,"timestamp":m.timestamp_ns/1e9,"value":m.value,"unit":m.unit}
                         for m in session.scalars(q.limit(limit))]}

    @app.get("/api/anomalies")
    def anomalies(method:str=Query("robust",pattern="^(robust|threshold|ml)$"),session:Session=Depends(get_session)):
        rows,a,_,_=load_analysis(session)
        if method=="robust":return {"items":a,"method":method}
        if method=="threshold":return {"items":analytics.threshold_anomalies(rows),"method":method}
        from pathlib import Path
        from .ml import features,load_trusted,MODEL_VERSION
        location=Path(os.getenv("CAUSALTRACE_ML_MODEL", "artifacts/iforest.pkl"))
        if not location.is_file():
            raise HTTPException(503,"Fitted model absent; execute python scripts/train_ml.py")
        model=load_trusted(location)
        if not rows:return {"items":[],"method":"experimental_iforest","version":MODEL_VERSION}
        scores=model.decision_function(features(rows))
        return {"items":[{"service":r["service"],"start":r["start"],"metric":"multivariate",
                           "value":float(score),"score":round(float(-score),4),"detector":MODEL_VERSION,
                           "warning":"trained on synthetic healthy fixtures, not production-calibrated"}
                          for r,score in zip(rows,scores) if score<0],
                "method":"experimental_iforest","version":MODEL_VERSION,"training_domain":"synthetic fixture"}

    @app.post("/api/deployments",dependencies=[Depends(admin)])
    def add_deployment(data:DeploymentInput,session:Session=Depends(get_session)):
        bounded_time(data.timestamp)
        if session.get(Deployment,data.id):return {"status":"duplicate"}
        session.add(Deployment(id=data.id,service=data.service,timestamp_ns=int(data.timestamp*1e9),description=data.description))
        audit(session,"deployment",data.model_dump());session.commit()
        return {"status":"recorded"}

    def serialize_incident(inc:Incident):
        return {"id":inc.id,"title":inc.title,"status":inc.status,"created_at":inc.created_at,
                "updated_at":inc.updated_at,"affected_services":inc.affected_services,
                "hypotheses":inc.hypotheses,"evidence":inc.evidence,"version":inc.version}

    @app.get("/api/incidents")
    def incidents(limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),session:Session=Depends(get_session)):
        return {"items":[serialize_incident(inc) for inc in page(select(Incident).order_by(Incident.created_at.desc()),session,limit,offset)]}

    @app.post("/api/incidents",dependencies=[Depends(admin)],status_code=201)
    def create_incident(data:IncidentCreate,session:Session=Depends(get_session)):
        inc=Incident(id=str(uuid.uuid4()),title=data.title,affected_services=data.affected_services)
        session.add(inc);session.add(Timeline(incident_id=inc.id,actor="api",action="created",detail=data.model_dump()))
        audit(session,"create_incident",{"incident":inc.id});session.commit()
        return serialize_incident(inc)

    @app.get("/api/incidents/{incident_id}")
    def incident(incident_id:str,session:Session=Depends(get_session)):
        inc=session.get(Incident,incident_id)
        if not inc:raise HTTPException(404,"Incident not found")
        history=session.scalars(select(Timeline).where(Timeline.incident_id==incident_id).order_by(Timeline.id)).all()
        return {**serialize_incident(inc),"history":[{"timestamp":t.timestamp,"action":t.action,
                "actor":t.actor,"detail":t.detail} for t in history]}

    @app.patch("/api/incidents/{incident_id}",dependencies=[Depends(admin)])
    def update_incident(incident_id:str,data:IncidentUpdate,session:Session=Depends(get_session)):
        inc=session.get(Incident,incident_id)
        if not inc:raise HTTPException(404,"Incident not found")
        if inc.version!=data.version:raise HTTPException(409,"Stale version; reload incident")
        allowed={"open":{"investigating","resolved"},"investigating":{"mitigated","resolved"},
                 "mitigated":{"resolved","investigating"},"resolved":set()}
        if data.status not in allowed[inc.status]:raise HTTPException(409,"Invalid status transition")
        before=inc.status;inc.status=data.status;inc.updated_at=now_utc();inc.version+=1
        session.add(Timeline(incident_id=inc.id,actor="operator",action="status_transition",
                             detail={"from":before,"to":data.status}));audit(session,"incident_status",{"id":inc.id,"status":inc.status})
        session.commit();return serialize_incident(inc)

    @app.get("/api/incidents/{incident_id}/timeline")
    def incident_timeline(incident_id:str,session:Session=Depends(get_session)):
        inc=session.get(Incident,incident_id)
        if not inc:raise HTTPException(404,"Incident not found")
        span_start=int((inc.created_at.replace(tzinfo=timezone.utc) if inc.created_at.tzinfo is None else inc.created_at).timestamp()*1e9)-3600*int(1e9)
        events=session.scalars(select(Event).where(Event.timestamp_ns>=span_start).order_by(Event.timestamp_ns.desc()).limit(300)).all()
        changes=session.scalars(select(Deployment).where(Deployment.timestamp_ns>=span_start).order_by(Deployment.timestamp_ns.desc()).limit(100)).all()
        history=session.scalars(select(Timeline).where(Timeline.incident_id==incident_id).order_by(Timeline.timestamp.desc()).limit(200)).all()
        return {"items":sorted(
           [{"time":e.timestamp_ns/1e9,"type":"telemetry_event","service":e.service,"detail":e.detail,"error":e.error} for e in events]
           +[{"time":d.timestamp_ns/1e9,"type":"deployment","service":d.service,"detail":{"description":d.description}} for d in changes]
           +[{"time":t.timestamp.timestamp(),"type":"incident_change","service":"","detail":{"action":t.action,**(t.detail or {})}} for t in history],
           key=lambda e:e["time"]),"scope":"up to 1h before incident creation, bounded read"}

    @app.post("/api/incidents/detect",dependencies=[Depends(admin)],status_code=201)
    def detect_incident(session:Session=Depends(get_session)):
        rows,anomalies,edges,ranking=load_analysis(session)
        if not anomalies:raise HTTPException(422,"Insufficient statistical evidence for incident creation")
        affected=sorted({a["service"] for a in anomalies[-100:]})
        inc=Incident(id=str(uuid.uuid4()),title=f"Telemetry anomalies: {', '.join(affected[:3])}",
                     affected_services=affected,hypotheses=ranking[:25],evidence=anomalies[-100:])
        session.add(inc)
        session.add(Timeline(incident_id=inc.id,actor="detector",action="detected",
                            detail={"signals":len(anomalies),"method":"rolling_mad"}))
        audit(session,"detected_incident",{"id":inc.id,"signals":len(anomalies)})
        session.commit()
        return serialize_incident(inc)

    @app.get("/api/incidents/{incident_id}/root-causes")
    def incident_roots(incident_id:str,session:Session=Depends(get_session)):
        inc=session.get(Incident,incident_id)
        if not inc:raise HTTPException(404,"Incident not found")
        return {"incident_id":inc.id,"items":inc.hypotheses,"causality":"observational hypotheses"}

    @app.post("/api/incidents/{incident_id}/analyze",dependencies=[Depends(admin)])
    def analyze_incident(incident_id:str,session:Session=Depends(get_session)):
        inc=session.get(Incident,incident_id)
        if not inc:raise HTTPException(404,"Incident not found")
        rows,anomalies,edges,ranking=load_analysis(session)
        # Do not filter hypotheses to the incident's visibly affected services:
        # the true faulty dependency can be outside the initial blast-radius list.
        filtered=ranking
        inc.hypotheses=filtered[:25]
        inc.evidence=anomalies[-100:]
        inc.updated_at=now_utc();inc.version+=1
        session.add(Timeline(incident_id=inc.id,actor="analysis",action="analyzed",
                             detail={"candidate_count":len(filtered),"anomaly_count":len(anomalies)}))
        session.commit()
        return {"incident_id":inc.id,"candidates":filtered[:25],"anomalies":anomalies[-100:],
                "disclaimer":"Correlations and graph propagation do not establish causation"}

    @app.get("/api/reports/{incident_id}")
    def report(incident_id:str,session:Session=Depends(get_session)):
        record=incident(incident_id,session)
        return {"report_version":1,"generated_at":now_utc(),"incident":record,
                "evidence_basis":"observational telemetry","proven_cause":None,
                "note":"Ground-truth intervention results appear only in experiment records"}

    @app.post("/api/benchmarks",dependencies=[Depends(admin)],status_code=201)
    def record_benchmark(body:BenchmarkInput,session:Session=Depends(get_session)):
        # Stores operator-submitted evaluation records with explicit provenance.
        # These records are not independent cryptographic attestations.
        identifier=str(uuid.uuid4())
        session.add(Benchmark(id=identifier,dataset=body.dataset,
                              result={"data_origin":body.data_origin,"metrics":body.result,
                                      "verification":"operator-submitted, not independently attested"}))
        audit(session,"benchmark_import",{"id":identifier,"data_origin":body.data_origin})
        session.commit()
        return {"id":identifier,"dataset":body.dataset,"data_origin":body.data_origin}

    @app.get("/api/benchmarks")
    def benchmarks(session:Session=Depends(get_session)):
        return {"items":[{"id":b.id,"ran_at":b.ran_at,"dataset":b.dataset,"result":b.result}
                         for b in session.scalars(select(Benchmark).order_by(Benchmark.ran_at.desc()).limit(50))]}

    @app.get("/api/lab/experiments")
    def experiments(session:Session=Depends(get_session)):
        return {"items":[experiment_dict(e) for e in session.scalars(select(Experiment).order_by(Experiment.started_at.desc()).limit(100))]}

    @app.get("/api/lab/experiments/{experiment_id}")
    def experiment(experiment_id:str,session:Session=Depends(get_session)):
        row=session.get(Experiment,experiment_id)
        if not row:raise HTTPException(404,"Experiment not found")
        return experiment_dict(row)

    @app.post("/api/lab/experiments",dependencies=[Depends(admin)],status_code=202)
    def start_experiment(data:ExperimentCreate,request:Request,session:Session=Depends(get_session)):
        cfg=request.app.state.ct
        if not cfg.settings.lab_enabled:raise HTTPException(403,"Disabled outside isolated Docker Compose lab")
        if (data.mode=="db_exhaustion" and data.target!="database") or (data.mode=="cache_failure" and data.target!="cache"):
            raise HTTPException(422,"This fault mode must target its matching dependency service")
        if not cfg.experiment_slots.acquire(blocking=False):raise HTTPException(429,"One experiment at a time to prevent telemetry contamination")
        exp=Experiment(id=str(uuid.uuid4()),target=data.target,mode=data.mode,status="queued")
        try:
            session.add(exp)
            audit(session,"lab_start",{"id":exp.id,"target":data.target,"mode":data.mode})
            session.commit()
        except Exception:
            # A failed transaction must not consume the only lab admission slot.
            cfg.experiment_slots.release()
            raise
        try:
            cfg.pool.submit(run_experiment,cfg,exp.id,data)
        except RuntimeError:
            cfg.experiment_slots.release()
            exp.status="failed"
            exp.result={"error":"worker_unavailable"}
            session.commit()
            raise HTTPException(503,"Lab worker unavailable")
        return experiment_dict(exp)

    @app.post("/api/lab/experiments/{experiment_id}/stop",dependencies=[Depends(admin)])
    def stop_experiment(experiment_id:str,request:Request,session:Session=Depends(get_session)):
        row=session.get(Experiment,experiment_id)
        if not row:raise HTTPException(404,"Experiment not found")
        if not request.app.state.ct.settings.lab_enabled:raise HTTPException(403,"Lab disabled")
        # Serialize cancellation and fault activation: otherwise a worker can
        # inject *after* an operator's successful stop request.
        cfg=request.app.state.ct
        with cfg.experiment_guard:
            session.refresh(row)
            previously_running=row.status == "running"
            if row.status in {"queued","running"}:
                row.status="stopping"
            audit(session,"lab_stop",{"id":row.id})
            session.commit()
            if previously_running:
                # The TTL in every injected fault remains a second safety net.
                set_lab_fault(row.target,{"mode":"none","duration_seconds":1},cfg.settings.api_key)
        return experiment_dict(row)

    @app.post("/api/admin/retention",dependencies=[Depends(admin)])
    def retention(request:Request,session:Session=Depends(get_session)):
        outcome=purge(session,request.app.state.ct.settings.retention_days)
        audit(session,"retention",outcome);session.commit();return outcome

    @app.get("/api/system")
    def system(request:Request,session:Session=Depends(get_session)):
        return {"lab_enabled":request.app.state.ct.settings.lab_enabled,
                "retention_days":request.app.state.ct.settings.retention_days,
                "max_batch":request.app.state.ct.settings.ingest_max_events,
                "database_type":request.app.state.ct.engine.dialect.name,
                "spans":session.scalar(select(func.count()).select_from(Span)),
                "metrics":session.scalar(select(func.count()).select_from(Metric))}
    return app


def summarize_edges(edges:list[dict]):
    counts=defaultdict(list)
    for e in edges:counts[(e["source"],e["target"])].append(e)
    return [{"source":a,"target":b,"observations":len(group),
             "error_rate":sum(e.get("error",False) for e in group)/len(group),
             "latency_ms":round(sum(e.get("latency_ms",0) for e in group)/len(group),2),
             "provenance":sorted({e.get("provenance","unknown") for e in group})}
            for (a,b),group in sorted(counts.items())]

def experiment_dict(row:Experiment):
    return {"id":row.id,"target":row.target,"mode":row.mode,"status":row.status,
            "started_at":row.started_at,"ended_at":row.ended_at,"result":row.result}

def set_lab_fault(service:str,body:dict,key:str):
    # Fixed literal DNS from allowlist; no arbitrary hosts or ports from requests.
    if service not in {"gateway", "auth", "catalog", "inventory", "cart",
                       "checkout", "payment", "notification", "database", "cache"}:
        raise ValueError("Service not in permitted lab allowlist")
    with httpx.Client(timeout=3.0,trust_env=False) as client:
        response=client.post(f"http://{service}:8100/_lab/fault",json=body,headers={"x-lab-key":key})
        response.raise_for_status()

def online_fault_alert_seen(anomalies: list[dict], fault_start_ns: int, observed_at_ns: int) -> bool:
    """True only for a fully elapsed fault-period bucket seen by the active worker.

    Reject the injection-boundary bucket and any not-yet-finished bucket;
    retrospective anomaly onset is not a measured alert delivery time.
    """
    width=5_000_000_000
    first_complete_start=((fault_start_ns+width-1)//width)*width
    return any(first_complete_start <= int(a["start"]*1e9) and
               int(a["start"]*1e9)+width <= observed_at_ns for a in anomalies)



def complete_incident_detection_windows(
    rows: list[dict], anomalies: list[dict], fault_start_ns: int, fault_end_ns: int
) -> list[dict]:
    """Score *incident-level* alerting once per complete observed time window.

    Service-level rows within a bucket must not multiply its sample weight;
    conversely, one service alert is sufficient to signal an incident. A
    healthy service in that bucket is never independently called anomalous.
    Empty (unobserved) buckets are excluded, not imputed as true negatives.
    """
    width = 5_000_000_000
    observed: dict[int, set[str]] = defaultdict(set)
    alerting: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        observed[int(row["start"] * 1e9)].add(row["service"])
    for anomaly in anomalies:
        alerting[int(anomaly["start"] * 1e9)].add(anomaly["service"])
    windows = []
    for start in sorted(observed):
        finish = start + width
        if finish <= fault_start_ns:
            phase = "baseline"
        elif start >= fault_start_ns and finish <= fault_end_ns:
            phase = "fault"
        else:
            continue  # Exclude ambiguous intervention/recovery boundary buckets.
        windows.append({"start_ns": start, "phase": phase,
                        "alert": bool(alerting.get(start)),
                        "alert_services": sorted(alerting.get(start, set())),
                        "observed_services": sorted(observed[start]),
                        "evaluation_unit": "incident_time_bucket"})
    return windows


def run_experiment(cfg: State, experiment_id: str, data: ExperimentCreate):
    """Collect genuine checkout telemetry in an experiment-bounded time interval.

    Best-effort service fault controls are TTL-limited. A stopped job never
    silently becomes completed, and cleanup failures mark the job failed.
    Ground truth is excluded from all inference and supplied only for scoring.
    """
    outcome = {"ground_truth": {"target":data.target,"mode":data.mode},
               "baseline": [], "fault": [], "recovery": [],
               "telemetry_provenance": "persisted OTLP spans, windowed by experiment time"}
    fault_set = False
    cleanup_error = None
    was_stopped = False
    baseline_start_ns = int(time.time()*1e9)
    fault_start_ns = None
    fault_end_ns = None
    online_detection_observed_at_ns = None
    next_detection_poll = 0.0

    def stopping():
        if cfg.shutdown_requested.is_set():
            return True
        with cfg.sessions() as session:
            record = session.get(Experiment, experiment_id)
            return record is None or record.status == "stopping"

    def sample(client: httpx.Client):
        start = time.monotonic()
        try:
            response = client.get("http://gateway:8100/checkout")
            return {"http_status": response.status_code,
                    "latency_ms": round((time.monotonic()-start)*1000,2)}
        except httpx.HTTPError:
            return {"http_status": 0,
                    "latency_ms": round((time.monotonic()-start)*1000,2)}

    try:
        with cfg.sessions() as db:
            row=db.get(Experiment,experiment_id)
            if row is None:
                raise RuntimeError("Experiment record disappeared")
            if row.status == "stopping":
                was_stopped=True
            else:
                row.status="running"
                db.commit()

        if not was_stopped:
            with httpx.Client(timeout=3,trust_env=False) as client:
                # Six separate rolling-MAD reference windows before intervention.
                for _ in range(6):
                    if stopping():
                        was_stopped=True
                        break
                    outcome["baseline"].extend(sample(client) for _ in range(3))
                    if cfg.shutdown_requested.wait(5.1):
                        was_stopped=True
                        break
                if not was_stopped and stopping():
                    was_stopped=True
                if not was_stopped:
                    with cfg.experiment_guard:
                        # Cancellation may arrive between the preceding poll
                        # and fault dispatch. Re-check while holding the guard.
                        if stopping():
                            was_stopped=True
                        else:
                            fault_start_ns=int(time.time()*1e9)
                            # The remote control may apply a fault but lose its
                            # response. Mark cleanup necessary *before* dispatch.
                            fault_set=True
                            set_lab_fault(data.target,{**data.model_dump(exclude={"target"}),
                                                      "duration_seconds":data.duration_seconds},cfg.settings.api_key)
                    if not was_stopped and data.mode=="config":
                        with cfg.sessions() as db:
                            db.add(Deployment(id=f"lab-{experiment_id}",service=data.target,
                                timestamp_ns=fault_start_ns,
                                description="Explicit isolated laboratory configuration-fault activation"))
                            db.commit()
                    deadline=time.monotonic()+data.duration_seconds if not was_stopped else time.monotonic()
                    while not was_stopped and time.monotonic()<deadline and len(outcome["fault"])<120:
                        if stopping():
                            was_stopped=True
                            break
                        outcome["fault"].append(sample(client))
                        # Observe detection *while the fault is active*. A later
                        # offline analysis is not a measured online detection delay.
                        if time.monotonic() >= next_detection_poll:
                            next_detection_poll = time.monotonic() + 2.0
                            if fault_start_ns is not None and online_detection_observed_at_ns is None:
                                with cfg.sessions() as detection_db:
                                    _, seen, _, _ = load_analysis(
                                        detection_db, since_ns=baseline_start_ns,
                                        until_ns=time.time_ns())
                                if online_fault_alert_seen(seen, fault_start_ns, time.time_ns()):
                                    online_detection_observed_at_ns = time.time_ns()
                        if cfg.shutdown_requested.wait(.15):
                            was_stopped=True
                            break
                    if fault_set:
                        fault_end_ns=int(time.time()*1e9)
                        set_lab_fault(data.target,{"mode":"none","duration_seconds":1},cfg.settings.api_key)
                        fault_set=False
                        outcome["recovery"]=[sample(client) for _ in range(8)]
                        # Explicit cancellation still requires a healthy recovery.
                        if any(r["http_status"]!=200 for r in outcome["recovery"]):
                            raise RuntimeError("Checkout did not recover after fault cleanup")

        if not was_stopped and fault_start_ns is not None:
            # Allow the SDK exporter + Collector bounded queues to flush.
            if cfg.shutdown_requested.wait(3):
                was_stopped=True
            else:
                with cfg.sessions() as db:
                    rows, anomalies, edges, ranking = load_analysis(db, since_ns=baseline_start_ns,
                        until_ns=int(time.time()*1e9))
                    # Aggregation floors timestamps into five-second buckets;
                    # include the bucket containing the intervention boundary.
                    bucket_start=(fault_start_ns//5_000_000_000)*5_000_000_000
                    # Exclude the intervention boundary and post-cleanup anomalies;
                    # neither is reliable evidence of fault-period detection.
                    first_full_fault_bucket=((fault_start_ns+4_999_999_999)//5_000_000_000)*5_000_000_000
                    experiment_signals=[a for a in anomalies if
                        first_full_fault_bucket <= int(a["start"]*1e9) and
                        int(a["start"]*1e9)+5_000_000_000 <= fault_end_ns]
                    outcome["recorded_windows"] = len(rows)
                    outcome["recorded_dependency_edges"] = len(edges)
                    outcome["baseline_interval_ns"] = [baseline_start_ns,fault_start_ns]
                    outcome["fault_interval_ns"] = [fault_start_ns,fault_end_ns]
                    outcome["detection"]={"anomaly_count":len(experiment_signals),
                        "detected_services":sorted({a["service"] for a in experiment_signals}),
                        "first_detection_at_ns":min((int(a["start"]*1e9) for a in experiment_signals),default=None),
                        "timing_basis":"complete persisted five-second windows; retrospective except separately recorded online observation"}
                    # Evaluate windows only after ranking. Ground truth MUST NOT
                    # enter analytics.rank_causes or detector feature extraction.
                    # A boundary-spanning bucket is ambiguous and excluded.
                    first_full_fault_bucket=((fault_start_ns+4_999_999_999)//5_000_000_000)*5_000_000_000
                    last_fault_bucket=(fault_end_ns//5_000_000_000)*5_000_000_000 if fault_end_ns else first_full_fault_bucket
                    # Count one incident-level alert per complete time bucket.
                    # A single alerting service does not automatically imply
                    # that every observed peer is anomalous.
                    outcome["detection_windows"] = complete_incident_detection_windows(
                        rows, anomalies, fault_start_ns, fault_end_ns)
                    # Timing starts when the remote injection was acknowledged,
                    # not when an offline 5-second bucket began. A retrospective
                    # alert with no online observation has unknown delay.
                    outcome["online_detection_observed_at_ns"] = online_detection_observed_at_ns
                    outcome["detection_delay_seconds"]=(
                        max(0,(online_detection_observed_at_ns-fault_start_ns)/1e9)
                        if online_detection_observed_at_ns is not None else None)
                    outcome["ranking"]=[c["service"] for c in ranking]
                    outcome["root_cause_evidence"]=ranking[:10]
                    outcome["ranking_provenance"]="anomaly + observed topology + timestamps + deployment events; no fault labels"
                    outcome["ground_truth_rank"]=(outcome["ranking"].index(data.target)+1
                            if data.target in outcome["ranking"] else None)
                    # Empty spans cannot count as a successful fault-injection experiment.
                    if not rows or not edges:
                        raise RuntimeError("No persisted distributed telemetry observed during lab run")
                    if not outcome["fault"]:
                        raise RuntimeError("No fault-period checkout requests were sampled")
                    if any(r["http_status"]!=200 for r in outcome["baseline"]):
                        raise RuntimeError("Pre-intervention checkout baseline was not healthy")
                    if data.mode in {"latency", "saturation"}:
                        baseline_latency=sum(r["latency_ms"] for r in outcome["baseline"])/len(outcome["baseline"])
                        fault_latency=sum(r["latency_ms"] for r in outcome["fault"])/len(outcome["fault"])
                        expected_increase = max(50,data.delay_ms*.30) if data.mode=="latency" else 50
                        if fault_latency-baseline_latency < expected_increase:
                            raise RuntimeError("Injected slowdown produced no measurable checkout impact")
                    elif data.mode in {"error","unavailable","timeout","db_exhaustion","cache_failure","config"}:
                        if not any(r["http_status"]!=200 for r in outcome["fault"]):
                            raise RuntimeError("Injected failure did not affect checkout HTTP responses")
                    if any(r["http_status"]!=200 for r in outcome["recovery"]):
                        raise RuntimeError("Checkout did not recover after fault cleanup")
        outcome["cleanup_verified"] = not fault_set
        outcome["recovery_verified"] = bool(outcome["recovery"]) and all(r["http_status"]==200 for r in outcome["recovery"])
        with cfg.sessions() as db:
            row=db.get(Experiment,experiment_id)
            if row:
                row.status="cancelled" if was_stopped else "completed"
                row.ended_at=now_utc()
                row.result=outcome
                db.commit()
    except Exception as exc:
        logger.exception("Laboratory experiment failed")
        outcome["error"]={"type":type(exc).__name__,"detail":str(exc)[:300]}
        with cfg.sessions() as db:
            row=db.get(Experiment,experiment_id)
            if row:
                row.status="failed"
                row.ended_at=now_utc()
                row.result=outcome
                db.commit()
    finally:
        if fault_set:
            try:
                set_lab_fault(data.target,{"mode":"none","duration_seconds":1},cfg.settings.api_key)
            except Exception as exc:
                cleanup_error=type(exc).__name__
                logger.exception("Lab cleanup failed; injected fault TTL provides final protection")
        if fault_set:
            with cfg.sessions() as db:
                row=db.get(Experiment,experiment_id)
                if row:
                    if cleanup_error:
                        row.status="failed"
                    row.ended_at=now_utc()
                    row.result={**(row.result or {}),"cleanup_verified":cleanup_error is None,
                                **({"cleanup_error":cleanup_error} if cleanup_error else {})}
                    db.commit()
        cfg.experiment_slots.release()

# Do not validate environment until lifespan starts: imports remain safe for unit tests.
app=create_app()
