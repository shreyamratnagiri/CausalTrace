"""Validated deployment configuration; no committed credentials."""
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str
    api_key: str
    retention_days: int
    ingest_max_events: int
    ingest_max_bytes: int
    lab_enabled: bool
    lab_services: tuple[str, ...]
    protect_reads: bool = False  # explicit opt-out only in unit fixtures; deployment defaults secure

    @classmethod
    def load(cls) -> "Settings":
        key = os.getenv("CAUSALTRACE_API_KEY", "")
        if len(key) < 16:
            raise ValueError("CAUSALTRACE_API_KEY must contain at least 16 characters")
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./causaltrace.db"),
            api_key=key,
            retention_days=max(1, min(365, int(os.getenv("RETENTION_DAYS", "7")))),
            ingest_max_events=max(1, min(5000, int(os.getenv("INGEST_MAX_EVENTS", "500")))),
            ingest_max_bytes=max(1024, min(4_194_304, int(os.getenv("INGEST_MAX_BYTES", "1048576")))),
            lab_enabled=os.getenv("CAUSALTRACE_LAB", "") == "isolated-compose-only",
            lab_services=("gateway", "auth", "catalog", "inventory", "cart", "checkout", "payment", "notification", "database", "cache"),
            protect_reads=os.getenv("CAUSALTRACE_PROTECT_READS", "1") == "1",
        )
