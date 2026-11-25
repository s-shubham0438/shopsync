"""Controllable adapters for runner/registry tests."""

import asyncio
from typing import Any

from app.adapters.base import StoreAdapter
from app.adapters.schemas import StoreListing, StoreSearchQuery
from app.core.stores import STORES_BY_SLUG


def make_listing(slug: str = "amazon", external_id: str = "X1", **overrides: Any) -> StoreListing:
    store = STORES_BY_SLUG[slug]
    data: dict[str, Any] = {
        "platform_slug": slug,
        "external_id": external_id,
        "title": f"Product {external_id}",
        "url": f"{store.base_url}/p/{external_id}",
        "price": 99_900,
    }
    data.update(overrides)
    return StoreListing(**data)


class FakeAdapter(StoreAdapter):
    """Returns `results` after `delay` seconds, or raises `error`. Records lifecycle events."""

    mode = "mock"

    def __init__(
        self,
        slug: str,
        *,
        results: list[Any] | None = None,
        delay: float = 0.0,
        error: BaseException | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(STORES_BY_SLUG[slug])
        self.results = results if results is not None else [make_listing(slug, f"{slug}-1")]
        self.delay = delay
        self.error = error
        self.calls = 0
        self.cancelled = False
        self.closed = False
        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds  # type: ignore[misc]  # per-instance override

    async def _respond(self) -> list[Any]:
        self.calls += 1
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.error is not None:
            raise self.error
        return self.results

    async def search(self, query: StoreSearchQuery) -> list[StoreListing]:
        return await self._respond()

    async def get_product(self, external_id: str) -> StoreListing | None:
        results = await self._respond()
        return next((r for r in results if getattr(r, "external_id", None) == external_id), None)

    async def aclose(self) -> None:
        self.closed = True
