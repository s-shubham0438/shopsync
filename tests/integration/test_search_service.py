"""SearchService end to end: six real mock adapters + PostgreSQL (shopsync_test, rolled back)."""

import random
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.adapters.mock import MockStoreAdapter
from app.adapters.runner import AdapterRunner
from app.core.errors import ServiceUnavailableError
from app.core.stores import STORES, STORES_BY_SLUG
from app.db.seed import run_seed
from app.db.seed_data import PRODUCTS, ProductSeed
from app.models import Product
from app.repositories.catalog import CatalogRepository
from app.schemas.search import SearchRequest, SearchSort
from app.services.search import InvalidSearchFilterError, SearchService


def mocks(**overrides: dict[str, Any]) -> list[MockStoreAdapter]:
    return [
        MockStoreAdapter(
            store,
            latency_ms=0,
            rng=random.Random(store.slug),  # noqa: S311
            **overrides.get(store.slug, {}),
        )
        for store in STORES
    ]


@pytest.fixture
async def service(session: AsyncSession) -> SearchService:
    await run_seed(session)
    return SearchService(AdapterRunner(mocks(), default_timeout=2), CatalogRepository(session))


@contextmanager
def count_queries(connection: AsyncConnection) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(args[2])

    sync = connection.sync_connection
    assert sync is not None
    event.listen(sync, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(sync, "before_cursor_execute", record)


async def test_iphone_aggregates_four_stores_onto_the_seeded_product(
    service: SearchService, session: AsyncSession
) -> None:
    response = await service.search(SearchRequest(q="iphone 15"))
    assert response.total == 1 and not response.partial and response.unresolved_count == 0
    item = response.items[0]
    seeded = await session.scalar(
        select(Product).where(Product.canonical_title.like("Apple iPhone 15%"))
    )
    assert seeded is not None and item.id == seeded.id
    assert item.store_count == 4
    assert item.best_price == 59_999_00 and item.best_platform.slug == "flipkart"
    assert item.highest_price == 62_990_00
    assert item.category is not None and item.category.slug == "mobiles"
    assert {s.platform for s in response.stores} == {s.slug for s in STORES}


async def test_parent_category_filter(service: SearchService) -> None:
    response = await service.search(SearchRequest(q="men", category="fashion", page_size=50))
    assert response.total > 0
    assert {item.category.slug for item in response.items if item.category} <= {
        "clothing",
        "footwear",
    }


async def test_unknown_category_rejected(service: SearchService) -> None:
    with pytest.raises(InvalidSearchFilterError):
        await service.search(SearchRequest(q="phone", category="spaceships"))


async def test_price_filter_and_sort(service: SearchService) -> None:
    response = await service.search(
        SearchRequest(
            q="apple", min_price=20_000_00, max_price=60_000_00, sort=SearchSort.PRICE_ASC
        )
    )
    prices = [item.best_price for item in response.items]
    assert prices and prices == sorted(prices)
    assert all(20_000_00 <= p <= 60_000_00 for p in prices)


async def test_pages_cover_every_result_exactly_once(service: SearchService) -> None:
    full = await service.search(SearchRequest(q="men", page_size=50, sort=SearchSort.RATING))
    collected = []
    for page in range(1, full.pages + 5):
        response = await service.search(
            SearchRequest(q="men", page=page, page_size=2, sort=SearchSort.RATING)
        )
        collected.extend(item.id for item in response.items)
    assert collected == [item.id for item in full.items]
    assert len(set(collected)) == len(collected) == full.total


async def test_partial_failure_keeps_other_stores(session: AsyncSession) -> None:
    await run_seed(session)
    runner = AdapterRunner(mocks(croma={"failure_rate": 1.0}), default_timeout=2)
    response = await SearchService(runner, CatalogRepository(session)).search(
        SearchRequest(q="iphone 15")
    )
    assert response.partial is True
    assert next(s for s in response.stores if s.platform == "croma").status == "error"
    assert response.items[0].store_count == 3
    assert response.items[0].best_platform.slug == "flipkart"


async def test_every_store_failing_is_503(session: AsyncSession) -> None:
    await run_seed(session)
    failing = {store.slug: {"failure_rate": 1.0} for store in STORES}
    runner = AdapterRunner(mocks(**failing), default_timeout=2)
    with pytest.raises(ServiceUnavailableError):
        await SearchService(runner, CatalogRepository(session)).search(SearchRequest(q="iphone"))


async def test_listing_not_in_database_is_counted_not_shown(session: AsyncSession) -> None:
    await run_seed(session)
    unseeded = ProductSeed(
        "not-in-db-gadget", "Zentrix Gadget Pro", "Zentrix", "audio", 5000, 4.0, 10,
        {"amazon": 4000}, {"Type": "Gadget"},
    )  # fmt: skip
    amazon = MockStoreAdapter(
        STORES_BY_SLUG["amazon"], latency_ms=0, catalogue=[*PRODUCTS, unseeded]
    )
    response = await SearchService(
        AdapterRunner([amazon], default_timeout=2), CatalogRepository(session)
    ).search(SearchRequest(q="zentrix"))
    assert response.total == 0 and response.unresolved_count == 1


async def test_database_access_is_a_fixed_number_of_queries(
    service: SearchService, connection: AsyncConnection
) -> None:
    with count_queries(connection) as statements:
        broad = await service.search(SearchRequest(q="men", category="fashion", page_size=50))
    assert broad.total > 3
    # Ignore the test fixture's own SAVEPOINT handling; count real queries only.
    queries = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    # category lookup + resolve listings + load products, regardless of result count (no N+1)
    assert len(queries) == 3, queries
