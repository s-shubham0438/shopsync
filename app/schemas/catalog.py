"""Product detail and price history contracts (match frontend/src/api/types.ts).

Money is integer paise. Times are timezone-aware UTC.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel
from app.schemas.search import PlatformRef, ProductSearchResult

OfferType = Literal["bank", "coupon", "cashback", "exchange", "emi"]


class OfferOut(APIModel):
    type: OfferType
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=1000)


class ListingOut(APIModel):
    id: uuid.UUID
    platform: PlatformRef
    title: str
    url: str = Field(description="The store's product page (validated against the store allowlist)")
    affiliate_url: str = Field(
        description="ShopSync's outbound link for this listing; the server adds affiliate tags"
    )
    current_price: int
    mrp: int | None
    discount_percent: int | None
    offers: list[OfferOut]
    rating: float | None
    review_count: int
    in_stock: bool
    delivery_info: str | None
    last_checked_at: datetime
    is_best_deal: bool


class ProductDetail(ProductSearchResult):
    model_number: str | None
    ean: str | None
    attributes: dict[str, str | int | float | bool]
    listings: list[ListingOut] = Field(
        description="In-stock listings first, then by price; exactly one has is_best_deal=true"
    )


class PricePoint(APIModel):
    recorded_at: datetime
    price: int
    mrp: int | None


class PriceHistorySeries(APIModel):
    listing_id: uuid.UUID
    platform: PlatformRef
    points: list[PricePoint] = Field(description="Oldest first")


class PriceHistoryResponse(APIModel):
    product_id: uuid.UUID
    days: int
    series: list[PriceHistorySeries]
    lowest_price: int | None = Field(description="Lowest price in the window, any store")
    lowest_at: datetime | None = Field(description="When lowest_price was first recorded")
