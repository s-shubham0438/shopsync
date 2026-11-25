"""Milestone 3.4 against a real Redis/Memurai.

Uses TEST_REDIS_URL, or REDIS_URL from the environment/.env with the database number switched to
15, so development keys in db 0 are never touched. Only this module's keys in db 15 are deleted.
Skipped (with a reason that never contains the URL) if Redis isn't reachable.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from redis.asyncio import Redis

from app.core.config import Environment, Settings
from app.core.redis import create_redis
from app.schemas.search import SearchRequest
from app.services.cache import NAMESPACE, JsonCache, SearchCache
from app.services.search import SearchService
from tests.services.test_search_unit import standard_setup

pytestmark = pytest.mark.integration

TEST_DB = 15


def _test_redis_url() -> str:
    explicit = os.environ.get("TEST_REDIS_URL")
    if explicit:
        return explicit
    dev = str(Settings().redis_url)
    return urlunsplit(urlsplit(dev)._replace(path=f"/{TEST_DB}"))


def _settings(url: str, **kw: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment=Environment.TEST,
        redis_url=url,
        **kw,  # type: ignore[arg-type]
    )


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    url = _test_redis_url()
    if urlsplit(url).path.strip("/") in ("", "0"):
        pytest.exit("TEST_REDIS_URL points at Redis db 0 (development); refusing to use it.")
    client = create_redis(_settings(url))
    try:
        await asyncio.wait_for(client.ping(), timeout=3)
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"Redis test database not reachable ({type(exc).__name__})")
    yield client
    async for key in client.scan_iter(match=f"{NAMESPACE}:*"):
        await client.delete(key)
    await client.aclose()


async def test_round_trip_with_real_ttl(redis: Redis) -> None:
    cache = JsonCache(redis)
    key = f"it:{uuid.uuid7()}"
    assert await cache.set(key, "value", 30) is True
    assert await cache.get(key) == "value"
    assert 0 < await redis.ttl(f"{NAMESPACE}:{key}") <= 30
    await cache.delete(key)
    assert await cache.get(key) is None


async def test_search_is_served_from_real_redis(redis: Redis) -> None:
    runner, catalog = standard_setup()
    scope = f"it-{uuid.uuid7()}"
    cache = SearchCache(JsonCache(redis), ttl=60, partial_ttl=10)
    service = SearchService(runner, catalog, cache=cache, cache_scope=scope)

    first = await service.search(SearchRequest(q="phone"))
    second = await service.search(SearchRequest(q="Phone", sort="price_desc"))  # type: ignore[arg-type]
    assert (first.cache, second.cache) == ("miss", "hit")
    assert len(runner.queries) == 1
    assert second.total == first.total

    # A second SearchCache (e.g. another worker process) sees the same entry.
    other = SearchService(
        *standard_setup(),
        cache=SearchCache(JsonCache(redis), ttl=60, partial_ttl=10),
        cache_scope=scope,
    )
    assert (await other.search(SearchRequest(q="phone"))).cache == "hit"

    await cache.invalidate()
    assert (await service.search(SearchRequest(q="phone"))).cache == "miss"


async def test_wrong_password_fails_open(redis: Redis) -> None:
    parts = urlsplit(_test_redis_url())
    netloc = f":wrong-{uuid.uuid4().hex}@{parts.hostname}:{parts.port or 6379}"
    bad = create_redis(_settings(urlunsplit(parts._replace(netloc=netloc))))
    try:
        runner, catalog = standard_setup()
        service = SearchService(
            runner,
            catalog,
            cache=SearchCache(JsonCache(bad, op_timeout=2), ttl=60, partial_ttl=10),
        )
        response = await service.search(SearchRequest(q="phone"))
        assert response.cache == "bypass"
        assert response.total == 3
    finally:
        await bad.aclose()


async def test_unreachable_redis_fails_open_quickly() -> None:
    # Port 1 on localhost: connection refused immediately, no Redis needed.
    bad = create_redis(_settings("redis://localhost:1/15", health_check_timeout_seconds=0.5))
    try:
        runner, catalog = standard_setup()
        service = SearchService(
            runner, catalog, cache=SearchCache(JsonCache(bad), ttl=60, partial_ttl=10)
        )
        async with asyncio.timeout(3):
            response = await service.search(SearchRequest(q="phone"))
        assert response.cache == "bypass"
        assert response.total == 3
    finally:
        await bad.aclose()
