import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
from fastapi import FastAPI

from app.api.deps import get_health_service
from app.schemas.health import (
    ComponentHealth,
    ComponentStatus,
    HealthResponse,
    HealthStatus,
)
from app.services.health import HealthService

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeConnection:
    def __init__(self, error: Exception | None = None, delay: float = 0) -> None:
        self.error = error
        self.delay = delay

    async def execute(self, _: object) -> None:
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error


class FakeEngine:
    def __init__(self, **kwargs: Any) -> None:
        self.conn = FakeConnection(**kwargs)

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[FakeConnection]:
        yield self.conn


class FakeRedis:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def ping(self) -> bool:
        if self.error:
            raise self.error
        return True


def make_service(engine: FakeEngine, redis: FakeRedis, timeout: float = 0.2) -> HealthService:
    return HealthService(
        engine=cast(Any, engine),
        redis=cast(Any, redis),
        timeout_seconds=timeout,
        version="test",
        environment="test",
    )


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


async def test_all_healthy() -> None:
    report = await make_service(FakeEngine(), FakeRedis()).check()
    assert report.status is HealthStatus.OK
    assert all(c.status is ComponentStatus.OK for c in report.checks.values())
    assert report.checks["database"].latency_ms is not None


async def test_redis_down_is_degraded_and_hides_error_message() -> None:
    redis = FakeRedis(error=ConnectionError("secret-host:6379 refused"))
    report = await make_service(FakeEngine(), redis).check()
    assert report.status is HealthStatus.DEGRADED
    assert report.checks["database"].status is ComponentStatus.OK
    assert report.checks["redis"].error == "ConnectionError"


async def test_slow_database_times_out() -> None:
    report = await make_service(FakeEngine(delay=1), FakeRedis(), timeout=0.05).check()
    assert report.status is HealthStatus.DEGRADED
    assert report.checks["database"].error == "timeout"


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #


class StubHealthService:
    def __init__(self, status: HealthStatus) -> None:
        self.status = status

    async def check(self) -> HealthResponse:
        component = ComponentStatus.OK if self.status is HealthStatus.OK else ComponentStatus.ERROR
        return HealthResponse(
            status=self.status,
            version="test",
            environment="test",
            checks={"database": ComponentHealth(status=component)},
        )


async def test_health_endpoint_ok(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_health_service] = lambda: StubHealthService(HealthStatus.OK)
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.headers["X-Request-ID"]


async def test_health_endpoint_degraded_returns_503(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.dependency_overrides[get_health_service] = lambda: StubHealthService(HealthStatus.DEGRADED)
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 503
    assert resp.json()["checks"]["database"]["status"] == "error"
