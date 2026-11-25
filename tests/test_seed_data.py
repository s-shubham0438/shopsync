"""Seed catalogue and generator sanity checks (no database needed)."""

from datetime import UTC, datetime

from app.db.seed import listing_external_id, price_series, rupees
from app.db.seed_data import CATEGORIES, PLATFORMS, PRODUCTS


def test_seed_references_are_valid() -> None:
    platform_slugs = {p.slug for p in PLATFORMS}
    category_slugs = {c.slug for c in CATEGORIES}
    seen_parents: set[str] = set()
    for c in CATEGORIES:
        assert c.parent is None or c.parent in seen_parents, (
            "parents must be listed before children"
        )
        seen_parents.add(c.slug)
    for p in PRODUCTS:
        assert p.category in category_slugs
        assert set(p.prices) <= platform_slugs
        assert len(p.prices) >= 2, "a comparison needs at least two stores"
        assert all(0 < price <= p.mrp for price in p.prices.values())
        assert p.out_of_stock <= set(p.prices)


def test_product_keys_and_listing_ids_are_unique() -> None:
    keys = [p.key for p in PRODUCTS]
    assert len(keys) == len(set(keys))
    ids = [listing_external_id(p, slug) for p in PRODUCTS for slug in p.prices]
    assert len(ids) == len(set(ids))


def test_price_series_is_deterministic_and_ends_today() -> None:
    today = datetime(2026, 10, 17, tzinfo=UTC)
    a = price_series("x", rupees(59_999), rupees(69_900), 90, today)
    b = price_series("x", rupees(59_999), rupees(69_900), 90, today)
    assert a == b
    assert len(a) == 91
    assert a[-1] == (today, rupees(59_999))
    assert all(
        isinstance(v, int) and 0 < v <= rupees(69_900) for _, v in a
    )  # integer paise, never above MRP
