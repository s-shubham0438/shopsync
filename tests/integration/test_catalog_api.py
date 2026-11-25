"""Milestone 3.5 public catalogue API, end to end over HTTP.

Real app (create_app), real routes and dependencies, six mock stores (no latency), PostgreSQL
`shopsync_test` (seeded, rolled back after each test) and an in-memory fake Redis.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.registry import AdapterRegistry
from app.core.config import Environment, Settings
from app.core.stores import STORES_BY_SLUG
from app.db.seed import run_seed
from app.db.seed_data import CATEGORIES, PRODUCTS
from app.db.session import get_db_session
from app.main import create_app
from app.models import Listing, Platform, Product
from app.services.cache import JsonCache, ProductCache, SearchCache
from tests.services.test_cache_unit import FakeRedis

ClientFactory = Callable[..., Awaitable[httpx.AsyncClient]]

# frontend/src/api/types.ts
FRONTEND_SUMMARY = {
    "id", "canonical_title", "brand", "category", "image_url", "best_price", "highest_price",
    "mrp", "max_discount_percent", "rating", "review_count", "store_count", "best_platform",
}  # fmt: skip
FRONTEND_DETAIL = FRONTEND_SUMMARY | {"model_number", "ean", "attributes", "listings"}
FRONTEND_LISTING = {
    "id", "platform", "title", "url", "affiliate_url", "current_price", "mrp",
    "discount_percent", "offers", "rating", "review_count", "in_stock", "delivery_info",
    "last_checked_at", "is_best_deal",
}  # fmt: skip
FRONTEND_PLATFORM = {"id", "name", "slug", "logo_url", "base_url"}
FRONTEND_CATEGORY = {"id", "name", "slug", "parent_id"}


@pytest.fixture
async def make_client(session: AsyncSession) -> AsyncIterator[ClientFactory]:
    await run_seed(session)
    registries: list[AdapterRegistry] = []
    clients: list[httpx.AsyncClient] = []

    async def factory(**overrides: Any) -> httpx.AsyncClient:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment=Environment.TEST,
            mock_adapter_latency_ms=0,
            **overrides,
        )
        app = create_app(settings)
        # The lifespan isn't run: wire the state it would create, with test doubles.
        registry = AdapterRegistry.from_settings(settings)
        registries.append(registry)
        app.state.store_registry = registry
        store = JsonCache(FakeRedis(), op_timeout=1)
        app.state.search_cache = SearchCache(store, ttl=1800, partial_ttl=60)
        app.state.product_cache = ProductCache(store, ttl=1800)

        async def test_session() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_db_session] = test_session
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()
    for registry in registries:
        await registry.aclose()


@pytest.fixture
async def client(make_client: ClientFactory) -> httpx.AsyncClient:
    return await make_client()


async def product_id(session: AsyncSession, slug: str) -> uuid.UUID:
    seed = next(p for p in PRODUCTS if p.key == slug)
    found = await session.scalar(select(Product.id).where(Product.canonical_title == seed.title))
    assert found is not None
    return found


@contextmanager
def count_selects(session: AsyncSession) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(*args: Any) -> None:
        if args[2].lstrip().upper().startswith("SELECT"):
            statements.append(args[2])

    sync = session.sync_session.get_bind()
    event.listen(sync, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(sync, "before_cursor_execute", record)


def assert_error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    return body["error"]


# --------------------------------------------------------------------------- #
# /search
# --------------------------------------------------------------------------- #
async def test_text_search_then_cache_hit(client: httpx.AsyncClient) -> None:
    first = await client.get("/search", params={"q": "iphone"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["cache"] == "miss"
    assert body["query"] == "iphone"
    assert body["total"] >= 1
    assert len(body["stores"]) == 6
    assert set(body["items"][0]) >= FRONTEND_SUMMARY
    assert set(body["items"][0]["best_platform"]) >= FRONTEND_PLATFORM

    again = await client.get("/search", params={"q": " IPHONE ", "sort": "price_desc"})
    assert again.json()["cache"] == "hit"
    assert again.json()["total"] == body["total"]


async def test_browse_category_without_q(client: httpx.AsyncClient) -> None:
    response = await client.get("/search", params={"category": "mobiles", "sort": "price_asc"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] is None
    assert body["stores"] == []
    assert body["cache"] == "bypass"
    expected = sum(1 for p in PRODUCTS if p.category == "mobiles")
    assert body["total"] == expected > 0
    prices = [i["best_price"] for i in body["items"]]
    assert prices == sorted(prices)
    assert {i["category"]["slug"] for i in body["items"]} == {"mobiles"}


async def test_browse_parent_category_includes_children(client: httpx.AsyncClient) -> None:
    parent = next(c for c in CATEGORIES if any(o.parent == c.slug for o in CATEGORIES))
    children = {c.slug for c in CATEGORIES if c.parent == parent.slug}
    response = await client.get("/search", params={"category": parent.slug, "page_size": 50})
    slugs = {i["category"]["slug"] for i in response.json()["items"]}
    assert slugs <= children | {parent.slug}
    assert slugs & children


async def test_browse_everything_paginates(client: httpx.AsyncClient) -> None:
    page1 = (await client.get("/search", params={"page_size": 7})).json()
    assert page1["total"] == len(PRODUCTS)
    assert page1["pages"] == -(-len(PRODUCTS) // 7)
    ids = [i["id"] for i in page1["items"]]
    for page in range(2, page1["pages"] + 1):
        more = (await client.get("/search", params={"page_size": 7, "page": page})).json()
        ids += [i["id"] for i in more["items"]]
    assert len(ids) == len(set(ids)) == len(PRODUCTS)


@pytest.mark.parametrize(
    "params",
    [
        {"q": "x" * 201},
        {"q": "x", "min_price": 500, "max_price": 100},
        {"q": "x", "page_size": 51},
        {"q": "x", "sort": "cheapest"},
        {"q": "x", "page": 0},
        {"q": "x", "unexpected": "1"},
    ],
)
async def test_search_validation_errors_use_the_envelope(
    client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    error = assert_error(await client.get("/search", params=params), 422, "validation_error")
    assert error["details"]


async def test_unknown_category_is_422_invalid_filter(client: httpx.AsyncClient) -> None:
    for params in ({"q": "phone", "category": "nope"}, {"category": "nope"}):
        error = assert_error(await client.get("/search", params=params), 422, "invalid_filter")
        assert error["details"][0]["loc"] == ["query", "category"]


async def test_all_stores_failing_is_503(make_client: ClientFactory) -> None:
    client = await make_client(mock_adapter_failure_rate=1.0)
    assert_error(await client.get("/search", params={"q": "iphone"}), 503, "service_unavailable")
    # Browsing doesn't touch the stores, so it still works.
    assert (await client.get("/search")).status_code == 200


# --------------------------------------------------------------------------- #
# /deals
# --------------------------------------------------------------------------- #
async def test_deals(client: httpx.AsyncClient) -> None:
    response = await client.get("/deals")
    assert response.status_code == 200
    deals = response.json()
    assert 0 < len(deals) <= 8
    assert all(d["in_stock"] and d["max_discount_percent"] > 0 for d in deals)
    discounts = [d["max_discount_percent"] for d in deals]
    assert discounts == sorted(discounts, reverse=True)
    assert set(deals[0]) >= FRONTEND_SUMMARY

    assert len((await client.get("/deals", params={"limit": 3})).json()) == 3
    for bad in ("0", "25", "x"):
        assert_error(await client.get("/deals", params={"limit": bad}), 422, "validation_error")


# --------------------------------------------------------------------------- #
# /products/{id}
# --------------------------------------------------------------------------- #
async def test_product_detail(client: httpx.AsyncClient, session: AsyncSession) -> None:
    pid = await product_id(session, "iphone-15-128-black")
    response = await client.get(f"/products/{pid}")
    assert response.status_code == 200, response.text
    assert response.headers["x-cache"] == "miss"
    detail = response.json()

    assert set(detail) >= FRONTEND_DETAIL
    listings = detail["listings"]
    assert len(listings) == detail["store_count"] >= 2
    assert all(set(li) >= FRONTEND_LISTING for li in listings)
    assert [li["is_best_deal"] for li in listings].count(True) == 1
    best = listings[0]
    assert best["is_best_deal"]
    assert best["current_price"] == detail["best_price"]
    assert best["platform"]["slug"] == detail["best_platform"]["slug"]

    in_stock = [li for li in listings if li["in_stock"]]
    assert listings[: len(in_stock)] == in_stock  # in-stock first
    prices = [li["current_price"] for li in in_stock]
    assert prices == sorted(prices)

    for li in listings:
        assert li["affiliate_url"] == f"/api/v1/go/{li['id']}"
        host = urlsplit(li["url"]).hostname
        assert host in STORES_BY_SLUG[li["platform"]["slug"]].allowed_hosts
        assert all(o["type"] in {"bank", "coupon", "cashback", "exchange", "emi"}
                   for o in li["offers"])  # fmt: skip

    cached = await client.get(f"/products/{pid}")
    assert cached.headers["x-cache"] == "hit"
    assert cached.json() == detail


async def test_product_not_found_and_bad_id(client: httpx.AsyncClient) -> None:
    error = assert_error(await client.get(f"/products/{uuid.uuid7()}"), 404, "not_found")
    assert error["message"] == "Product not found."
    assert_error(await client.get("/products/not-a-uuid"), 422, "validation_error")


async def test_inactive_platform_hidden_everywhere(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    pid = await product_id(session, "iphone-15-128-black")
    await session.execute(update(Platform).where(Platform.slug == "amazon").values(is_active=False))
    await session.flush()
    client = await make_client()

    detail = (await client.get(f"/products/{pid}")).json()
    assert "amazon" not in {li["platform"]["slug"] for li in detail["listings"]}
    assert "amazon" not in {p["slug"] for p in (await client.get("/platforms")).json()}
    history = (await client.get(f"/products/{pid}/price-history")).json()
    assert "amazon" not in {s["platform"]["slug"] for s in history["series"]}
    browse = (await client.get("/search", params={"page_size": 50})).json()
    assert all(i["best_platform"]["slug"] != "amazon" for i in browse["items"])


async def test_listing_with_unsafe_url_is_left_out(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    pid = await product_id(session, "iphone-15-128-black")
    victim = await session.scalar(select(Listing).where(Listing.product_id == pid).limit(1))
    assert victim is not None
    victim.url = "https://evil.example.com/phish"
    await session.flush()

    detail = (await client.get(f"/products/{pid}")).json()
    assert str(victim.id) not in {li["id"] for li in detail["listings"]}
    assert "evil" not in str(detail)


# --------------------------------------------------------------------------- #
# /products/{id}/price-history
# --------------------------------------------------------------------------- #
async def test_price_history(client: httpx.AsyncClient, session: AsyncSession) -> None:
    pid = await product_id(session, "iphone-15-128-black")
    response = await client.get(f"/products/{pid}/price-history", params={"days": 30})
    assert response.status_code == 200, response.text
    history = response.json()
    assert history["product_id"] == str(pid)
    assert history["days"] == 30
    assert len(history["series"]) >= 2

    cutoff = datetime.now(UTC) - timedelta(days=30, minutes=1)
    all_points = []
    for series in history["series"]:
        assert set(series["platform"]) >= FRONTEND_PLATFORM
        times = [datetime.fromisoformat(p["recorded_at"]) for p in series["points"]]
        assert times == sorted(times)
        assert all(t >= cutoff for t in times)
        all_points += series["points"]
    assert history["lowest_price"] == min(p["price"] for p in all_points)

    year = (await client.get(f"/products/{pid}/price-history", params={"days": 365})).json()
    assert sum(len(s["points"]) for s in year["series"]) > len(all_points)
    default = (await client.get(f"/products/{pid}/price-history")).json()
    assert default["days"] == 30


async def test_price_history_errors(client: httpx.AsyncClient, session: AsyncSession) -> None:
    pid = await product_id(session, "iphone-15-128-black")
    for days in ("0", "366", "x"):
        assert_error(
            await client.get(f"/products/{pid}/price-history", params={"days": days}),
            422,
            "validation_error",
        )
    assert_error(await client.get(f"/products/{uuid.uuid7()}/price-history"), 404, "not_found")


# --------------------------------------------------------------------------- #
# /categories, /platforms
# --------------------------------------------------------------------------- #
async def test_categories_and_platforms(client: httpx.AsyncClient) -> None:
    categories = await client.get("/categories")
    assert categories.status_code == 200
    assert categories.headers["cache-control"] == "public, max-age=300"
    body = categories.json()
    assert len(body) == len(CATEGORIES)
    assert all(set(c) == FRONTEND_CATEGORY for c in body)
    assert [c["name"] for c in body] == sorted(c["name"] for c in body)

    platforms = await client.get("/platforms")
    assert platforms.headers["cache-control"] == "public, max-age=300"
    assert {p["slug"] for p in platforms.json()} == set(STORES_BY_SLUG)
    assert all(set(p) == FRONTEND_PLATFORM for p in platforms.json())


# --------------------------------------------------------------------------- #
# Query counts (no N+1) and OpenAPI
# --------------------------------------------------------------------------- #
async def test_fixed_query_counts(client: httpx.AsyncClient, session: AsyncSession) -> None:
    pid = await product_id(session, "iphone-15-128-black")
    expectations = [
        (f"/products/{pid}", 2),  # product+category, listings+platforms
        (f"/products/{pid}/price-history?days=365", 3),
        ("/categories", 1),
        ("/platforms", 1),
        ("/search?page_size=50", 2),  # browse everything: products, listings
        ("/search?category=mobiles", 3),  # + category tree
        ("/deals", 2),
    ]
    for path, expected in expectations:
        with count_selects(session) as selects:
            assert (await client.get(path)).status_code == 200
        assert len(selects) == expected, (path, selects)


async def test_openapi_lists_every_catalogue_route(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    paths = set(schema["paths"])
    assert {
        "/api/v1/search",
        "/api/v1/deals",
        "/api/v1/products/{product_id}",
        "/api/v1/products/{product_id}/price-history",
        "/api/v1/categories",
        "/api/v1/platforms",
    } <= paths
    search = schema["paths"]["/api/v1/search"]["get"]
    assert {p["name"] for p in search["parameters"]} >= {
        "q", "category", "min_price", "max_price", "sort", "page", "page_size",
    }  # fmt: skip
