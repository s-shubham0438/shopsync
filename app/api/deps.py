"""Typed dependency aliases shared by all routers."""

from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import __version__
from app.adapters.registry import AdapterRegistry
from app.adapters.runner import AdapterRunner
from app.core.auth_http import ACCESS_COOKIE
from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.core.redis import get_redis
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db_session, get_engine
from app.models import User
from app.repositories.catalog import CatalogRepository
from app.services.cache import ProductCache, SearchCache, search_cache_scope
from app.services.catalog import CatalogService
from app.services.health import HealthService
from app.services.messaging import EmailSender, SmsSender
from app.services.rate_limit import RateLimiter
from app.services.search import SearchService


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def get_store_registry(request: Request) -> AdapterRegistry:
    registry: AdapterRegistry = request.app.state.store_registry
    return registry


def get_adapter_runner(
    registry: Annotated[AdapterRegistry, Depends(get_store_registry)],
) -> AdapterRunner:
    return registry.runner


StoreRegistryDep = Annotated[AdapterRegistry, Depends(get_store_registry)]
AdapterRunnerDep = Annotated[AdapterRunner, Depends(get_adapter_runner)]


def get_search_cache(request: Request) -> SearchCache:
    cache: SearchCache = request.app.state.search_cache
    return cache


def get_product_cache(request: Request) -> ProductCache:
    cache: ProductCache = request.app.state.product_cache
    return cache


SearchCacheDep = Annotated[SearchCache, Depends(get_search_cache)]
ProductCacheDep = Annotated[ProductCache, Depends(get_product_cache)]


def get_health_service(settings: SettingsDep, engine: EngineDep, redis: RedisDep) -> HealthService:
    return HealthService(
        engine=engine,
        redis=redis,
        timeout_seconds=settings.health_check_timeout_seconds,
        version=__version__,
        environment=settings.environment.value,
    )


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]


def get_search_service(
    settings: SettingsDep,
    runner: AdapterRunnerDep,
    session: DbSession,
    cache: SearchCacheDep,
) -> SearchService:
    return SearchService(
        runner,
        CatalogRepository(session),
        cache=cache,
        cache_scope=search_cache_scope(settings),
    )


def get_catalog_service(session: DbSession, cache: ProductCacheDep) -> CatalogService:
    return CatalogService(CatalogRepository(session), product_cache=cache)


SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
CatalogServiceDep = Annotated[CatalogService, Depends(get_catalog_service)]


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


# --------------------------------------------------------------------------- #
# Authentication. The user always comes from the verified access token, never from
# anything else the client sends.
# --------------------------------------------------------------------------- #
async def get_optional_user(
    request: Request, settings: SettingsDep, session: DbSession
) -> User | None:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        return None
    try:
        claims = decode_access_token(token, settings)
    except TokenError:
        return None
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        return None
    request.state.user_id = user.id  # for logging; never read back as an authority
    return user


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    if user is None:
        raise UnauthorizedError()
    return user


OptionalUser = Annotated[User | None, Depends(get_optional_user)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def get_email_sender(request: Request) -> EmailSender:
    sender: EmailSender = request.app.state.email_sender
    return sender


def get_sms_sender(request: Request) -> SmsSender:
    sender: SmsSender = request.app.state.sms_sender
    return sender


EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
SmsSenderDep = Annotated[SmsSender, Depends(get_sms_sender)]
