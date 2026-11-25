"""SearchService business logic with a fake store runner and a fake catalogue (no database)."""

import uuid
from collections.abc import Collection
from typing import Any

import pytest
from pydantic import ValidationError

from app.adapters.schemas import (
    AdapterResult,
    AdapterStatus,
    StoreListing,
    StoreSearchOutcome,
    StoreSearchQuery,
)
from app.core.errors import ServiceUnavailableError
from app.core.stores import STORES_BY_SLUG
from app.models import Category, Platform, Product
from app.repositories.catalog import ResolvedListing
from app.schemas.search import ProductSearchResult, SearchRequest, SearchSort
from app.services.search import InvalidSearchFilterError, SearchService
from tests.adapters.fakes import make_listing

# --------------------------------------------------------------------------- #
# Fixtures: a tiny catalogue held in memory
# --------------------------------------------------------------------------- #
PLATFORMS = {
    slug: Platform(
        id=uuid.uuid7(),
        slug=slug,
        name=STORES_BY_SLUG[slug].name,
        base_url=STORES_BY_SLUG[slug].base_url,
        logo_url=None,
    )
    for slug in ("amazon", "flipkart", "croma")
}
ELECTRONICS = Category(id=uuid.uuid7(), name="Electronics", slug="electronics", parent_id=None)
MOBILES = Category(id=uuid.uuid7(), name="Mobiles", slug="mobiles", parent_id=ELECTRONICS.id)
FASHION = Category(id=uuid.uuid7(), name="Fashion", slug="fashion", parent_id=None)
FOOTWEAR = Category(id=uuid.uuid7(), name="Footwear", slug="footwear", parent_id=FASHION.id)
CATEGORIES = [ELECTRONICS, MOBILES, FASHION, FOOTWEAR]


def product(title: str, category: Category, brand: str = "Brand") -> Product:
    return Product(
        id=uuid.uuid7(),
        canonical_title=title,
        brand=brand,
        category_id=category.id,
        category=category,
        image_url=None,
    )


PHONE_A = product("Phone A", MOBILES)
PHONE_B = product("Phone B", MOBILES)
SHOE_C = product("Shoe C", FOOTWEAR)


class FakeCatalog:
    def __init__(self, links: dict[tuple[str, str], Product], products: list[Product]) -> None:
        self.links = links
        self.products = {p.id: p for p in products}
        self.calls: list[str] = []

    async def resolve_listings(
        self, keys: Collection[tuple[str, str]]
    ) -> dict[tuple[str, str], ResolvedListing]:
        self.calls.append("resolve_listings")
        return {
            key: ResolvedListing(uuid.uuid7(), self.links[key].id, PLATFORMS[key[0]])
            for key in keys
            if key in self.links
        }

    async def get_products(self, ids: Collection[uuid.UUID]) -> dict[uuid.UUID, Product]:
        self.calls.append("get_products")
        return {i: self.products[i] for i in ids if i in self.products}

    async def category_with_descendants(self, slug: str) -> set[uuid.UUID] | None:
        self.calls.append("category_with_descendants")
        root = next((c for c in CATEGORIES if c.slug == slug), None)
        if root is None:
            return None
        return {root.id} | {c.id for c in CATEGORIES if c.parent_id == root.id}


class FakeRunner:
    def __init__(self, results: list[AdapterResult]) -> None:
        self.results = results
        self.queries: list[StoreSearchQuery] = []

    async def search_all(self, query: StoreSearchQuery) -> StoreSearchOutcome:
        self.queries.append(query)
        return StoreSearchOutcome(query=query, results=tuple(self.results))


def ok(slug: str, *listings: StoreListing) -> AdapterResult:
    return AdapterResult(slug, AdapterStatus.OK, listings=listings)


def listing(slug: str, ext: str, price: int, **kw: Any) -> StoreListing:
    return make_listing(slug, ext, price=price, **kw)


def standard_setup() -> tuple[FakeRunner, FakeCatalog]:
    """Phone A on amazon+flipkart, Phone B on croma, Shoe C on amazon."""
    runner = FakeRunner(
        [
            ok(
                "amazon",
                listing("amazon", "a-phoneA", 1_000_00, mrp=1_200_00, rating=4.0, review_count=100),
                listing("amazon", "a-shoeC", 300_00, mrp=600_00, rating=3.0, review_count=10),
            ),
            ok(
                "flipkart",
                listing("flipkart", "f-phoneA", 900_00, mrp=1_200_00, rating=5.0, review_count=300),
            ),
            ok("croma", listing("croma", "c-phoneB", 2_000_00, rating=4.5, review_count=50)),
        ]
    )
    catalog = FakeCatalog(
        {
            ("amazon", "a-phoneA"): PHONE_A,
            ("flipkart", "f-phoneA"): PHONE_A,
            ("croma", "c-phoneB"): PHONE_B,
            ("amazon", "a-shoeC"): SHOE_C,
        },
        [PHONE_A, PHONE_B, SHOE_C],
    )
    return runner, catalog


async def run(request: SearchRequest, setup: tuple[FakeRunner, FakeCatalog] | None = None):  # type: ignore[no-untyped-def]
    runner, catalog = setup or standard_setup()
    return await SearchService(runner, catalog).search(request)


def titles(response: Any) -> list[str]:
    return [item.canonical_title for item in response.items]


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
async def test_groups_listings_by_existing_product_link() -> None:
    response = await run(SearchRequest(q="phone"))
    phone_a = next(i for i in response.items if i.id == PHONE_A.id)
    assert phone_a.store_count == 2
    assert phone_a.best_price == 900_00 and phone_a.best_platform.slug == "flipkart"
    assert phone_a.highest_price == 1_000_00
    assert phone_a.mrp == 1_200_00  # MRP of the best-price listing
    assert phone_a.max_discount_percent == 25  # (1200-900)*100//1200
    assert phone_a.rating == 4.8  # (4.0*100 + 5.0*300) / 400 = 4.75 -> 4.8
    assert phone_a.review_count == 400
    assert phone_a.category is not None and phone_a.category.slug == "mobiles"
    assert response.total == 3


async def test_best_price_prefers_in_stock_listings() -> None:
    runner, catalog = standard_setup()
    runner.results[1] = ok(
        "flipkart", listing("flipkart", "f-phoneA", 900_00, in_stock=False, mrp=1_200_00)
    )
    response = await run(SearchRequest(q="phone"), (runner, catalog))
    phone_a = next(i for i in response.items if i.id == PHONE_A.id)
    assert phone_a.best_price == 1_000_00 and phone_a.best_platform.slug == "amazon"
    assert phone_a.highest_price == 1_000_00 and phone_a.in_stock


async def test_all_out_of_stock_uses_cheapest_and_flags_it() -> None:
    runner = FakeRunner(
        [
            ok("amazon", listing("amazon", "a-phoneA", 1_000_00, in_stock=False)),
            ok("flipkart", listing("flipkart", "f-phoneA", 900_00, in_stock=False)),
        ]
    )
    _, catalog = standard_setup()
    response = await run(SearchRequest(q="phone"), (runner, catalog))
    assert response.items[0].best_price == 900_00
    assert response.items[0].in_stock is False


async def test_unresolved_listings_are_excluded_and_counted() -> None:
    runner, catalog = standard_setup()
    runner.results.append(ok("croma", listing("croma", "c-unknown", 10_00)))
    response = await run(SearchRequest(q="phone"), (runner, catalog))
    assert response.unresolved_count == 1
    assert response.total == 3  # the unknown listing is not shown


async def test_listing_pointing_at_missing_product_is_counted_unresolved() -> None:
    runner, catalog = standard_setup()
    del catalog.products[PHONE_B.id]
    response = await run(SearchRequest(q="phone"), (runner, catalog))
    assert response.unresolved_count == 1
    assert PHONE_B.id not in {i.id for i in response.items}


async def test_no_hits_returns_empty_page() -> None:
    response = await run(SearchRequest(q="zzz"), (FakeRunner([ok("amazon")]), FakeCatalog({}, [])))
    assert response.items == [] and response.total == 0 and response.pages == 0
    assert response.partial is False


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("electronics", {"Phone A", "Phone B"}),  # parent includes children
        ("mobiles", {"Phone A", "Phone B"}),
        ("fashion", {"Shoe C"}),
        ("footwear", {"Shoe C"}),
    ],
)
async def test_category_filter_includes_descendants(category: str, expected: set[str]) -> None:
    response = await run(SearchRequest(q="x", category=category))
    assert set(titles(response)) == expected
    assert response.category == category


async def test_unknown_category_is_rejected_before_querying_stores() -> None:
    runner, catalog = standard_setup()
    with pytest.raises(InvalidSearchFilterError) as excinfo:
        await SearchService(runner, catalog).search(SearchRequest(q="x", category="spaceships"))
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "invalid_filter"
    assert excinfo.value.details and excinfo.value.details[0].loc == ["query", "category"]
    assert runner.queries == []  # no store was called


@pytest.mark.parametrize(
    ("min_price", "max_price", "expected"),
    [
        (None, 900_00, {"Phone A", "Shoe C"}),  # boundary is inclusive
        (900_00, None, {"Phone A", "Phone B"}),
        (900_00, 900_00, {"Phone A"}),
        (301_00, 899_00, set()),
        (None, None, {"Phone A", "Phone B", "Shoe C"}),
    ],
)
async def test_price_filters_apply_to_best_price(
    min_price: int | None, max_price: int | None, expected: set[str]
) -> None:
    response = await run(SearchRequest(q="x", min_price=min_price, max_price=max_price))
    assert set(titles(response)) == expected


async def test_store_query_has_no_price_filter_and_uses_store_limit() -> None:
    runner, catalog = standard_setup()
    await SearchService(runner, catalog).search(
        SearchRequest(q=" phone ", category="mobiles", min_price=1, max_price=5)
    )
    sent = runner.queries[0]
    assert sent.text == "phone"
    assert sent.category_slug == "mobiles"
    assert sent.min_price is None and sent.max_price is None
    assert sent.limit == 50


async def test_overlong_category_slug_is_not_forwarded_to_stores() -> None:
    long_slug = "c" * 60  # valid for the DB (<= 80) but above the adapter slug limit (50)
    extra = Category(id=uuid.uuid7(), name="Long", slug=long_slug, parent_id=None)
    CATEGORIES.append(extra)
    try:
        runner, catalog = standard_setup()
        await SearchService(runner, catalog).search(SearchRequest(q="x", category=long_slug))
        assert runner.queries[0].category_slug is None
    finally:
        CATEGORIES.remove(extra)


# --------------------------------------------------------------------------- #
# Sorting and pagination
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        # relevance: best per-store rank (Phone A and Phone B rank 0, Shoe C rank 1),
        # then more stores (Phone A has 2), then title
        (SearchSort.RELEVANCE, ["Phone A", "Phone B", "Shoe C"]),
        (SearchSort.PRICE_ASC, ["Shoe C", "Phone A", "Phone B"]),
        (SearchSort.PRICE_DESC, ["Phone B", "Phone A", "Shoe C"]),
        (SearchSort.DISCOUNT, ["Shoe C", "Phone A", "Phone B"]),  # 50%, 25%, none
        (SearchSort.RATING, ["Phone A", "Phone B", "Shoe C"]),  # 4.8, 4.5, 3.0
    ],
)
async def test_sort_options(sort: SearchSort, expected: list[str]) -> None:
    assert titles(await run(SearchRequest(q="x", sort=sort))) == expected


async def test_ties_are_broken_deterministically_by_id() -> None:
    p1, p2 = product("Same", MOBILES), product("Same", MOBILES)
    runner = FakeRunner(
        [
            ok(
                "amazon",
                listing("amazon", "x1", 500_00),
                listing("amazon", "x2", 500_00),
            )
        ]
    )
    catalog = FakeCatalog({("amazon", "x1"): p1, ("amazon", "x2"): p2}, [p1, p2])
    ids = [
        i.id for i in (await run(SearchRequest(q="x", sort="price_asc"), (runner, catalog))).items
    ]
    assert ids == sorted([p1.id, p2.id], key=str)


async def test_pagination_pages_and_out_of_range() -> None:
    pages = [
        await run(SearchRequest(q="x", sort="price_asc", page=n, page_size=2)) for n in (1, 2, 3)
    ]
    assert [titles(p) for p in pages] == [["Shoe C", "Phone A"], ["Phone B"], []]
    assert all(p.total == 3 and p.pages == 2 and p.page_size == 2 for p in pages)
    assert [p.page for p in pages] == [1, 2, 3]


# --------------------------------------------------------------------------- #
# Store failures
# --------------------------------------------------------------------------- #
async def test_partial_store_failure_still_returns_results() -> None:
    runner, catalog = standard_setup()
    runner.results[1] = AdapterResult("flipkart", AdapterStatus.TIMEOUT, error_code="timeout")
    response = await run(SearchRequest(q="phone"), (runner, catalog))
    assert response.partial is True
    statuses = {s.platform: (s.status, s.error_code, s.result_count) for s in response.stores}
    assert statuses["flipkart"] == ("timeout", "timeout", 0)
    assert statuses["amazon"] == ("ok", None, 2)
    phone_a = next(i for i in response.items if i.id == PHONE_A.id)
    assert phone_a.store_count == 1 and phone_a.best_platform.slug == "amazon"


async def test_every_store_failing_is_503() -> None:
    runner = FakeRunner(
        [
            AdapterResult("amazon", AdapterStatus.ERROR, error_code="AdapterUnavailableError"),
            AdapterResult("flipkart", AdapterStatus.TIMEOUT, error_code="timeout"),
        ]
    )
    with pytest.raises(ServiceUnavailableError):
        await run(SearchRequest(q="x"), (runner, FakeCatalog({}, [])))


async def test_no_stores_configured_is_503() -> None:
    with pytest.raises(ServiceUnavailableError):
        await run(SearchRequest(q="x"), (FakeRunner([]), FakeCatalog({}, [])))


# --------------------------------------------------------------------------- #
# Request validation and response contract
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kwargs",
    [
        {"q": "x" * 201},
        {"q": "x", "min_price": 500, "max_price": 100},
        {"q": "x", "min_price": -1},
        {"q": "x", "min_price": 10.5},
        {"q": "x", "page": 0},
        {"q": "x", "page_size": 0},
        {"q": "x", "page_size": 51},
        {"q": "x", "sort": "cheapest"},
        {"q": "x", "category": "Mobiles!"},
        {"q": "x", "unexpected": 1},
    ],
)
def test_invalid_requests_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SearchRequest(**kwargs)


def test_blank_category_means_no_filter() -> None:
    assert SearchRequest(q="x", category="  ").category is None


@pytest.mark.parametrize("q", [None, "", "   "])
def test_missing_or_blank_q_means_browse(q: str | None) -> None:
    # Milestone 3.5 (decision 1a): no search text = browse stored listings.
    assert SearchRequest(q=q).q is None


def test_result_matches_frontend_product_summary_contract() -> None:
    # frontend/src/api/types.ts ProductSummary
    frontend_fields = {
        "id", "canonical_title", "brand", "category", "image_url", "best_price", "highest_price",
        "mrp", "max_discount_percent", "rating", "review_count", "store_count", "best_platform",
    }  # fmt: skip
    assert frontend_fields <= set(ProductSearchResult.model_fields)


@pytest.mark.parametrize("limit", [0, -1, 51])
def test_invalid_per_store_limit_fails_at_construction(limit: int) -> None:
    runner, catalog = standard_setup()
    with pytest.raises(ValueError, match="per_store_limit"):
        SearchService(runner, catalog, per_store_limit=limit)
