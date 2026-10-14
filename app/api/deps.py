"""Typed dependency aliases shared by all routers."""

from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import __version__
from app.core.config import Settings
from app.core.redis import get_redis
from app.db.session import get_db_session, get_engine
from app.services.health import HealthService


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def get_health_service(settings: SettingsDep, engine: EngineDep, redis: RedisDep) -> HealthService:
    return HealthService(
        engine=engine,
        redis=redis,
        timeout_seconds=settings.health_check_timeout_seconds,
        version=__version__,
        environment=settings.environment.value,
    )


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
