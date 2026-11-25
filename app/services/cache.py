"""Redis caching for search results and (from Milestone 3.5) product details.

Design rules:

- **Fail-open.** Redis is an optimisation, never a dependency of search. Every cache operation
  has a short deadline (`CACHE_OP_TIMEOUT_SECONDS`); any Redis error or timeout is treated as
  a miss. After a failure the cache is skipped for `CACHE_FAILURE_BACKOFF_SECONDS`, so a dead
  Redis costs one slow call per window instead of one per request, and is logged once per window.
- **JSON only.** Entries are pydantic models serialised with `model_dump_json`, never pickle.
  An entry that no longer parses (corrupted, or written by an older format) counts as a miss
  and is deleted.
- **Namespaced, versioned keys.** Every key starts with `shopsync:v1:`. Bumping
  `CACHE_FORMAT_VERSION` orphans old entries; Redis' LRU policy evicts them.
- **No secrets or query text in keys.** Search keys are SHA-256 digests.
- **Single-flight.** Concurrent identical searches in one process share one store query.
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.schemas.search import SearchRequest, SearchSnapshot

logger = logging.getLogger(__name__)

CACHE_FORMAT_VERSION = "v1"
NAMESPACE = f"shopsync:{CACHE_FORMAT_VERSION}"
SEARCH_GENERATION_KEY = "search:gen"


class CacheStatus(StrEnum):
    HIT = "hit"  # served without querying the stores for this request
    MISS = "miss"  # stores queried; the result was offered to the cache
    BYPASS = "bypass"  # cache disabled or Redis unavailable


class CacheBackend(Protocol):
    """The subset of `redis.asyncio.Redis` (with `decode_responses=True`) used here."""

    async def get(self, name: str) -> Any: ...

    async def set(self, name: str, value: str, *, ex: int) -> Any: ...

    async def delete(self, *names: str) -> Any: ...

    async def incr(self, name: str) -> Any: ...


class JsonCache:
    """Fail-open string cache over Redis. Never raises for Redis problems."""

    def __init__(
        self,
        backend: CacheBackend | None,
        *,
        enabled: bool = True,
        op_timeout: float = 0.25,
        failure_backoff: float = 30.0,
        max_entry_bytes: int = 1_000_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._backend = backend
        self._enabled = enabled and backend is not None
        self._op_timeout = op_timeout
        self._failure_backoff = failure_backoff
        self._max_entry_bytes = max_entry_bytes
        self._clock = clock
        self._skip_until = 0.0
        self._degraded = False

    @classmethod
    def from_settings(cls, backend: CacheBackend | None, settings: Settings) -> JsonCache:
        return cls(
            backend,
            enabled=settings.cache_enabled,
            op_timeout=settings.cache_op_timeout_seconds,
            failure_backoff=settings.cache_failure_backoff_seconds,
            max_entry_bytes=settings.cache_max_entry_bytes,
        )

    @property
    def available(self) -> bool:
        """False when disabled, or while backing off after a Redis failure."""
        return self._enabled and self._clock() >= self._skip_until

    async def get(self, key: str) -> str | None:
        value = await self._call("get", key, lambda b: b.get(_full(key)))
        return value if isinstance(value, str) else None

    async def set(self, key: str, value: str, ttl: int) -> bool:
        if ttl <= 0:
            return False
        size = len(value.encode())
        if size > self._max_entry_bytes:
            logger.info("cache_entry_too_large", extra={"bytes": size})
            return False
        result = await self._call("set", key, lambda b: b.set(_full(key), value, ex=ttl))
        return bool(result)

    async def delete(self, key: str) -> None:
        await self._call("delete", key, lambda b: b.delete(_full(key)))

    async def incr(self, key: str) -> int | None:
        value = await self._call("incr", key, lambda b: b.incr(_full(key)))
        return value if isinstance(value, int) else None

    async def _call(
        self, op: str, key: str, action: Callable[[CacheBackend], Awaitable[Any]]
    ) -> Any:
        if not self.available or self._backend is None:
            return None
        try:
            async with asyncio.timeout(self._op_timeout):
                result = await action(self._backend)
        except Exception as exc:  # fail-open by design; CancelledError is not an Exception
            self._skip_until = self._clock() + self._failure_backoff
            if not self._degraded:
                self._degraded = True
                # Only the exception type: Redis error messages can include connection details.
                logger.warning(
                    "cache_unavailable",
                    extra={
                        "operation": op,
                        "key_kind": key.split(":", 1)[0],
                        "error_type": type(exc).__name__,
                        "backoff_seconds": self._failure_backoff,
                    },
                )
            return None
        if self._degraded:
            self._degraded = False
            logger.info("cache_recovered")
        return result


def _full(key: str) -> str:
    return f"{NAMESPACE}:{key}"


def normalise_query(text: str) -> str:
    """Case and whitespace don't change a search, so they don't change its cache key."""
    return " ".join(text.split()).casefold()


def search_cache_scope(settings: Settings) -> str:
    """Results depend on which stores are queried and how; different configs never share."""
    return f"{settings.store_adapter_mode}:{','.join(sorted(settings.enabled_stores))}"


class SearchCache:
    """Caches search snapshots (everything before price filtering, sorting and paging).

    The key covers the normalised query text, category and store scope only, so every sort
    order, page and price range of one search is served from a single entry.
    """

    def __init__(self, store: JsonCache, *, ttl: int, partial_ttl: int) -> None:
        self._store = store
        self._ttl = ttl
        self._partial_ttl = partial_ttl
        self._inflight: dict[str, asyncio.Future[SearchSnapshot]] = {}

    @classmethod
    def from_settings(cls, store: JsonCache, settings: Settings) -> SearchCache:
        return cls(
            store, ttl=settings.cache_ttl_seconds, partial_ttl=settings.cache_partial_ttl_seconds
        )

    @staticmethod
    def key(generation: int, request: SearchRequest, scope: str) -> str:
        material = json.dumps([normalise_query(request.q or ""), request.category, scope])
        digest = hashlib.sha256(material.encode()).hexdigest()
        return f"search:g{generation}:{digest}"

    async def get_or_compute(
        self,
        request: SearchRequest,
        scope: str,
        compute: Callable[[], Awaitable[SearchSnapshot]],
    ) -> tuple[SearchSnapshot, CacheStatus]:
        """Return a cached snapshot, or compute (once per process per key) and cache it.

        Errors from `compute` (e.g. 503 when every store failed, 422 unknown category) are
        never cached.
        """
        if not self._store.available:
            return await compute(), CacheStatus.BYPASS
        raw_generation = await self._store.get(SEARCH_GENERATION_KEY)
        if not self._store.available:  # the read just failed
            return await compute(), CacheStatus.BYPASS
        generation = int(raw_generation) if raw_generation and raw_generation.isdigit() else 0
        key = self.key(generation, request, scope)

        raw = await self._store.get(key)
        if raw is not None and (cached := await self._decode(key, raw)) is not None:
            return cached, CacheStatus.HIT

        # Single-flight: wait for an identical search already running in this process.
        while (pending := self._inflight.get(key)) is not None:
            # asyncio.wait never cancels `pending`; it raises only if THIS task is cancelled.
            await asyncio.wait({pending})
            if not pending.cancelled():  # leader finished (result or error): share it
                return pending.result(), CacheStatus.HIT
            # The leader's client went away; take over.

        future: asyncio.Future[SearchSnapshot] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            snapshot = await compute()
        except asyncio.CancelledError:
            future.cancel()
            raise
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved: no "never retrieved" warning if nobody waited
            raise
        else:
            future.set_result(snapshot)
        finally:
            if self._inflight.get(key) is future:
                del self._inflight[key]

        if not self._store.available:  # Redis failed mid-request: nothing was cached
            return snapshot, CacheStatus.BYPASS
        ttl = self._partial_ttl if snapshot.partial else self._ttl
        await self._store.set(key, snapshot.model_dump_json(), ttl)
        return snapshot, CacheStatus.MISS

    async def invalidate(self) -> None:
        """Make every cached search stale at once (new generation; old keys expire by TTL)."""
        await self._store.incr(SEARCH_GENERATION_KEY)

    async def _decode(self, key: str, raw: str) -> SearchSnapshot | None:
        try:
            return SearchSnapshot.model_validate_json(raw)
        except ValidationError:
            logger.warning("cache_entry_invalid", extra={"key_kind": "search"})
            await self._store.delete(key)
            return None


class ProductCache:
    """Product detail cache (`product:{id}`). Wired to GET /products/{id} in Milestone 3.5."""

    def __init__(self, store: JsonCache, *, ttl: int) -> None:
        self._store = store
        self._ttl = ttl

    @staticmethod
    def key(product_id: uuid.UUID) -> str:
        return f"product:{product_id}"

    async def get[M: BaseModel](self, product_id: uuid.UUID, model: type[M]) -> M | None:
        key = self.key(product_id)
        raw = await self._store.get(key)
        if raw is None:
            return None
        try:
            return model.model_validate_json(raw)
        except ValidationError:
            logger.warning("cache_entry_invalid", extra={"key_kind": "product"})
            await self._store.delete(key)
            return None

    async def set(self, product_id: uuid.UUID, value: BaseModel) -> bool:
        return await self._store.set(self.key(product_id), value.model_dump_json(), self._ttl)

    async def invalidate(self, product_id: uuid.UUID) -> None:
        await self._store.delete(self.key(product_id))
