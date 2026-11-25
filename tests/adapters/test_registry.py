import pytest

from app.adapters.mock import MockStoreAdapter
from app.adapters.registry import AdapterRegistry, StoreAdapterConfigError, build_adapters
from app.adapters.schemas import AdapterStatus, StoreSearchQuery
from app.core.config import Environment, Settings
from app.core.stores import STORES
from app.main import create_app
from tests.adapters.fakes import FakeAdapter


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, mock_adapter_latency_ms=0, **kw)  # type: ignore[arg-type]


def test_default_builds_a_mock_adapter_for_all_six_stores() -> None:
    adapters = build_adapters(settings())
    assert [a.platform_slug for a in adapters] == [s.slug for s in STORES]
    assert all(isinstance(a, MockStoreAdapter) for a in adapters)


def test_respects_enabled_stores_and_order() -> None:
    adapters = build_adapters(settings(enabled_stores="myntra,amazon"))
    assert [a.platform_slug for a in adapters] == ["myntra", "amazon"]


def test_live_mode_without_any_live_adapter_fails_fast() -> None:
    with pytest.raises(StoreAdapterConfigError, match="STORE_ADAPTER_MODE=mock"):
        build_adapters(settings(store_adapter_mode="live"), live_adapters={})


def test_live_mode_uses_registered_factories_and_skips_others() -> None:
    live = {"amazon": lambda store, _settings: FakeAdapter(store.slug)}
    adapters = build_adapters(
        settings(store_adapter_mode="live", enabled_stores="amazon,flipkart"), live_adapters=live
    )
    assert [type(a).__name__ for a in adapters] == ["FakeAdapter"]


def test_runner_gets_configured_timeouts() -> None:
    registry = AdapterRegistry.from_settings(
        settings(store_adapter_timeout_seconds=3, store_adapter_timeouts="amazon=6")
    )
    amazon, flipkart = registry.get("amazon"), registry.get("flipkart")
    assert amazon is not None and flipkart is not None
    assert registry.runner.timeout_for(amazon) == 6
    assert registry.runner.timeout_for(flipkart) == 3


async def test_end_to_end_mock_search_across_stores() -> None:
    registry = AdapterRegistry.from_settings(settings())
    outcome = await registry.runner.search_all(StoreSearchQuery(text="iphone 15"))
    assert all(r.status is AdapterStatus.OK for r in outcome.results)
    stores_with_hits = {listing.platform_slug for listing in outcome.listings}
    assert stores_with_hits == {"amazon", "flipkart", "croma", "tatacliq"}


async def test_aclose_closes_every_adapter_even_if_one_fails() -> None:
    class Broken(FakeAdapter):
        async def aclose(self) -> None:
            raise RuntimeError("boom")

    good = FakeAdapter("amazon")
    registry = AdapterRegistry([Broken("flipkart"), good], runner=None)  # type: ignore[arg-type]
    await registry.aclose()
    assert good.closed


async def test_app_lifespan_builds_and_closes_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []
    original = AdapterRegistry.aclose

    async def spy(self: AdapterRegistry) -> None:
        closed.append(True)
        await original(self)

    monkeypatch.setattr(AdapterRegistry, "aclose", spy)
    app = create_app(settings(environment=Environment.TEST, enabled_stores="amazon"))
    async with app.router.lifespan_context(app):
        assert app.state.store_registry.platform_slugs == ("amazon",)
    assert closed == [True]


async def test_app_refuses_to_start_with_unusable_adapter_config() -> None:
    app = create_app(settings(environment=Environment.TEST, store_adapter_mode="live"))
    with pytest.raises(StoreAdapterConfigError):
        async with app.router.lifespan_context(app):
            pass
