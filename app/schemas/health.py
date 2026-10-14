from enum import StrEnum

from pydantic import Field

from app.schemas.common import APIModel


class ComponentStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


class ComponentHealth(APIModel):
    status: ComponentStatus
    latency_ms: float | None = Field(default=None, description="Round-trip time of the probe")
    error: str | None = Field(default=None, description="Error class name if the probe failed")


class HealthResponse(APIModel):
    status: HealthStatus
    version: str
    environment: str
    checks: dict[str, ComponentHealth]
