import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.schemas.health import ComponentHealth, ComponentStatus, HealthResponse, HealthStatus

logger = logging.getLogger(__name__)


class HealthService:
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        redis: Redis,
        timeout_seconds: float,
        version: str,
        environment: str,
    ) -> None:
        self._engine = engine
        self._redis = redis
        self._timeout = timeout_seconds
        self._version = version
        self._environment = environment

    async def check(self) -> HealthResponse:
        database, redis = await asyncio.gather(
            self._probe("database", self._ping_database),
            self._probe("redis", self._ping_redis),
        )
        checks = {"database": database, "redis": redis}
        healthy = all(c.status is ComponentStatus.OK for c in checks.values())
        return HealthResponse(
            status=HealthStatus.OK if healthy else HealthStatus.DEGRADED,
            version=self._version,
            environment=self._environment,
            checks=checks,
        )

    async def _ping_database(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def _ping_redis(self) -> None:
        await self._redis.ping()

    async def _probe(self, name: str, ping: Callable[[], Awaitable[None]]) -> ComponentHealth:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._timeout):
                await ping()
        except TimeoutError:
            logger.warning("health_check_timeout", extra={"component": name})
            return ComponentHealth(status=ComponentStatus.ERROR, error="timeout")
        except Exception as exc:
            # Log the full error server-side; expose only the class name publicly.
            logger.warning("health_check_failed", extra={"component": name, "error": repr(exc)})
            return ComponentHealth(status=ComponentStatus.ERROR, error=type(exc).__name__)
        return ComponentHealth(
            status=ComponentStatus.OK,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
