"""Builds the configured store adapters and owns their lifecycle.

Adding a real integration later is one entry in LIVE_ADAPTERS, e.g.
    LIVE_ADAPTERS["amazon"] = lambda store, settings: AmazonPAAPIAdapter(store, ...)
No change is needed in the runner, the search service or the API.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence

from app.adapters.base import StoreAdapter
from app.adapters.mock import MockStoreAdapter
from app.adapters.runner import AdapterRunner
from app.core.config import Settings
from app.core.stores import STORES_BY_SLUG, StoreInfo

logger = logging.getLogger("app.adapters")

type AdapterFactory = Callable[[StoreInfo, Settings], StoreAdapter]

#: Real (official/affiliate API) adapters by store slug. Empty until real integrations land.
LIVE_ADAPTERS: dict[str, AdapterFactory] = {}


class StoreAdapterConfigError(RuntimeError):
    """The store adapter configuration can't produce a working set of adapters."""


def build_adapters(
    settings: Settings, live_adapters: dict[str, AdapterFactory] | None = None
) -> list[StoreAdapter]:
    live = LIVE_ADAPTERS if live_adapters is None else live_adapters
    adapters: list[StoreAdapter] = []
    missing: list[str] = []
    for slug in settings.enabled_stores:
        store = STORES_BY_SLUG[slug]  # slugs are validated by Settings
        if settings.store_adapter_mode == "mock":
            adapters.append(
                MockStoreAdapter(
                    store,
                    latency_ms=settings.mock_adapter_latency_ms,
                    failure_rate=settings.mock_adapter_failure_rate,
                )
            )
        elif (factory := live.get(slug)) is not None:
            adapters.append(factory(store, settings))
        else:
            missing.append(slug)

    if missing:
        if not adapters:
            raise StoreAdapterConfigError(
                "STORE_ADAPTER_MODE=live but no live adapter exists for any enabled store "
                f"({', '.join(missing)}). "
                "Use STORE_ADAPTER_MODE=mock until real integrations exist."
            )
        logger.warning(
            "store_adapters_skipped", extra={"stores": missing, "reason": "no live adapter"}
        )
    return adapters


class AdapterRegistry:
    def __init__(self, adapters: Sequence[StoreAdapter], runner: AdapterRunner) -> None:
        self._adapters = {a.platform_slug: a for a in adapters}
        self.runner = runner

    @classmethod
    def from_settings(
        cls, settings: Settings, live_adapters: dict[str, AdapterFactory] | None = None
    ) -> AdapterRegistry:
        adapters = build_adapters(settings, live_adapters)
        runner = AdapterRunner(
            adapters,
            default_timeout=settings.store_adapter_timeout_seconds,
            timeouts=settings.store_adapter_timeouts,
        )
        registry = cls(adapters, runner)
        logger.info(
            "store_adapters_ready",
            extra={"mode": settings.store_adapter_mode, "stores": list(registry.platform_slugs)},
        )
        if settings.is_production and settings.store_adapter_mode == "mock":
            logger.warning("store_adapters_mock_in_production")
        return registry

    @property
    def platform_slugs(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    @property
    def adapters(self) -> tuple[StoreAdapter, ...]:
        return tuple(self._adapters.values())

    def get(self, platform_slug: str) -> StoreAdapter | None:
        return self._adapters.get(platform_slug)

    async def aclose(self) -> None:
        """Close every adapter; one failing to close never prevents the others."""
        results = await asyncio.gather(
            *(a.aclose() for a in self._adapters.values()), return_exceptions=True
        )
        for adapter, result in zip(self._adapters.values(), results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "adapter_close_failed",
                    extra={"platform": adapter.platform_slug, "error_type": type(result).__name__},
                )
