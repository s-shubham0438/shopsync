"""Public catalogue endpoints: search, deals, product detail, price history, categories,
platforms. No authentication; read-only."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import CatalogServiceDep, SearchServiceDep
from app.schemas.catalog import PriceHistoryResponse, ProductDetail
from app.schemas.common import ErrorResponse
from app.schemas.search import (
    CategoryRef,
    PlatformRef,
    ProductSearchResult,
    SearchRequest,
    SearchResponse,
)
from app.services.catalog import MAX_HISTORY_DAYS
from app.services.search import MAX_DEALS

router = APIRouter(tags=["catalog"])

# Reference data changes rarely; let browsers and CDNs reuse it for a few minutes.
REFERENCE_CACHE_CONTROL = "public, max-age=300"

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"}}

ProductId = Annotated[uuid.UUID, Path(description="Product id (UUID)")]


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search products across stores",
    description="With `q`: queries every enabled store in parallel and groups results by "
    "product (cached; see `cache`). Without `q`: browses stored listings, optionally within "
    "`category`. Money is integer paise. `partial` is true when some stores failed.",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "No store responded",
        }
    },
)
async def search(
    params: Annotated[SearchRequest, Query()], service: SearchServiceDep
) -> SearchResponse:
    return await service.search(params)


@router.get(
    "/deals",
    response_model=list[ProductSearchResult],
    summary="Best current deals",
    description="In-stock products with a discount, biggest discount first (stored prices).",
)
async def deals(
    service: SearchServiceDep,
    limit: Annotated[int, Query(ge=1, le=MAX_DEALS)] = 8,
) -> list[ProductSearchResult]:
    return await service.deals(limit)


@router.get(
    "/products/{product_id}",
    response_model=ProductDetail,
    summary="Product detail with every store listing",
    description="Listings are in-stock first, then cheapest first; exactly one has "
    "`is_best_deal`. The `X-Cache` header says whether Redis served it.",
    responses=_NOT_FOUND,
)
async def product_detail(
    product_id: ProductId, response: Response, service: CatalogServiceDep
) -> ProductDetail:
    detail, cache = await service.product_detail(product_id)
    response.headers["X-Cache"] = cache.value
    return detail


@router.get(
    "/products/{product_id}/price-history",
    response_model=PriceHistoryResponse,
    summary="Price history per store",
    responses=_NOT_FOUND,
)
async def price_history(
    product_id: ProductId,
    service: CatalogServiceDep,
    days: Annotated[int, Query(ge=1, le=MAX_HISTORY_DAYS, description="Window size in days")] = 30,
) -> PriceHistoryResponse:
    return await service.price_history(product_id, days)


@router.get("/categories", response_model=list[CategoryRef], summary="All categories")
async def categories(response: Response, service: CatalogServiceDep) -> list[CategoryRef]:
    response.headers["Cache-Control"] = REFERENCE_CACHE_CONTROL
    return await service.categories()


@router.get("/platforms", response_model=list[PlatformRef], summary="Active stores")
async def platforms(response: Response, service: CatalogServiceDep) -> list[PlatformRef]:
    response.headers["Cache-Control"] = REFERENCE_CACHE_CONTROL
    return await service.platforms()
