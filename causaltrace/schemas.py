from typing import Literal
from pydantic import BaseModel, Field, field_validator

class EventInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    service: str = Field(min_length=1, max_length=100)
    timestamp: float = Field(gt=0, allow_inf_nan=False)
    latency_ms: float = Field(default=0, ge=0, le=600000)
    error: bool = False
    dependency: str | None = Field(default=None, max_length=100)
    trace_id: str | None = None
    kind: str = Field(default="application", max_length=48)
    detail: dict = Field(default_factory=dict)
    @field_validator("trace_id")
    @classmethod
    def check_trace(cls, v):
        if v is not None and (len(v) != 32 or any(c not in "0123456789abcdef" for c in v)):
            raise ValueError("trace_id must be 32 lowercase hexadecimal characters")
        return v

class EventBatch(BaseModel):
    events: list[EventInput] = Field(min_length=1, max_length=500)

class MetricInput(BaseModel):
    service: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    timestamp: float = Field(gt=0, allow_inf_nan=False)
    value: float = Field(allow_inf_nan=False)
    unit: str = Field(default="", max_length=30)
    attributes: dict = Field(default_factory=dict)

class MetricBatch(BaseModel):
    metrics: list[MetricInput] = Field(min_length=1, max_length=500)

class DeploymentInput(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    service: str = Field(min_length=1, max_length=100)
    timestamp: float = Field(gt=0, allow_inf_nan=False)
    description: str = Field(default="", max_length=300)

class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    affected_services: list[str] = Field(default_factory=list, max_length=50)

class IncidentUpdate(BaseModel):
    status: Literal["open", "investigating", "mitigated", "resolved"]
    version: int = Field(ge=0)

class ExperimentCreate(BaseModel):
    target: Literal["gateway", "auth", "catalog", "inventory", "cart", "checkout", "payment", "notification", "database", "cache"]
    mode: Literal["latency", "timeout", "unavailable", "db_exhaustion", "cache_failure", "saturation", "error", "config"]
    duration_seconds: int = Field(default=20, ge=1, le=120)
    delay_ms: int = Field(default=500, ge=0, le=1200)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)

class BenchmarkInput(BaseModel):
    dataset: str = Field(min_length=3, max_length=100)
    data_origin: Literal["synthetic_fixture", "isolated_lab", "measured_local"]
    result: dict
