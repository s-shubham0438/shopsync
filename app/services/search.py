"""Search service: query every enabled store, aggregate, filter, sort and paginate.

Text search (`q` given):

1. Validate the category filter against the database (unknown -> 422 `invalid_filter`).
2. Query all stores through `AdapterRunner` (parallel, per-store timeouts, failure isolation).
   Price filters are NOT sent to stores, so each product's full set of offers is known.
3. Resolve every store listing to ShopSync's database by (platform slug, external id) in one
   query. Listings with no database row are left out and counted (`unresolved_count`): grouping
   unknown listings needs Phase 4 matching.
4. Group by the EXISTING `listings.product_id` links (curated data, not a matching algorithm),
   summarise each product, filter by category (incl. children) and by best price, sort with
   deterministic tie-breaks, then paginate.

Some stores failing -> results with `partial=True`. Every store failing -> 503.

Caching (Milestone 3.4): steps 1-4 up to (not including) the price filter produce a
`SearchSnapshot`, which `SearchCache` stores by (normalised query, category, store scope).
Price filtering, sorting and paging run on the snapshot, so a cache hit makes no store or
database calls for any sort order, page and price range of the same search.

Browsing (no `q`, Milestone 3.5): products and their stored listings come straight from the
database (no store calls, not cached), then the same summarising, filtering, sorting and paging
apply. `/deals` is browsing everything, keeping in-stock discounted products, best discount first.
"""

import logging
import math
import uuid
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from app.adapters.schemas import (
    AdapterStatus,
    StoreSearchOutcome,
    StoreSearchQuery,
)
from app.core.errors import AppError, ServiceUnavailableError
from app.models import Listing, Platform, Product
from app.repositories.catalog import ResolvedListing
from app.schemas.common import ErrorDetail
from app.schemas.search import (
    CategoryRef,
    PlatformRef,
    ProductSearchResult,
    SearchRequest,
    SearchResponse,
    SearchSnapshot,
    SearchSort,
    SnapshotItem,
    StoreSearchStatus,
)
from app.services.cache import CacheStatus, SearchCache

logger = logging.getLogger(__name__)

PER_STORE_LIMIT = 50  # adapters return at most this many listings per store per query
_ADAPTER_SLUG_MAX = 50  # StoreSearchQuery.category_slug limit
MAX_DEALS = 24


class InvalidSearchFilterError(AppError):
    status_code = 422
    code = "invalid_filter"
    message = "Invalid search filter."


class SearchRunner(Protocol):
    async def search_all(self, query: StoreSearchQuery) -> StoreSearchOutcome: ...


class CatalogReader(Protocol):
    async def resolve_listings(
        self, keys: Collection[tuple[str, str]]
    ) -> dict[tuple[str, str], ResolvedListing]: ...

    async def get_products(self, ids: Collection[uuid.UUID]) -> dict[uuid.UUID, Product]: ...

    async def category_with_descendants(self, slug: str) -> set[uuid.UUID] | None: ...

    async def browse_products(self, category_ids: set[uuid.UUID] | None) -> list[Product]: ...


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested without a database)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Offering:
    """One store's offer for a product, from a live store result or a stored listing.

    `rank` is the position in that store's search results (0 for stored listings).
    """

    price: int
    mrp: int | None
    in_stock: bool
    rating: float | None
    review_count: int
    platform: Platform
    rank: int = 0

    @classmethod
    def from_listing(cls, listing: Listing) -> Offering:
        return cls(
            price=listing.current_price,
            mrp=listing.mrp,
            in_stock=listing.in_stock,
            rating=float(listing.rating) if listing.rating is not None else None,
            review_count=listing.review_count,
            platform=listing.platform,
        )


def discount_percent(price: int, mrp: int | None) -> int | None:
    """Same formula as the `listings.discount_percent` generated column."""
    if mrp and mrp > price:
        return (mrp - price) * 100 // mrp
    return None


def weighted_rating(offers: Iterable[Offering]) -> float | None:
    rated = [(o.rating, o.review_count) for o in offers if o.rating is not None]
    if not rated:
        return None
    weight = sum(count for _, count in rated)
    if weight:
        return round(sum(r * count for r, count in rated) / weight, 1)
    return round(sum(r for r, _ in rated) / len(rated), 1)


def best_offer_key(o: Offering) -> tuple[Any, ...]:
    """Cheapest wins; ties go to the better search rank, then the store slug (deterministic)."""
    return (o.price, o.rank, o.platform.slug)


def summarise(product: Product, offers: list[Offering]) -> SnapshotItem:
    """Aggregate one product's offers (non-empty) into a search result."""
    in_stock = [o for o in offers if o.in_stock]
    best = min(in_stock or offers, key=best_offer_key)
    discounts = [d for o in offers if (d := discount_percent(o.price, o.mrp)) is not None]
    result = ProductSearchResult(
        id=product.id,
        canonical_title=product.canonical_title,
        brand=product.brand,
        category=CategoryRef.model_validate(product.category) if product.category else None,
        image_url=product.image_url,
        best_price=best.price,
        highest_price=max(o.price for o in offers),
        mrp=best.mrp,
        max_discount_percent=max(discounts) if discounts else None,
        rating=weighted_rating(offers),
        review_count=sum(o.review_count for o in offers),
        store_count=len({o.platform.id for o in offers}),
        best_platform=PlatformRef.model_validate(best.platform),
        in_stock=bool(in_stock),
    )
    return SnapshotItem(result=result, best_rank=min(o.rank for o in offers))


def _relevance_key(r: SnapshotItem) -> tuple[Any, ...]:
    return (
        r.best_rank,
        -r.result.store_count,
        r.result.canonical_title.casefold(),
        str(r.result.id),
    )


# Every key ends with the product id so equal items always come back in the same order,
# which keeps pagination stable across requests.
SORT_KEYS: dict[SearchSort, Callable[[SnapshotItem], tuple[Any, ...]]] = {
    SearchSort.RELEVANCE: _relevance_key,
    SearchSort.PRICE_ASC: lambda r: (r.result.best_price, str(r.result.id)),
    SearchSort.PRICE_DESC: lambda r: (-r.result.best_price, str(r.result.id)),
    SearchSort.DISCOUNT: lambda r: (
        -(r.result.max_discount_percent or 0),
        r.result.best_price,
        str(r.result.id),
    ),
    SearchSort.RATING: lambda r: (
        r.result.rating is None,
        -(r.result.rating or 0),
        -r.result.review_count,
        str(r.result.id),
    ),
}


def within_price(result: ProductSearchResult, request: SearchRequest) -> bool:
    if request.min_price is not None and result.best_price < request.min_price:
        return False
    return request.max_price is None or result.best_price <= request.max_price


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
class SearchService:
    def __init__(
        self,
        runner: SearchRunner,
        catalog: CatalogReader,
        *,
        per_store_limit: int = PER_STORE_LIMIT,
        cache: SearchCache | None = None,
        cache_scope: str = "",
    ) -> None:
        # Fail at construction, not on every search (StoreSearchQuery accepts 1..50).
        if not 1 <= per_store_limit <= PER_STORE_LIMIT:
            raise ValueError(f"per_store_limit must be between 1 and {PER_STORE_LIMIT}")
        self._runner = runner
        self._catalog = catalog
        self._per_store_limit = per_store_limit
        self._cache = cache
        # The per-store limit changes results too, so it is part of the cache scope.
        self._cache_scope = f"{cache_scope}|limit={per_store_limit}"

    async def search(self, request: SearchRequest) -> SearchResponse:
        if request.q is None:
            snapshot, status = await self._browse_snapshot(request), CacheStatus.BYPASS
        elif self._cache is None:
            snapshot, status = await self._snapshot(request), CacheStatus.BYPASS
        else:
            snapshot, status = await self._cache.get_or_compute(
                request, self._cache_scope, lambda: self._snapshot(request)
            )

        ranked = [item for item in snapshot.items if within_price(item.result, request)]
        ranked.sort(key=SORT_KEYS[request.sort])

        total = len(ranked)
        start = (request.page - 1) * request.page_size
        page_items = [r.result for r in ranked[start : start + request.page_size]]

        logger.info(
            "search_completed",
            extra={
                "mode": "browse" if request.q is None else "text",
                "query_length": len(request.q or ""),
                "cache": status.value,
                "stores": len(snapshot.stores),
                "failed": [s.platform for s in snapshot.stores if s.status != "ok"],
                "partial": snapshot.partial,
                "total": total,
                "unresolved": snapshot.unresolved_count,
            },
        )
        return SearchResponse(
            items=page_items,
            total=total,
            page=request.page,
            page_size=request.page_size,
            pages=math.ceil(total / request.page_size) if total else 0,
            query=request.q,
            category=request.category,
            min_price=request.min_price,
            max_price=request.max_price,
            sort=request.sort,
            partial=snapshot.partial,
            stores=snapshot.stores,
            unresolved_count=snapshot.unresolved_count,
            cache=status.value,
        )

    async def deals(self, limit: int = 8) -> list[ProductSearchResult]:
        """In-stock products with a discount, biggest discount first (stored prices)."""
        if not 1 <= limit <= MAX_DEALS:
            raise ValueError(f"limit must be between 1 and {MAX_DEALS}")
        items = await self._stored_items(None)
        deals = [i for i in items if i.result.in_stock and (i.result.max_discount_percent or 0) > 0]
        deals.sort(key=SORT_KEYS[SearchSort.DISCOUNT])
        return [i.result for i in deals[:limit]]

    async def _category_ids(self, request: SearchRequest) -> set[uuid.UUID] | None:
        if request.category is None:
            return None
        category_ids = await self._catalog.category_with_descendants(request.category)
        if category_ids is None:
            raise InvalidSearchFilterError(
                f"Unknown category '{request.category}'.",
                details=[
                    ErrorDetail(
                        loc=["query", "category"],
                        message="Unknown category.",
                        type="invalid_filter",
                    )
                ],
            )
        return category_ids

    async def _browse_snapshot(self, request: SearchRequest) -> SearchSnapshot:
        items = await self._stored_items(await self._category_ids(request))
        return SearchSnapshot(items=items, stores=[], partial=False, unresolved_count=0)

    async def _stored_items(self, category_ids: set[uuid.UUID] | None) -> list[SnapshotItem]:
        items: list[SnapshotItem] = []
        for product in await self._catalog.browse_products(category_ids):
            offers = [Offering.from_listing(li) for li in product.listings if li.platform.is_active]
            if offers:  # a product with no active store has no price to show
                items.append(summarise(product, offers))
        return items

    async def _snapshot(self, request: SearchRequest) -> SearchSnapshot:
        """Text search steps 1-4 (everything that touches stores or the database). Raises, and
        is then never cached, for an unknown category (422) or when every store failed (503)."""
        if request.q is None:  # search() routes q=None to browsing
            raise ValueError("text search needs q")
        category_ids = await self._category_ids(request)

        outcome = await self._runner.search_all(
            StoreSearchQuery(
                text=request.q,
                # Stores may use it to narrow results; the database filter below is authoritative.
                category_slug=request.category
                if request.category and len(request.category) <= _ADAPTER_SLUG_MAX
                else None,
                limit=self._per_store_limit,
            )
        )
        stores = [
            StoreSearchStatus(
                platform=r.platform_slug,
                status=r.status.value,
                result_count=len(r.listings),
                error_code=r.error_code,
            )
            for r in outcome.results
        ]
        if not any(r.status is AdapterStatus.OK for r in outcome.results):
            logger.warning(
                "search_no_store_responded",
                extra={
                    "stores": [s.platform for s in stores],
                    "failed": list(outcome.failed_stores),
                },
            )
            raise ServiceUnavailableError(
                "No stores responded to this search. Please try again shortly."
            )

        items, unresolved = await self._aggregate(outcome, category_ids)
        return SearchSnapshot(
            items=items,
            stores=stores,
            partial=outcome.is_partial,
            unresolved_count=unresolved,
        )

    async def _aggregate(
        self,
        outcome: StoreSearchOutcome,
        category_ids: set[uuid.UUID] | None,
    ) -> tuple[list[SnapshotItem], int]:
        ranked_listings = [
            (rank, listing)
            for result in outcome.results
            for rank, listing in enumerate(result.listings)
        ]
        resolved = await self._catalog.resolve_listings(
            {(listing.platform_slug, listing.external_id) for _, listing in ranked_listings}
        )

        groups: dict[uuid.UUID, list[Offering]] = {}
        unresolved = 0
        for rank, listing in ranked_listings:
            match = resolved.get((listing.platform_slug, listing.external_id))
            if match is None:
                unresolved += 1
                continue
            groups.setdefault(match.product_id, []).append(
                Offering(
                    price=listing.price,
                    mrp=listing.mrp,
                    in_stock=listing.in_stock,
                    rating=listing.rating,
                    review_count=listing.review_count,
                    platform=match.platform,
                    rank=rank,
                )
            )

        products = await self._catalog.get_products(groups.keys())
        items: list[SnapshotItem] = []
        for product_id, offers in groups.items():
            product = products.get(product_id)
            if product is None:  # listing points at a product that no longer exists
                unresolved += len(offers)
                continue
            if category_ids is not None and product.category_id not in category_ids:
                continue
            items.append(summarise(product, offers))
        if unresolved:
            logger.info("search_unresolved_listings", extra={"count": unresolved})
        return items, unresolved
