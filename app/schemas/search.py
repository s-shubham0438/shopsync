"""Search request/response contracts (consumed by GET /search in Milestone 3.5).

`ProductSearchResult` matches the frontend's `ProductSummary` (frontend/src/api/types.ts) so the
UI can switch from mock data to the real API without changes. Money is integer paise.
"""

import uuid
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.adapters.schemas import MAX_PAISE
from app.schemas.common import APIModel, Page

MAX_PAGE_SIZE = 50
SearchPaise = Annotated[int, Field(ge=0, le=MAX_PAISE)]


class SearchSort(StrEnum):
    RELEVANCE = "relevance"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    DISCOUNT = "discount"
    RATING = "rating"


class SearchRequest(APIModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    q: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Search text. Omit (or leave blank) to browse the catalogue, "
        "optionally within `category`.",
    )
    category: str | None = Field(
        default=None, pattern=r"^[a-z0-9-]{1,80}$", description="Category slug (includes children)"
    )
    min_price: SearchPaise | None = Field(default=None, description="Paise, applied to best price")
    max_price: SearchPaise | None = Field(default=None, description="Paise, applied to best price")
    sort: SearchSort = SearchSort.RELEVANCE
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("q", "category", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _price_range(self) -> Self:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must not exceed max_price")
        return self


class PlatformRef(APIModel):
    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None
    base_url: str


class CategoryRef(APIModel):
    id: uuid.UUID
    name: str
    slug: str
    parent_id: uuid.UUID | None


class ProductSearchResult(APIModel):
    """One product, aggregated over the store listings the search returned for it."""

    id: uuid.UUID
    canonical_title: str
    brand: str | None
    category: CategoryRef | None
    image_url: str | None
    best_price: int = Field(description="Cheapest in-stock price (paise); cheapest overall if none")
    highest_price: int
    mrp: int | None = Field(description="MRP of the best-price listing")
    max_discount_percent: int | None
    rating: float | None = Field(description="Review-weighted average across stores")
    review_count: int
    store_count: int = Field(description="Distinct stores in this result")
    best_platform: PlatformRef
    in_stock: bool = Field(description="True if at least one store has it in stock")


class StoreSearchStatus(APIModel):
    platform: str
    status: Literal["ok", "timeout", "error"]
    result_count: int = Field(description="Listings this store returned (before grouping)")
    error_code: str | None = None


class SnapshotItem(APIModel):
    """A product result plus its best store rank (needed for relevance sorting)."""

    result: ProductSearchResult
    best_rank: int = Field(ge=0)


class SearchSnapshot(APIModel):
    """Internal, cacheable search result: everything before price filtering, sorting and
    paging, so one cache entry serves every sort order, page and price range of a search."""

    items: list[SnapshotItem]
    stores: list[StoreSearchStatus]
    partial: bool
    unresolved_count: int = Field(ge=0)


class SearchResponse(Page[ProductSearchResult]):
    query: str | None = Field(description="Search text; null when browsing")
    category: str | None
    min_price: int | None
    max_price: int | None
    sort: SearchSort
    partial: bool = Field(description="True if at least one store failed or timed out")
    stores: list[StoreSearchStatus]
    unresolved_count: int = Field(
        description="Store listings not yet linked to a ShopSync product (left out until Phase 4)"
    )
    cache: Literal["hit", "miss", "bypass"] = Field(
        default="bypass",
        description="hit: served from cache (stores not queried for this request); "
        "miss: stores queried; bypass: cache disabled or unavailable",
    )
