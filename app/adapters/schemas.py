"""Adapter-layer data contracts.

These are deliberately independent of the SQLAlchemy models: adapters describe what a store
returned; mapping into `listings`/`products` rows is the search service's job. Money is integer
paise, never floats.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.adapters.urls import url_problem

# ₹100 crore upper bound: catches unit mistakes (rupees vs paise, a 100x error) and corrupt feeds.
MAX_PAISE = 10**11

Paise = Annotated[int, Field(ge=0, le=MAX_PAISE, strict=True)]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9-]{1,50}$")]
AttributeValue = str | int | float | bool

_EAN_STRIP = re.compile(r"[\s-]")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class OfferType(StrEnum):
    BANK = "bank"
    COUPON = "coupon"
    CASHBACK = "cashback"
    EXCHANGE = "exchange"
    EMI = "emi"


class Offer(_Frozen):
    type: OfferType
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)


class StoreSearchQuery(_Frozen):
    """What the search service asks every store. Sorting and paging happen after aggregation."""

    text: str = Field(min_length=1, max_length=200)
    category_slug: Slug | None = None
    min_price: Paise | None = None
    max_price: Paise | None = None
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def _price_range(self) -> Self:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must not exceed max_price")
        return self


class StoreListing(_Frozen):
    """One product as a store presents it, normalised across stores."""

    platform_slug: Slug
    external_id: str = Field(min_length=1, max_length=120)  # ASIN, FSN, style id…
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1)  # store product page; host allowlist enforced by the runner
    image_url: str | None = None
    price: Paise
    mrp: Paise | None = None
    in_stock: bool = True
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int = Field(default=0, ge=0)
    offers: tuple[Offer, ...] = Field(default=(), max_length=20)
    delivery_info: str | None = Field(default=None, max_length=200)
    # Matching signals for grouping the same product across stores (Phase 4).
    brand: str | None = Field(default=None, max_length=120)
    model_number: str | None = Field(default=None, max_length=120)
    ean: str | None = None
    category_hint: str | None = Field(default=None, max_length=100)
    attributes: dict[str, AttributeValue] = Field(default_factory=dict, max_length=50)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("url")
    @classmethod
    def _url_structurally_safe(cls, value: str) -> str:
        if problem := url_problem(value):
            raise ValueError(problem)
        return value

    @field_validator("image_url")
    @classmethod
    def _drop_unsafe_image(cls, value: str | None) -> str | None:
        # Images are optional: an unsafe one is dropped rather than rejecting the listing.
        return None if value is None or url_problem(value) else value

    @field_validator("mrp")
    @classmethod
    def _mrp_not_below_price(cls, value: int | None, info: Any) -> int | None:
        price = info.data.get("price")
        return None if value is not None and price is not None and value < price else value

    @field_validator("rating")
    @classmethod
    def _one_decimal(cls, value: float | None) -> float | None:
        return None if value is None else round(value, 1)

    @field_validator("ean", mode="before")
    @classmethod
    def _normalise_ean(cls, value: object) -> str | None:
        if value is None:
            return None
        digits = _EAN_STRIP.sub("", str(value))
        return digits if digits.isdigit() and 8 <= len(digits) <= 14 else None

    @field_validator("fetched_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class AdapterStatus(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Outcome of one store call. `error_code` is a class name or "timeout", never a message."""

    platform_slug: str
    status: AdapterStatus
    listings: tuple[StoreListing, ...] = ()
    duration_ms: float = 0.0
    error_code: str | None = None
    rejected: int = 0  # records dropped by validation (see runner logs for reasons)


@dataclass(frozen=True, slots=True)
class StoreSearchOutcome:
    query: StoreSearchQuery
    results: tuple[AdapterResult, ...]

    @property
    def listings(self) -> tuple[StoreListing, ...]:
        return tuple(listing for r in self.results for listing in r.listings)

    @property
    def is_partial(self) -> bool:
        """True when at least one store failed, so the result set may be incomplete."""
        return any(r.status is not AdapterStatus.OK for r in self.results)

    @property
    def failed_stores(self) -> tuple[str, ...]:
        return tuple(r.platform_slug for r in self.results if r.status is not AdapterStatus.OK)
