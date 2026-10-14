"""Redis client lifecycle. One pooled async client per process, created in the
app lifespan and exposed to routes through the ``get_redis`` dependency."""

from urllib.parse import urlsplit, urlunsplit

from fastapi import Request
from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        str(settings.redis_url),
        decode_responses=True,
        socket_connect_timeout=settings.health_check_timeout_seconds,
        socket_timeout=5,
        health_check_interval=30,
    )


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def redact_url(url: str) -> str:
    """Hide the password in a URL so it can be logged."""
    parts = urlsplit(url)
    if not parts.password:
        return url
    netloc = f"{parts.username or ''}:***@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))
