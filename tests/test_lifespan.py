"""A9: startup failures must clean up whatever was already created; shutdown closes everything."""

from types import SimpleNamespace
from typing import Any

import pytest

import app.main as main_module
from app.adapters.registry import AdapterRegistry
from app.core.config import Environment, Settings
from app.main import create_app


def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment=Environment.TEST,
        enabled_stores=["amazon"],
        mock_adapter_latency_ms=0,
    )


class Tracker:
    """Records the order in which resources are closed."""

    def __init__(self) -> None:
        self.closed: list[str] = []

    def engine(self, _settings: Settings, *, fail_dispose: bool = False) -> Any:
        async def dispose() -> None:
            self.closed.append("engine")
            if fail_dispose:
                raise RuntimeError("dispose failed")

        url = SimpleNamespace(render_as_string=lambda hide_password: "postgresql://***@db/x")
        return SimpleNamespace(dispose=dispose, url=url)

    def redis(self, _settings: Settings, *, fail_close: bool = False) -> Any:
        async def aclose() -> None:
            self.closed.append("redis")
            if fail_close:
                raise RuntimeError("redis close failed")

        return SimpleNamespace(aclose=aclose)


@pytest.fixture
def tracker(monkeypatch: pytest.MonkeyPatch) -> Tracker:
    t = Tracker()
    original_aclose = AdapterRegistry.aclose

    async def registry_aclose(self: AdapterRegistry) -> None:
        t.closed.append("registry")
        await original_aclose(self)

    monkeypatch.setattr(AdapterRegistry, "aclose", registry_aclose)
    monkeypatch.setattr(main_module, "create_engine", t.engine)
    monkeypatch.setattr(main_module, "create_redis", t.redis)
    return t


async def test_normal_shutdown_closes_everything_in_reverse_order(tracker: Tracker) -> None:
    app = create_app(settings())
    async with app.router.lifespan_context(app):
        assert tracker.closed == []
        assert app.state.store_registry.platform_slugs == ("amazon",)
    assert tracker.closed == ["redis", "engine", "registry"]


async def test_engine_creation_failure_closes_registry(
    tracker: Tracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_engine(_settings: Settings) -> Any:
        raise RuntimeError("cannot create engine")

    monkeypatch.setattr(main_module, "create_engine", broken_engine)
    app = create_app(settings())
    with pytest.raises(RuntimeError, match="cannot create engine"):
        async with app.router.lifespan_context(app):
            pytest.fail("app must not start")
    assert tracker.closed == ["registry"]


async def test_redis_creation_failure_closes_engine_and_registry(
    tracker: Tracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_redis(_settings: Settings) -> Any:
        raise RuntimeError("cannot create redis")

    monkeypatch.setattr(main_module, "create_redis", broken_redis)
    app = create_app(settings())
    with pytest.raises(RuntimeError, match="cannot create redis"):
        async with app.router.lifespan_context(app):
            pytest.fail("app must not start")
    assert tracker.closed == ["engine", "registry"]


async def test_startup_log_failure_still_cleans_up(
    tracker: Tracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_redact(_url: str) -> str:
        raise ValueError("bad redis url")

    monkeypatch.setattr(main_module, "redact_url", broken_redact)
    app = create_app(settings())
    with pytest.raises(ValueError, match="bad redis url"):
        async with app.router.lifespan_context(app):
            pytest.fail("app must not start")
    assert tracker.closed == ["redis", "engine", "registry"]


async def test_one_failing_cleanup_does_not_skip_the_others(
    tracker: Tracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_module, "create_redis", lambda s: tracker.redis(s, fail_close=True))
    app = create_app(settings())
    with pytest.raises(RuntimeError, match="redis close failed"):
        async with app.router.lifespan_context(app):
            pass
    assert tracker.closed == ["redis", "engine", "registry"]
