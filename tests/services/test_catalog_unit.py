"""CatalogService helpers without a database."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.models import Category, Listing, Platform, Product
from app.repositories.catalog import HistoryPoint
from app.services.catalog import (
    CatalogService,
    ProductNotFoundError,
    build_detail,
    parse_offers,
    scalar_attributes,
)

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)
AMAZON = Platform(
    id=uuid.uuid7(), slug="amazon", name="Amazon", base_url="https://www.amazon.in",
    logo_url=None, is_active=True,
)  # fmt: skip
FLIPKART = Platform(
    id=uuid.uuid7(), slug="flipkart", name="Flipkart", base_url="https://www.flipkart.com",
    logo_url=None, is_active=True,
)  # fmt: skip


def listing(platform: Platform, price: int, **kw: Any) -> Listing:
    defaults: dict[str, Any] = {
        "id": uuid.uuid7(),
        "platform": platform,
        "platform_id": platform.id,
        "title": "Phone",
        "url": f"{platform.base_url}/p/1",
        "current_price": price,
        "mrp": None,
        "offers": [],
        "rating": None,
        "review_count": 0,
        "in_stock": True,
        "delivery_info": None,
        "last_checked_at": NOW,
    }
    return Listing(**(defaults | kw))


def product(*listings: Listing, attributes: dict[str, Any] | None = None) -> Product:
    p = Product(
        id=uuid.uuid7(),
        canonical_title="Phone",
        brand="B",
        model_number=None,
        ean=None,
        image_url=None,
        attributes=attributes or {},
        category=Category(id=uuid.uuid7(), name="Mobiles", slug="mobiles", parent_id=None),
    )
    p.listings = list(listings)
    return p


def test_malformed_offers_are_skipped() -> None:
    li = listing(
        AMAZON,
        100,
        offers=[
            {"type": "bank", "title": "10% off"},
            {"type": "lottery", "title": "?"},
            {"title": "no type"},
            "not an object",
        ],
    )
    assert [o.title for o in parse_offers(li)] == ["10% off"]


def test_only_scalar_attributes_are_returned() -> None:
    p = product(attributes={"RAM": "8 GB", "5G": True, "Weight": 171, "x": None, "y": [1]})
    assert scalar_attributes(p) == {"RAM": "8 GB", "5G": True, "Weight": 171}


def test_best_deal_is_cheapest_in_stock_even_if_out_of_stock_is_cheaper() -> None:
    cheap_oos = listing(AMAZON, 900, in_stock=False)
    in_stock = listing(FLIPKART, 1000)
    detail = build_detail(product(cheap_oos, in_stock))
    assert detail is not None
    assert [li.id for li in detail.listings] == [in_stock.id, cheap_oos.id]
    assert detail.listings[0].is_best_deal and not detail.listings[1].is_best_deal
    assert detail.best_price == 1000


def test_price_ties_break_by_store_slug() -> None:
    detail = build_detail(product(listing(FLIPKART, 500), listing(AMAZON, 500)))
    assert detail is not None
    assert detail.listings[0].platform.slug == "amazon"


def test_no_showable_listing_means_no_detail() -> None:
    inactive = Platform(
        id=uuid.uuid7(), slug="amazon", name="Amazon", base_url="https://www.amazon.in",
        logo_url=None, is_active=False,
    )  # fmt: skip
    assert build_detail(product(listing(inactive, 100))) is None
    assert build_detail(product(listing(AMAZON, 100, url="https://evil.test/x"))) is None
    assert build_detail(product()) is None


class FakeDetailRepo:
    def __init__(self, points: list[HistoryPoint], exists: bool = True) -> None:
        self.points = points
        self.exists = exists
        self.since: datetime | None = None
        self.listing_id = uuid.uuid7()

    async def product_exists(self, product_id: uuid.UUID) -> bool:
        return self.exists

    async def active_listings(self, product_id: uuid.UUID) -> list[tuple[uuid.UUID, Platform]]:
        return [(self.listing_id, AMAZON), (uuid.uuid7(), FLIPKART)]

    async def price_points(self, ids: list[uuid.UUID], since: datetime) -> list[HistoryPoint]:
        self.since = since
        return self.points

    async def get_product_with_listings(self, product_id: uuid.UUID) -> Product | None:
        return None


async def test_history_window_series_and_earliest_lowest() -> None:
    repo = FakeDetailRepo([])
    lid = repo.listing_id
    repo.points = [
        HistoryPoint(lid, NOW - timedelta(days=3), 90, None),
        HistoryPoint(lid, NOW - timedelta(days=2), 100, None),
        HistoryPoint(lid, NOW - timedelta(days=1), 90, 120),
    ]
    service = CatalogService(repo, clock=lambda: NOW)  # type: ignore[arg-type]
    history = await service.price_history(uuid.uuid7(), 7)

    assert repo.since == NOW - timedelta(days=7)
    assert [s.platform.slug for s in history.series] == ["amazon"]  # flipkart had no points
    assert history.lowest_price == 90
    assert history.lowest_at == NOW - timedelta(days=3)


async def test_history_with_no_points_and_unknown_product() -> None:
    empty = await CatalogService(FakeDetailRepo([])).price_history(uuid.uuid7(), 30)  # type: ignore[arg-type]
    assert empty.series == [] and empty.lowest_price is None and empty.lowest_at is None
    with pytest.raises(ProductNotFoundError):
        await CatalogService(FakeDetailRepo([], exists=False)).price_history(uuid.uuid7(), 30)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="days"):
        await CatalogService(FakeDetailRepo([])).price_history(uuid.uuid7(), 366)  # type: ignore[arg-type]


async def test_missing_product_detail_is_not_found() -> None:
    with pytest.raises(ProductNotFoundError):
        await CatalogService(FakeDetailRepo([])).product_detail(uuid.uuid7())  # type: ignore[arg-type]
