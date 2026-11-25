"""Milestone 3.4: fail-open Redis cache and its use by SearchService (in-memory fake Redis)."""

import asyncio
import logging
import uuid
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.adapters.schemas import AdapterResult, AdapterStatus, StoreSearchOutcome, StoreSearchQuery
from app.core.config import Environment, Settings
from app.core.errors import ServiceUnavailableError
from app.schemas.search import SearchRequest, SearchSnapshot, SearchSort
from app.services.cache import (
    NAMESPACE,
    SEARCH_GENERATION_KEY,
    JsonCache,
    ProductCache,
    SearchCache,
    normalise_query,
    search_cache_scope,
)
from app.services.search import InvalidSearchFilterError, SearchService
from tests.services.test_search_unit import FakeCatalog, FakeRunner, standard_setup

SECRET = "hunter2-redis-password"


class FakeRedis:
    """Async in-memory stand-in for redis.asyncio.Redis(decode_responses=True)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.calls: list[str] = []
        self.fail = False
        self.delay = 0.0

    async def _op(self, name: str) -> None:
        self.calls.append(name)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError(f"Error connecting to redis://:{SECRET}@localhost:6379")

    async def get(self, name: str) -> str | None:
        await self._op("get")
        return self.data.get(name)

    async def set(self, name: str, value: str, *, ex: int) -> bool:
        await self._op("set")
        self.data[name] = value
        self.ttls[name] = ex
        return True

    async def delete(self, *names: str) -> int:
        await self._op("delete")
        return sum(self.data.pop(n, None) is not None for n in names)

    async def incr(self, name: str) -> int:
        await self._op("incr")
        value = int(self.data.get(name, "0")) + 1
        self.data[name] = str(value)
        return value


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def store(redis: FakeRedis | None = None, **kw: Any) -> JsonCache:
    kw.setdefault("op_timeout", 0.5)
    return JsonCache(redis if redis is not None else FakeRedis(), **kw)


def cached_service(
    setup: tuple[FakeRunner, FakeCatalog] | None = None,
    redis: FakeRedis | None = None,
    *,
    ttl: int = 1800,
    partial_ttl: int = 60,
    scope: str = "mock:amazon,croma,flipkart",
    **store_kw: Any,
) -> tuple[SearchService, FakeRunner, FakeCatalog, FakeRedis]:
    runner, catalog = setup or standard_setup()
    redis = redis or FakeRedis()
    cache = SearchCache(store(redis, **store_kw), ttl=ttl, partial_ttl=partial_ttl)
    return SearchService(runner, catalog, cache=cache, cache_scope=scope), runner, catalog, redis


def search_keys(redis: FakeRedis) -> list[str]:
    return [k for k in redis.data if k.startswith(f"{NAMESPACE}:search:g")]


# --------------------------------------------------------------------------- #
# JsonCache
# --------------------------------------------------------------------------- #
async def test_round_trip_uses_namespace_and_ttl() -> None:
    redis = FakeRedis()
    cache = store(redis)
    assert await cache.set("k", "value", 30) is True
    assert redis.data == {f"{NAMESPACE}:k": "value"}
    assert redis.ttls[f"{NAMESPACE}:k"] == 30
    assert await cache.get("k") == "value"
    assert await cache.incr("n") == 1
    await cache.delete("k")
    assert await cache.get("k") is None


async def test_zero_ttl_and_oversized_entries_are_not_written() -> None:
    redis = FakeRedis()
    cache = store(redis, max_entry_bytes=1024)
    assert await cache.set("k", "v", 0) is False
    assert await cache.set("big", "é" * 600, 30) is False  # 1200 bytes > 1024, counted in bytes
    assert redis.calls == []


async def test_disabled_or_missing_backend_never_calls_redis() -> None:
    redis = FakeRedis()
    disabled = store(redis, enabled=False)
    assert not disabled.available
    assert await disabled.set("k", "v", 30) is False
    assert await disabled.get("k") is None
    assert redis.calls == []
    assert not JsonCache(None).available


async def test_failure_is_swallowed_backs_off_and_logs_once_without_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis, clock = FakeRedis(), Clock()
    cache = store(redis, failure_backoff=30, clock=clock)
    redis.fail = True
    caplog.set_level(logging.INFO, logger="app.services.cache")

    assert await cache.get("search:x") is None
    assert not cache.available
    # Within the back-off window Redis is not called at all.
    assert await cache.get("search:x") is None
    assert await cache.set("search:x", "v", 30) is False
    assert redis.calls == ["get"]

    warnings = [r for r in caplog.records if r.message == "cache_unavailable"]
    assert len(warnings) == 1
    assert warnings[0].error_type == "ConnectionError"  # type: ignore[attr-defined]
    assert warnings[0].key_kind == "search"  # type: ignore[attr-defined]
    assert SECRET not in caplog.text

    # After the window, one retry; success logs recovery.
    clock.now += 31
    redis.fail = False
    assert cache.available
    assert await cache.set("k", "v", 30) is True
    assert any(r.message == "cache_recovered" for r in caplog.records)


async def test_slow_redis_times_out_as_a_miss() -> None:
    redis = FakeRedis()
    redis.delay = 0.2
    cache = store(redis, op_timeout=0.01)
    assert await cache.get("k") is None
    assert not cache.available


async def test_cancellation_is_not_swallowed() -> None:
    class Cancelling(FakeRedis):
        async def get(self, name: str) -> str | None:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await store(Cancelling()).get("k")


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #
def test_query_normalisation() -> None:
    assert normalise_query("  iPhone   15\tPro ") == "iphone 15 pro"


def test_search_key_hides_query_text_and_ignores_sort_page_price() -> None:
    base = SearchRequest(q="Secret Gift")
    key = SearchCache.key(3, base, "mock:amazon")
    assert key.startswith("search:g3:")
    assert "secret" not in key.lower()
    same = SearchRequest(
        q=" secret   GIFT ", sort=SearchSort.PRICE_ASC, page=2, page_size=5, min_price=1
    )
    assert SearchCache.key(3, same, "mock:amazon") == key
    assert SearchCache.key(4, base, "mock:amazon") != key
    assert SearchCache.key(3, base, "mock:flipkart") != key
    assert SearchCache.key(3, SearchRequest(q="secret gift", category="mobiles"), "x") != (
        SearchCache.key(3, SearchRequest(q="secret gift"), "x")
    )


def test_scope_depends_on_mode_and_store_set_not_order() -> None:
    def s(stores: list[str]) -> Settings:
        return Settings(_env_file=None, environment=Environment.TEST, enabled_stores=stores)  # type: ignore[call-arg]

    assert search_cache_scope(s(["flipkart", "amazon"])) == search_cache_scope(
        s(["amazon", "flipkart"])
    )
    assert search_cache_scope(s(["amazon"])) != search_cache_scope(s(["amazon", "flipkart"]))


# --------------------------------------------------------------------------- #
# SearchService + SearchCache
# --------------------------------------------------------------------------- #
async def test_second_search_is_a_hit_with_no_store_or_db_calls() -> None:
    service, runner, catalog, redis = cached_service()
    first = await service.search(SearchRequest(q="phone"))
    calls_after_first = list(catalog.calls)
    second = await service.search(SearchRequest(q="phone"))

    assert first.cache == "miss"
    assert second.cache == "hit"
    assert len(runner.queries) == 1
    assert catalog.calls == calls_after_first
    assert second.model_dump(exclude={"cache"}) == first.model_dump(exclude={"cache"})
    assert redis.ttls[search_keys(redis)[0]] == 1800


@pytest.mark.parametrize(
    "variant",
    [
        {"sort": SearchSort.PRICE_DESC},
        {"sort": SearchSort.RATING, "page": 2, "page_size": 1},
        {"min_price": 950_00, "max_price": 2_500_00},
        {"max_price": 100_00},  # filters everything out
    ],
)
async def test_hit_matches_uncached_result_for_any_sort_page_or_price(
    variant: dict[str, Any],
) -> None:
    service, runner, _, _ = cached_service()
    await service.search(SearchRequest(q="phone"))  # warm with defaults

    request = SearchRequest(q="  PHONE ", **variant)
    cached = await service.search(request)
    uncached = await SearchService(*standard_setup()).search(request)

    assert cached.cache == "hit"
    assert len(runner.queries) == 1
    assert cached.model_dump(exclude={"cache"}) == uncached.model_dump(exclude={"cache"})
    assert uncached.cache == "bypass"


async def test_category_is_part_of_the_key() -> None:
    service, runner, _, _ = cached_service()
    await service.search(SearchRequest(q="phone"))
    response = await service.search(SearchRequest(q="phone", category="footwear"))
    assert response.cache == "miss"
    assert len(runner.queries) == 2
    assert [i.canonical_title for i in response.items] == ["Shoe C"]


async def test_partial_results_get_the_short_ttl() -> None:
    runner, catalog = standard_setup()
    runner.results.append(AdapterResult("myntra", AdapterStatus.TIMEOUT, error_code="timeout"))
    service, _, _, redis = cached_service((runner, catalog))
    response = await service.search(SearchRequest(q="phone"))
    assert response.partial
    assert redis.ttls[search_keys(redis)[0]] == 60


async def test_zero_partial_ttl_means_partial_results_are_not_cached() -> None:
    runner, catalog = standard_setup()
    runner.results.append(AdapterResult("myntra", AdapterStatus.ERROR, error_code="x"))
    service, _, _, redis = cached_service((runner, catalog), partial_ttl=0)
    await service.search(SearchRequest(q="phone"))
    second = await service.search(SearchRequest(q="phone"))
    assert search_keys(redis) == []
    assert second.cache == "miss"
    assert len(runner.queries) == 2


async def test_all_stores_failing_is_never_cached() -> None:
    runner = FakeRunner([AdapterResult("amazon", AdapterStatus.ERROR, error_code="x")])
    service, _, _, redis = cached_service((runner, standard_setup()[1]))
    for _ in range(2):
        with pytest.raises(ServiceUnavailableError):
            await service.search(SearchRequest(q="phone"))
    assert len(runner.queries) == 2
    assert search_keys(redis) == []


async def test_unknown_category_is_never_cached() -> None:
    service, runner, _, redis = cached_service()
    for _ in range(2):
        with pytest.raises(InvalidSearchFilterError):
            await service.search(SearchRequest(q="phone", category="nope"))
    assert runner.queries == []
    assert search_keys(redis) == []


async def test_corrupted_entry_is_a_miss_and_is_replaced(caplog: pytest.LogCaptureFixture) -> None:
    service, runner, _, redis = cached_service()
    await service.search(SearchRequest(q="phone"))
    (key,) = search_keys(redis)
    redis.data[key] = '{"items": "not a list"'

    response = await service.search(SearchRequest(q="phone"))
    assert response.cache == "miss"
    assert len(runner.queries) == 2
    assert "cache_entry_invalid" in caplog.text
    SearchSnapshot.model_validate_json(redis.data[key])  # rewritten with a valid entry


async def test_invalidate_starts_a_new_generation() -> None:
    service, runner, _, redis = cached_service()
    cache = service._cache
    assert cache is not None
    await service.search(SearchRequest(q="phone"))
    await cache.invalidate()
    assert redis.data[f"{NAMESPACE}:{SEARCH_GENERATION_KEY}"] == "1"
    response = await service.search(SearchRequest(q="phone"))
    assert response.cache == "miss"
    assert len(runner.queries) == 2
    assert any(k.startswith(f"{NAMESPACE}:search:g1:") for k in redis.data)


async def test_redis_down_search_still_works_as_bypass() -> None:
    redis = FakeRedis()
    redis.fail = True
    service, runner, _, _ = cached_service(redis=redis)
    first = await service.search(SearchRequest(q="phone"))
    second = await service.search(SearchRequest(q="phone"))
    assert first.cache == second.cache == "bypass"
    assert first.total == 3
    assert len(runner.queries) == 2
    assert redis.calls == ["get"]  # one failed call, then back-off


async def test_redis_failing_mid_request_reports_bypass() -> None:
    class FailsAfterGeneration(FakeRedis):
        async def get(self, name: str) -> str | None:
            if name.endswith(SEARCH_GENERATION_KEY):
                return None
            raise ConnectionError("down")

    service, _, _, _ = cached_service(redis=FailsAfterGeneration())
    response = await service.search(SearchRequest(q="phone"))
    assert response.cache == "bypass"
    assert response.total == 3


async def test_cache_disabled_is_bypass() -> None:
    service, _, _, redis = cached_service(enabled=False)
    response = await service.search(SearchRequest(q="phone"))
    assert response.cache == "bypass"
    assert redis.calls == []


# --------------------------------------------------------------------------- #
# Single-flight
# --------------------------------------------------------------------------- #
class GatedRunner(FakeRunner):
    def __init__(self, inner: FakeRunner) -> None:
        super().__init__(inner.results)
        self.gate = asyncio.Event()
        self.started = asyncio.Event()

    async def search_all(self, query: StoreSearchQuery) -> StoreSearchOutcome:
        self.queries.append(query)
        self.started.set()
        await self.gate.wait()
        return StoreSearchOutcome(query=query, results=tuple(self.results))


async def test_concurrent_identical_searches_query_stores_once() -> None:
    runner, catalog = standard_setup()
    gated = GatedRunner(runner)
    service, _, _, _ = cached_service((gated, catalog))

    tasks = [asyncio.create_task(service.search(SearchRequest(q="phone"))) for _ in range(5)]
    await gated.started.wait()
    await asyncio.sleep(0.01)  # let the other tasks reach the single-flight wait
    gated.gate.set()
    responses = await asyncio.gather(*tasks)

    assert len(gated.queries) == 1
    assert sorted(r.cache for r in responses) == ["hit"] * 4 + ["miss"]
    assert len({r.total for r in responses}) == 1


async def test_cancelled_leader_hands_over_to_a_waiter() -> None:
    runner, catalog = standard_setup()
    gated = GatedRunner(runner)
    service, _, _, _ = cached_service((gated, catalog))

    leader = asyncio.create_task(service.search(SearchRequest(q="phone")))
    await gated.started.wait()
    waiter = asyncio.create_task(service.search(SearchRequest(q="phone")))
    await asyncio.sleep(0.01)
    leader.cancel()
    await asyncio.sleep(0.01)
    gated.gate.set()

    with pytest.raises(asyncio.CancelledError):
        await leader
    response = await waiter
    assert response.cache == "miss"
    assert response.total == 3
    assert len(gated.queries) == 2


async def test_leader_error_is_shared_and_not_cached() -> None:
    gated = GatedRunner(FakeRunner([AdapterResult("amazon", AdapterStatus.ERROR, error_code="x")]))
    service, _, _, redis = cached_service((gated, standard_setup()[1]))

    tasks = [asyncio.create_task(service.search(SearchRequest(q="phone"))) for _ in range(3)]
    await gated.started.wait()
    gated.gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert all(isinstance(r, ServiceUnavailableError) for r in results)
    assert len(gated.queries) == 1
    assert search_keys(redis) == []


# --------------------------------------------------------------------------- #
# ProductCache
# --------------------------------------------------------------------------- #
class Detail(BaseModel):
    id: uuid.UUID
    title: str


async def test_product_cache_round_trip_and_invalidate() -> None:
    redis = FakeRedis()
    cache = ProductCache(store(redis), ttl=120)
    detail = Detail(id=uuid.uuid7(), title="Phone")

    assert await cache.get(detail.id, Detail) is None
    assert await cache.set(detail.id, detail) is True
    assert redis.ttls[f"{NAMESPACE}:product:{detail.id}"] == 120
    assert await cache.get(detail.id, Detail) == detail
    await cache.invalidate(detail.id)
    assert await cache.get(detail.id, Detail) is None


async def test_product_cache_drops_incompatible_entries() -> None:
    redis = FakeRedis()
    cache = ProductCache(store(redis), ttl=120)
    product_id = uuid.uuid7()
    redis.data[f"{NAMESPACE}:product:{product_id}"] = '{"id": "x"}'
    assert await cache.get(product_id, Detail) is None
    assert f"{NAMESPACE}:product:{product_id}" not in redis.data


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def make_settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, environment=Environment.TEST, **kw)  # type: ignore[call-arg]


def test_cache_setting_defaults() -> None:
    s = make_settings()
    assert s.cache_enabled is True
    assert s.cache_ttl_seconds == 1800
    assert s.cache_partial_ttl_seconds == 60
    assert s.cache_op_timeout_seconds == 0.25
    assert s.cache_failure_backoff_seconds == 30
    assert s.cache_max_entry_bytes == 1_000_000
    assert s.redis_socket_timeout_seconds == 2.0


@pytest.mark.parametrize(
    "field",
    [
        "cache_ttl_seconds",
        "cache_partial_ttl_seconds",
        "cache_op_timeout_seconds",
        "cache_failure_backoff_seconds",
        "cache_max_entry_bytes",
        "redis_socket_timeout_seconds",
    ],
)
def test_numeric_cache_settings_reject_booleans(field: str) -> None:
    with pytest.raises(ValidationError, match="must be a number"):
        make_settings(**{field: True})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cache_ttl_seconds", -1),
        ("cache_partial_ttl_seconds", -1),
        ("cache_op_timeout_seconds", 0),
        ("cache_op_timeout_seconds", 6),
        ("cache_failure_backoff_seconds", 3601),
        ("cache_max_entry_bytes", 100),
        ("redis_socket_timeout_seconds", 0),
        ("redis_socket_timeout_seconds", 31),
    ],
)
def test_cache_settings_out_of_range_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_cache_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_ENABLED", "false")
    monkeypatch.setenv("CACHE_PARTIAL_TTL_SECONDS", "15")
    s = make_settings()
    assert s.cache_enabled is False
    assert s.cache_partial_ttl_seconds == 15
    assert not JsonCache.from_settings(FakeRedis(), s).available
