"""The interface every store integration implements (mock or real).

Rules for adapter authors:

* Call only official / affiliate APIs. No scraping: the interface has no notion of HTML.
* Return `StoreListing`s with the store's own product URL. Affiliate links are generated
  server-side elsewhere, and the runner rejects URLs outside `allowed_hosts`.
* Raise an `AdapterError` subclass for expected failures. Keep messages free of secrets
  (keys, signed URLs); they are logged.
* Don't implement timeouts or catch-all error handling here: the runner does that uniformly.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import ClassVar, Literal

from pydantic import ValidationError

from app.adapters.logsafe import redact
from app.adapters.schemas import StoreListing, StoreSearchQuery
from app.core.stores import StoreInfo

logger = logging.getLogger("app.adapters")

type AdapterMode = Literal["mock", "live"]


class AdapterError(Exception):
    """Base for expected adapter failures.

    `code` (optional) is the stable error_code reported to callers; by default the class name.
    """

    code: ClassVar[str | None] = None


class AdapterUnavailableError(AdapterError):
    """Store API unreachable or returned a server error."""


class AdapterRateLimitedError(AdapterError):
    def __init__(self, message: str = "rate limited", *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AdapterAuthError(AdapterError):
    """Credentials missing, invalid or revoked."""


class AdapterResponseError(AdapterError):
    """Store answered, but with a payload we can't use."""


class ExternalIdMismatchError(AdapterResponseError):
    """get_product() returned a different product than the one requested."""

    code = "external_id_mismatch"


def log_rejected(platform_slug: str, reason: str, *, external_id: object = None) -> None:
    """Single place that records dropped store records. Never logs URLs (they may carry tags or
    keys); the external id is logged only if it is a string, and redacted like any error text."""
    safe_id = redact(external_id) if isinstance(external_id, str) else None
    logger.warning(
        "adapter_listing_rejected",
        extra={"platform": platform_slug, "reason": reason, "external_id": safe_id},
    )


class StoreAdapter(ABC):
    mode: ClassVar[AdapterMode]
    #: Store-specific default timeout; overridden by STORE_ADAPTER_TIMEOUTS, else the global one.
    timeout_seconds: ClassVar[float | None] = None

    def __init__(self, store: StoreInfo) -> None:
        self.store = store

    @property
    def platform_slug(self) -> str:
        return self.store.slug

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return self.store.allowed_hosts

    @abstractmethod
    async def search(self, query: StoreSearchQuery) -> list[StoreListing]:
        """Return this store's matches for `query`, most relevant first."""

    @abstractmethod
    async def get_product(self, external_id: str) -> StoreListing | None:
        """Fetch one listing by the store's own id (used for price refresh); None if gone."""

    async def aclose(self) -> None:  # noqa: B027  (optional hook, intentionally empty)
        """Release resources (HTTP clients, …) on application shutdown."""

    def parse_records[T](
        self, records: Iterable[T], to_listing: Callable[[T], StoreListing]
    ) -> list[StoreListing]:
        """Map raw API records to listings, skipping (and logging) any that fail validation,
        so one bad record never fails the whole store."""
        listings: list[StoreListing] = []
        for record in records:
            try:
                listings.append(to_listing(record))
            except ValidationError, ValueError, KeyError, TypeError:
                log_rejected(self.platform_slug, "invalid_record")
        return listings

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.platform_slug} ({self.mode})>"
