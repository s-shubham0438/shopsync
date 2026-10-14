import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import API_V1_PREFIX, Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.redis import create_redis, redact_url
from app.db.session import create_engine, create_sessionmaker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # Both clients connect lazily, so the API starts even if Postgres/Redis are
    # down; /health reports their status.
    engine = create_engine(settings)
    redis = create_redis(settings)
    app.state.db_engine = engine
    app.state.db_sessionmaker = create_sessionmaker(engine)
    app.state.redis = redis
    logger.info(
        "startup",
        extra={
            "environment": settings.environment.value,
            "database": engine.url.render_as_string(hide_password=True),
            "redis": redact_url(str(settings.redis_url)),
        },
    )
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()
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
