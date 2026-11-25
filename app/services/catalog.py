"""Product detail, price history, categories and platforms, from ShopSync's database.

- Product detail is cached in Redis (`ProductCache`, fail-open, `CACHE_TTL_SECONDS`). Nothing
  writes prices yet, so entries simply expire; `ProductCache.invalidate()` is there for the
  price-refresh job.
- Listings on inactive platforms are hidden everywhere.
- Store URLs are re-checked against the store's host allowlist before they are returned
  (defence in depth: the database is not trusted to contain only safe URLs). A listing whose
  URL fails is left out and logged, never shown with a bad link.
- Buy links (`affiliate_url`) always point at ShopSync's own `/go/{listing_id}` redirect, where
  the server adds affiliate parameters (Milestone 3.6).
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import ValidationError

from app.adapters.urls import url_problem
from app.core.config import API_V1_PREFIX
from app.core.errors import NotFoundError
from app.core.stores import STORES_BY_SLUG
from app.models import Category, Listing, Platform, Product
from app.repositories.catalog import HistoryPoint
from app.schemas.catalog import (
    ListingOut,
    OfferOut,
    PriceHistoryResponse,
    PriceHistorySeries,
    PricePoint,
    ProductDetail,
)
from app.schemas.search import CategoryRef, PlatformRef
from app.services.cache import CacheStatus, ProductCache
from app.services.search import Offering, best_offer_key, discount_percent, summarise

logger = logging.getLogger(__name__)

MAX_HISTORY_DAYS = 365


class ProductNotFoundError(NotFoundError):
    message = "Product not found."


class CatalogDetailReader(Protocol):
    async def get_product_with_listings(self, product_id: uuid.UUID) -> Product | None: ...

    async def product_exists(self, product_id: uuid.UUID) -> bool: ...

    async def active_listings(self, product_id: uuid.UUID) -> list[tuple[uuid.UUID, Platform]]: ...

    async def price_points(
        self, listing_ids: list[uuid.UUID], since: datetime
    ) -> list[HistoryPoint]: ...

    async def list_categories(self) -> list[Category]: ...

    async def list_active_platforms(self) -> list[Platform]: ...


def buy_url(listing_id: uuid.UUID) -> str:
    return f"{API_V1_PREFIX}/go/{listing_id}"


def safe_store_url(listing: Listing) -> bool:
    store = STORES_BY_SLUG.get(listing.platform.slug)
    if store is None:  # no allowlist for this platform: never expose its URLs
        problem: str | None = "unknown_store"
    else:
        problem = url_problem(listing.url, store.allowed_hosts)
    if problem is not None:
        logger.warning(
            "listing_url_rejected",
            extra={
                "listing_id": str(listing.id),
                "platform": listing.platform.slug,
                "reason": problem,
            },
        )
        return False
    return True


def parse_offers(listing: Listing) -> list[OfferOut]:
    """Valid offers only; one malformed JSONB entry must not break the whole product page."""
    offers: list[OfferOut] = []
    for raw in listing.offers or []:
        try:
            offers.append(OfferOut.model_validate(raw))
        except ValidationError:
            logger.warning("listing_offer_skipped", extra={"listing_id": str(listing.id)})
    return offers


def scalar_attributes(product: Product) -> dict[str, str | int | float | bool]:
    """Product attributes as a flat key -> scalar map (nested or null values are dropped)."""
    attributes: dict[str, Any] = product.attributes or {}
    return {str(k): v for k, v in attributes.items() if isinstance(v, str | int | float | bool)}


def build_detail(product: Product) -> ProductDetail | None:
    """None when the product has no listing that can be shown."""
    listings = [li for li in product.listings if li.platform.is_active and safe_store_url(li)]
    if not listings:
        return None
    offers = {li.id: Offering.from_listing(li) for li in listings}
    # In-stock first, then the same order `summarise` uses to pick the best price, so the
    # first listing is always the summary's best_platform/best_price.
    listings.sort(key=lambda li: (not li.in_stock, *best_offer_key(offers[li.id]), str(li.id)))
    summary = summarise(product, list(offers.values())).result

    return ProductDetail(
        **summary.model_dump(),
        model_number=product.model_number,
        ean=product.ean,
        attributes=scalar_attributes(product),
        listings=[
            ListingOut(
                id=li.id,
                platform=PlatformRef.model_validate(li.platform),
                title=li.title,
                url=li.url,
                affiliate_url=buy_url(li.id),
                current_price=li.current_price,
                mrp=li.mrp,
                discount_percent=discount_percent(li.current_price, li.mrp),
                offers=parse_offers(li),
                rating=offers[li.id].rating,
                review_count=li.review_count,
                in_stock=li.in_stock,
                delivery_info=li.delivery_info,
                last_checked_at=li.last_checked_at,
                is_best_deal=index == 0,
            )
            for index, li in enumerate(listings)
        ],
    )


class CatalogService:
    def __init__(
        self,
        catalog: CatalogDetailReader,
        *,
        product_cache: ProductCache | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._cache = product_cache
        self._now = clock or (lambda: datetime.now(UTC))

    async def product_detail(self, product_id: uuid.UUID) -> tuple[ProductDetail, CacheStatus]:
        if self._cache is not None:
            cached = await self._cache.get(product_id, ProductDetail)
            if cached is not None:
                return cached, CacheStatus.HIT
        product = await self._catalog.get_product_with_listings(product_id)
        detail = build_detail(product) if product is not None else None
        if detail is None:
            raise ProductNotFoundError()
        if self._cache is None:
            return detail, CacheStatus.BYPASS
        stored = await self._cache.set(product_id, detail)
        return detail, CacheStatus.MISS if stored else CacheStatus.BYPASS

    async def price_history(self, product_id: uuid.UUID, days: int) -> PriceHistoryResponse:
        if not 1 <= days <= MAX_HISTORY_DAYS:
            raise ValueError(f"days must be between 1 and {MAX_HISTORY_DAYS}")
        if not await self._catalog.product_exists(product_id):
            raise ProductNotFoundError()
        listings = await self._catalog.active_listings(product_id)
        since = self._now() - timedelta(days=days)
        points = await self._catalog.price_points([lid for lid, _ in listings], since)

        by_listing: dict[uuid.UUID, list[PricePoint]] = {}
        for p in points:
            by_listing.setdefault(p.listing_id, []).append(
                PricePoint(recorded_at=p.recorded_at, price=p.price, mrp=p.mrp)
            )
        series = [
            PriceHistorySeries(
                listing_id=lid,
                platform=PlatformRef.model_validate(platform),
                points=by_listing[lid],
            )
            for lid, platform in listings
            if lid in by_listing  # stores with no data in the window are left out
        ]
        lowest = min(points, key=lambda p: (p.price, p.recorded_at), default=None)
        return PriceHistoryResponse(
            product_id=product_id,
            days=days,
            series=series,
            lowest_price=lowest.price if lowest else None,
            lowest_at=lowest.recorded_at if lowest else None,
        )

    async def categories(self) -> list[CategoryRef]:
        return [CategoryRef.model_validate(c) for c in await self._catalog.list_categories()]

    async def platforms(self) -> list[PlatformRef]:
        return [PlatformRef.model_validate(p) for p in await self._catalog.list_active_platforms()]
