import random

import pytest

from app.adapters.base import AdapterUnavailableError
from app.adapters.mock import MockStoreAdapter
from app.adapters.schemas import StoreSearchQuery
from app.adapters.urls import url_problem
from app.core.stores import STORES, STORES_BY_SLUG
from app.db.seed_data import PRODUCTS, listing_external_id


def adapter(slug: str = "amazon", **kw: object) -> MockStoreAdapter:
    return MockStoreAdapter(STORES_BY_SLUG[slug], latency_ms=0, **kw)  # type: ignore[arg-type]


def q(text: str, **kw: object) -> StoreSearchQuery:
    return StoreSearchQuery(text=text, **kw)  # type: ignore[arg-type]


async def test_finds_products_by_title_and_brand() -> None:
    results = await adapter("flipkart").search(q("iphone 15"))
    assert [r.external_id for r in results] == ["seed-iphone-15-128-black-flipkart"]
    assert results[0].price == 59_999_00


async def test_category_synonyms_use_word_prefixes() -> None:
    results = await adapter("amazon").search(q("phone"))
    assert results
    assert {r.category_hint for r in results} == {"mobiles"}  # not headphones


async def test_only_returns_products_sold_by_that_store() -> None:
    croma = await adapter("croma").search(q("sneakers"))
    assert croma == []  # Croma doesn't stock the seeded shoes
    myntra = await adapter("myntra").search(q("sneakers"))
    assert myntra and all(r.platform_slug == "myntra" for r in myntra)


async def test_filters_and_limit() -> None:
    a = adapter("amazon")
    cheap = await a.search(q("apple", max_price=25_000_00))
    assert cheap and all(r.price <= 25_000_00 for r in cheap)
    fashion = await a.search(q("men", category_slug="fashion"))
    assert fashion and all(r.category_hint in {"clothing", "footwear"} for r in fashion)
    assert len(await a.search(q("apple", limit=1))) == 1


async def test_nonsense_query_returns_nothing() -> None:
    assert await adapter().search(q("!!")) == []
    assert await adapter().search(q("zzzzqqq")) == []


async def test_records_match_seeded_listings_and_pass_url_policy() -> None:
    for store in STORES:
        a = adapter(store.slug)
        for p in PRODUCTS:
            if store.slug not in p.prices:
                continue
            listing = await a.get_product(listing_external_id(p, store.slug))
            assert listing is not None
            assert listing.price == p.prices[store.slug] * 100
            assert url_problem(listing.url, store.allowed_hosts) is None
    assert await adapter().get_product("does-not-exist") is None


async def test_out_of_stock_is_reported() -> None:
    jbl = await adapter("croma").search(q("jbl flip"))
    assert jbl and jbl[0].in_stock is False


async def test_results_are_deterministic() -> None:
    a = adapter("amazon")
    first, second = await a.search(q("apple")), await a.search(q("apple"))
    # Everything except the fetch timestamp is identical between calls.
    assert [r.model_dump(exclude={"fetched_at"}) for r in first] == [
        r.model_dump(exclude={"fetched_at"}) for r in second
    ]


async def test_failure_injection_raises_adapter_error() -> None:
    always_down = adapter(failure_rate=1.0, rng=random.Random(1))  # noqa: S311
    with pytest.raises(AdapterUnavailableError):
        await always_down.search(q("iphone"))


def test_rejects_invalid_failure_rate() -> None:
    with pytest.raises(ValueError, match="failure_rate"):
        adapter(failure_rate=1.5)
