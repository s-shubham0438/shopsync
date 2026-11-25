"""Milestone 3.2 verification: the real mock adapters for all six stores, end to end.

Uses MockStoreAdapter (not test fakes) through the registry and runner, so this exercises exactly
what the search service will call: seed-catalogue reuse, per-store isolation, parallel execution
and per-store timeouts.
"""

import random
import time

import pytest

from app.adapters.base import AdapterUnavailableError
from app.adapters.mock import MockStoreAdapter
from app.adapters.registry import AdapterRegistry
from app.adapters.runner import AdapterRunner
from app.adapters.schemas import AdapterStatus, StoreSearchQuery
from app.adapters.urls import url_problem
from app.core.config import Settings
from app.core.stores import STORES, STORES_BY_SLUG
from app.db.seed_data import PRODUCTS, listing_external_id

SIX = ["amazon", "flipkart", "myntra", "ajio", "croma", "tatacliq"]
SEED_BY_LISTING_ID = {
    listing_external_id(p, slug): (p, slug) for p in PRODUCTS for slug in p.prices
}


def mock(slug: str, *, latency_ms: int = 0, failure_rate: float = 0.0) -> MockStoreAdapter:
    # Seeded RNG: simulated latency jitter and failures are reproducible.
    rng = random.Random(f"test-{slug}")  # noqa: S311
    return MockStoreAdapter(
        STORES_BY_SLUG[slug], latency_ms=latency_ms, failure_rate=failure_rate, rng=rng
    )


def all_six(**overrides: dict[str, object]) -> list[MockStoreAdapter]:
    return [mock(slug, **overrides.get(slug, {})) for slug in SIX]  # type: ignore[arg-type]


def test_registry_loads_one_mock_adapter_per_store() -> None:
    registry = AdapterRegistry.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    assert registry.platform_slugs == tuple(SIX) == tuple(s.slug for s in STORES)
    assert all(type(a) is MockStoreAdapter for a in registry.adapters)
    assert len({id(a) for a in registry.adapters}) == 6  # independent instances


@pytest.mark.parametrize("slug", SIX)
def test_every_store_has_catalogue_coverage(slug: str) -> None:
    stocked = [p for p in PRODUCTS if slug in p.prices]
    assert len(stocked) >= 3, f"{slug} needs enough demo products to be useful"


@pytest.mark.parametrize("slug", SIX)
async def test_store_returns_only_its_own_seeded_listings(slug: str) -> None:
    adapter = mock(slug)
    seen = 0
    for query in ("apple", "men", "black", "bag", "sneakers", "phone", "watch"):
        for listing in await adapter.search(StoreSearchQuery(text=query, limit=50)):
            seen += 1
            product, seeded_slug = SEED_BY_LISTING_ID[listing.external_id]  # reuses the catalogue
            assert seeded_slug == slug == listing.platform_slug
            assert listing.price == product.prices[slug] * 100  # integer paise, seeded price
            assert listing.mrp == product.mrp * 100
            assert url_problem(listing.url, STORES_BY_SLUG[slug].allowed_hosts) is None
    assert seen > 0


@pytest.mark.parametrize("slug", SIX)
async def test_get_product_round_trip_through_runner(slug: str) -> None:
    runner = AdapterRunner([mock(slug)], default_timeout=1)
    for product in [p for p in PRODUCTS if slug in p.prices][:3]:
        external_id = listing_external_id(product, slug)
        result = await runner.fetch_product(slug, external_id)
        assert result.status is AdapterStatus.OK
        assert [listing.external_id for listing in result.listings] == [external_id]
    missing = await runner.fetch_product(slug, "seed-does-not-exist")
    assert missing.status is AdapterStatus.OK and missing.listings == ()


async def test_all_six_run_in_parallel() -> None:
    adapters = all_six(**{slug: {"latency_ms": 200} for slug in SIX})
    started = time.perf_counter()
    outcome = await AdapterRunner(adapters, default_timeout=2).search_all(
        StoreSearchQuery(text="apple")
    )
    elapsed = time.perf_counter() - started
    # Sequential would be ~6 x 0.2s = 1.2s; parallel is about one store's latency (+30% jitter).
    assert elapsed < 0.6, f"looks sequential: {elapsed:.2f}s"
    assert [r.status for r in outcome.results] == [AdapterStatus.OK] * 6
    assert not outcome.is_partial


async def test_one_failing_store_does_not_affect_the_other_five() -> None:
    adapters = all_six(croma={"failure_rate": 1.0})
    outcome = await AdapterRunner(adapters, default_timeout=2).search_all(
        StoreSearchQuery(text="apple")
    )
    status = {r.platform_slug: (r.status, r.error_code) for r in outcome.results}
    assert status.pop("croma") == (AdapterStatus.ERROR, AdapterUnavailableError.__name__)
    assert all(s == (AdapterStatus.OK, None) for s in status.values())
    assert outcome.failed_stores == ("croma",)
    hits = {listing.platform_slug for listing in outcome.listings}
    assert "croma" not in hits and {"amazon", "flipkart", "tatacliq"} <= hits


async def test_slow_store_times_out_alone_using_per_store_override() -> None:
    adapters = all_six(myntra={"latency_ms": 3000})
    runner = AdapterRunner(adapters, default_timeout=2, timeouts={"myntra": 0.1})
    started = time.perf_counter()
    outcome = await runner.search_all(StoreSearchQuery(text="sneakers"))
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"slow store held up the search: {elapsed:.2f}s"
    status = {r.platform_slug: r.status for r in outcome.results}
    assert status.pop("myntra") is AdapterStatus.TIMEOUT
    assert all(s is AdapterStatus.OK for s in status.values())
    assert outcome.is_partial and outcome.failed_stores == ("myntra",)


async def test_multiple_simultaneous_failures_are_all_isolated() -> None:
    adapters = all_six(ajio={"failure_rate": 1.0}, croma={"latency_ms": 3000})
    runner = AdapterRunner(adapters, default_timeout=2, timeouts={"croma": 0.1})
    outcome = await runner.search_all(StoreSearchQuery(text="men"))
    status = {r.platform_slug: r.status for r in outcome.results}
    assert status == {
        "amazon": AdapterStatus.OK,
        "flipkart": AdapterStatus.OK,
        "myntra": AdapterStatus.OK,
        "ajio": AdapterStatus.ERROR,
        "croma": AdapterStatus.TIMEOUT,
        "tatacliq": AdapterStatus.OK,
    }


async def test_results_are_deterministic_across_all_six() -> None:
    runner = AdapterRunner(all_six(), default_timeout=2)
    query = StoreSearchQuery(text="black")

    def snapshot(outcome: object) -> list[dict[str, object]]:
        return [
            listing.model_dump(exclude={"fetched_at"})
            for listing in outcome.listings  # type: ignore[attr-defined]
        ]

    assert snapshot(await runner.search_all(query)) == snapshot(await runner.search_all(query))
