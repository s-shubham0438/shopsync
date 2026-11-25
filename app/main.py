import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.adapters.registry import AdapterRegistry
from app.api.v1.router import api_router
from app.core.config import API_V1_PREFIX, Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.redis import create_redis, redact_url
from app.core.security import warm_up as warm_up_security
from app.db.session import create_engine, create_sessionmaker
from app.services.cache import JsonCache, ProductCache, SearchCache
from app.services.messaging import build_email_sender, build_sms_sender
from app.services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # Every resource registers its cleanup the moment it exists, so a failure later in startup
    # still closes whatever was already created. On shutdown cleanups run in reverse order
    # (Redis, then the DB engine, then the store adapters); one failing cleanup doesn't skip
    # the others.
    async with AsyncExitStack() as resources:
        # Built first: an unusable store-adapter configuration fails startup before any
        # connections are opened.
        store_registry = AdapterRegistry.from_settings(settings)
        resources.push_async_callback(store_registry.aclose)
        app.state.store_registry = store_registry

        # Both clients connect lazily, so the API starts even if Postgres/Redis are
        # down; /health reports their status.
        engine = create_engine(settings)
        resources.push_async_callback(engine.dispose)
        app.state.db_engine = engine
        app.state.db_sessionmaker = create_sessionmaker(engine)

        redis = create_redis(settings)
        resources.push_async_callback(redis.aclose)
        app.state.redis = redis

        # Fail-open caches over the same client: Redis being down never breaks search.
        cache_store = JsonCache.from_settings(redis, settings)
        app.state.search_cache = SearchCache.from_settings(cache_store, settings)
        app.state.product_cache = ProductCache(cache_store, ttl=settings.cache_ttl_seconds)
        # Auth throttling over the same client; falls back to in-process counters, never open.
        app.state.rate_limiter = RateLimiter(
            redis,
            secret=settings.auth_signing_key,
            op_timeout=settings.cache_op_timeout_seconds,
            failure_backoff=settings.cache_failure_backoff_seconds,
        )
        await warm_up_security()
        if settings.auth_secret_key is None:
            logger.warning(
                "auth_secret_not_configured",
                extra={"effect": "random per-process key; sessions end when the API restarts"},
            )

        logger.info(
            "startup",
            extra={
                "environment": settings.environment.value,
                "database": engine.url.render_as_string(hide_password=True),
                "redis": redact_url(str(settings.redis_url)),
                "cache_enabled": settings.cache_enabled,
            },
        )
        yield
    logger.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    docs = settings.docs_enabled
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Compare prices, offers and ratings across Indian e-commerce stores.",
        openapi_url=f"{API_V1_PREFIX}/openapi.json" if docs else None,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    # Message senders hold no connections: built with the app, not in the lifespan.
    app.state.email_sender = build_email_sender(settings)
    app.state.sms_sender = build_sms_sender(settings)

    register_exception_handlers(app)

    # Last added = outermost. CORS wraps everything so even 500s get CORS
    # headers (otherwise the browser reports a CORS error instead of the 500).
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )

    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
