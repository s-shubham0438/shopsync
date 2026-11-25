"""Runs store adapters concurrently with per-store timeouts and failure isolation.

* Every adapter runs in parallel, so a search costs roughly the slowest store, not the sum.
* Each store has its own deadline (STORE_ADAPTER_TIMEOUTS override > adapter class default >
  STORE_ADAPTER_TIMEOUT_SECONDS). A slow or failing store yields a TIMEOUT/ERROR result for that
  store only; the others are unaffected.
* Cancellation (e.g. the client disconnected) is never swallowed: it propagates and cancels
  every in-flight store call.
* Adapter output is never trusted. Each record is checked in the order the adapter returned it,
  and the first acceptable record wins:
    1. must be a `StoreListing`                     → else `not_a_listing`
    2. fields must have usable types                → else `invalid_record`
    3. must belong to this adapter's store          → else `platform_mismatch`
    4. URL must pass the store's HTTPS/host policy  → else the `url_*` reason
    5. external_id not already accepted             → else `duplicate_external_id`
  Each record is checked in isolation: anything unexpected while checking it makes that record
  `invalid_record`, never a failed search. Rejections are logged individually and counted in
  `AdapterResult.rejected`. Results are then capped at `query.limit` (first N kept).
* `fetch_product` fails with `external_id_mismatch` if the store returns a different product.
* Failure logs never contain raw exception text or tracebacks: messages go through
  `logsafe.redact` (URLs reduced to host, secrets masked) and stack traces are reduced to
  "file:line in function" frames.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import cast

from app.adapters.base import AdapterError, ExternalIdMismatchError, StoreAdapter, log_rejected
from app.adapters.logsafe import redact, safe_frames
from app.adapters.schemas import (
    AdapterResult,
    AdapterStatus,
    StoreListing,
    StoreSearchOutcome,
    StoreSearchQuery,
)
from app.adapters.urls import url_problem

logger = logging.getLogger("app.adapters")


class AdapterRunner:
    def __init__(
        self,
        adapters: Sequence[StoreAdapter],
        *,
        default_timeout: float,
        timeouts: Mapping[str, float] | None = None,
    ) -> None:
        slugs = [a.platform_slug for a in adapters]
        if len(slugs) != len(set(slugs)):
            raise ValueError(f"duplicate store adapters: {slugs}")
        if default_timeout <= 0:
            raise ValueError("default_timeout must be positive")
        self._adapters = {a.platform_slug: a for a in adapters}
        self._default_timeout = default_timeout
        self._timeouts = dict(timeouts or {})

    @property
    def platform_slugs(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def timeout_for(self, adapter: StoreAdapter) -> float:
        return (
            self._timeouts.get(adapter.platform_slug)
            or adapter.timeout_seconds
            or self._default_timeout
        )

    async def search_all(self, query: StoreSearchQuery) -> StoreSearchOutcome:
        """Search every store concurrently; always returns one result per store."""
        if not self._adapters:
            return StoreSearchOutcome(query=query, results=())
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(
                    self._run(adapter, lambda a=adapter: a.search(query), limit=query.limit),
                    name=f"store-search:{adapter.platform_slug}",
                )
                for adapter in self._adapters.values()
            ]
        return StoreSearchOutcome(query=query, results=tuple(t.result() for t in tasks))

    async def fetch_product(self, platform_slug: str, external_id: str) -> AdapterResult:
        """One store's listing by its own id, with the same timeout and validation rules."""
        adapter = self._adapters.get(platform_slug)
        if adapter is None:
            raise KeyError(f"no adapter for store {platform_slug!r}")

        async def call() -> list[StoreListing]:
            listing = await adapter.get_product(external_id)
            if listing is None:
                return []
            if getattr(listing, "external_id", None) != external_id:
                raise ExternalIdMismatchError("store returned a different product than requested")
            return [listing]

        return await self._run(adapter, call, limit=1)

    async def _run(
        self,
        adapter: StoreAdapter,
        call: Callable[[], Awaitable[list[StoreListing]]],
        *,
        limit: int,
    ) -> AdapterResult:
        slug = adapter.platform_slug
        timeout = self.timeout_for(adapter)
        started = time.perf_counter()

        def elapsed_ms() -> float:
            return round((time.perf_counter() - started) * 1000, 1)

        # Only Exception is caught: CancelledError (a BaseException) must propagate.
        try:
            async with asyncio.timeout(timeout):
                raw = await call()
        except TimeoutError:
            logger.warning("adapter_timeout", extra={"platform": slug, "timeout_s": timeout})
            return AdapterResult(
                slug, AdapterStatus.TIMEOUT, duration_ms=elapsed_ms(), error_code="timeout"
            )
        except AdapterError as exc:
            logger.warning(
                "adapter_failed",
                extra={"platform": slug, "error_type": type(exc).__name__, "error": redact(exc)},
            )
            return AdapterResult(
                slug,
                AdapterStatus.ERROR,
                duration_ms=elapsed_ms(),
                error_code=exc.code or type(exc).__name__,
            )
        except Exception as exc:
            # Unexpected bug in an adapter: isolate the store. No exc_info: tracebacks embed raw
            # exception text (URLs, keys); log redacted text plus code locations instead.
            logger.warning(
                "adapter_crashed",
                extra={
                    "platform": slug,
                    "error_type": type(exc).__name__,
                    "error": redact(exc),
                    "frames": safe_frames(exc),
                },
            )
            return AdapterResult(
                slug, AdapterStatus.ERROR, duration_ms=elapsed_ms(), error_code=type(exc).__name__
            )

        try:
            accepted, rejected = self._validate(adapter, raw)
        except Exception as exc:  # defensive: a validation bug must only fail this store
            logger.warning(
                "adapter_validation_crashed",
                extra={
                    "platform": slug,
                    "error_type": type(exc).__name__,
                    "frames": safe_frames(exc),
                },
            )
            return AdapterResult(
                slug, AdapterStatus.ERROR, duration_ms=elapsed_ms(), error_code="invalid_response"
            )
        return AdapterResult(
            slug,
            AdapterStatus.OK,
            listings=tuple(accepted[:limit]),
            duration_ms=elapsed_ms(),
            rejected=rejected,
        )

    @staticmethod
    def _validate(adapter: StoreAdapter, raw: object) -> tuple[list[StoreListing], int]:
        slug = adapter.platform_slug
        if not isinstance(raw, list | tuple):
            log_rejected(slug, "not_a_list")
            return [], 1

        accepted: list[StoreListing] = []
        seen: set[str] = set()
        rejected = 0
        for item in raw:
            try:
                reason = AdapterRunner._record_problem(adapter, item, seen)
            except Exception:  # anything odd about one record rejects that record only
                reason = "invalid_record"
            if reason is None:
                listing = cast(StoreListing, item)  # _record_problem verified the type
                seen.add(listing.external_id)
                accepted.append(listing)
                continue
            rejected += 1
            log_rejected(slug, reason, external_id=getattr(item, "external_id", None))
        return accepted, rejected

    @staticmethod
    def _record_problem(adapter: StoreAdapter, item: object, seen: set[str]) -> str | None:
        """Why this record must be rejected, or None if it is acceptable."""
        if not isinstance(item, StoreListing):
            return "not_a_listing"
        # Records built without validation (model_construct / model_copy) can hold anything.
        if not all(isinstance(v, str) for v in (item.platform_slug, item.external_id, item.url)):
            return "invalid_record"
        if item.platform_slug != adapter.platform_slug:
            return "platform_mismatch"
        if problem := url_problem(item.url, adapter.allowed_hosts):
            return problem
        if item.external_id in seen:
            return "duplicate_external_id"
        return None
