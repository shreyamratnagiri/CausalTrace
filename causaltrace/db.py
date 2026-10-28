"""SQLAlchemy durable models. SQLite is supported only for lightweight local tests."""
from datetime import datetime, timezone
from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String,
                        UniqueConstraint, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase):
    pass

def now_utc():
    return datetime.now(timezone.utc)

class Span(Base):
    __tablename__ = "spans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    span_id: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(16))
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(180), nullable=False)
    start_ns: Mapped[int] = mapped_column(nullable=False)
    end_ns: Mapped[int] = mapped_column(nullable=False)
    error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (UniqueConstraint("trace_id", "span_id"),
                      Index("ix_spans_service_start", "service", "start_ns"),
                      Index("ix_spans_trace_start", "trace_id", "start_ns"))

class Event(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), default="application")
    timestamp_ns: Mapped[int] = mapped_column(nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[bool] = mapped_column(Boolean, default=False)
    dependency: Mapped[str | None] = mapped_column(String(100))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (Index("ix_events_service_time", "service", "timestamp_ns"),)

class Metric(Base):
    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    timestamp_ns: Mapped[int] = mapped_column(nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(30), default="")
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (Index("ix_metric_service_time", "service", "timestamp_ns"),)

class DependencyEdge(Base):
    __tablename__ = "dependency_edges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(100))
    timestamp_ns: Mapped[int] = mapped_column(nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    latency_ms: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[str] = mapped_column(String(30), default="span-parent")
    __table_args__ = (UniqueConstraint("source", "target", "trace_id", "timestamp_ns"),
                      Index("ix_edge_time", "timestamp_ns"),)

class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    service: Mapped[str] = mapped_column(String(100))
    timestamp_ns: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(String(300), default="")

class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    affected_services: Mapped[list] = mapped_column(JSON, default=list)
    hypotheses: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=0)

class Timeline(Base):
    __tablename__ = "timeline"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (Index("ix_timeline_incident", "incident_id", "timestamp"),)

class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="requested")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict] = mapped_column(JSON, default=dict)

class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    action: Mapped[str] = mapped_column(String(70))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

class Benchmark(Base):
    __tablename__ = "benchmarks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    dataset: Mapped[str] = mapped_column(String(100))
    result: Mapped[dict] = mapped_column(JSON)

def make_engine(url: str):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
    return create_engine(url, **kwargs)

def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def insert_ignore(session, model, values: list[dict], conflict_columns: list[str]) -> int:
    """Atomic idempotent inserts for supported SQLite/PostgreSQL engines.

    Delivery is not exactly-once: retries can replay requests, but unique keys
    make persistence idempotent for identical fingerprints.
    """
    if not values:
        return 0
    dialect=session.get_bind().dialect.name
    if dialect=="postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect=="sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Unsupported persistence dialect")
    result=session.execute(insert(model).values(values).on_conflict_do_nothing(index_elements=conflict_columns))
    return result.rowcount
