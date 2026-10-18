from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.seed import run_seed
from app.db.seed_data import PRODUCTS
from app.models import Category, Listing, Platform, PriceHistory, Product


async def count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_seed_populates_catalogue(session: AsyncSession) -> None:
    report = await run_seed(session)

    expected_listings = sum(len(p.prices) for p in PRODUCTS)
    assert report.products_created == len(PRODUCTS)
    assert report.listings_created == expected_listings
    assert await count(session, Platform) == 6
    assert await count(session, Category) == 9
    assert await count(session, Product) == len(PRODUCTS)
    assert await count(session, Listing) == expected_listings
    assert await count(session, PriceHistory) == report.history_points > 0


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    await run_seed(session)
    second = await run_seed(session)
    assert second.products_created == 0
    assert second.listings_created == 0
    assert second.products_skipped == len(PRODUCTS)
    assert await count(session, Product) == len(PRODUCTS)


async def test_seeded_history_ends_at_current_price(session: AsyncSession) -> None:
    await run_seed(session)
    latest = (
        select(PriceHistory.listing_id, func.max(PriceHistory.recorded_at).label("at"))
        .group_by(PriceHistory.listing_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(Listing.current_price, PriceHistory.price)
            .join(latest, latest.c.listing_id == Listing.id)
            .join(
                PriceHistory,
                (PriceHistory.listing_id == latest.c.listing_id)
                & (PriceHistory.recorded_at == latest.c.at),
            )
        )
    ).all()
    assert rows
    assert all(current == last for current, last in rows)


async def test_seeded_categories_form_a_tree(session: AsyncSession) -> None:
    await run_seed(session)
    mobiles = await session.scalar(select(Category).where(Category.slug == "mobiles"))
    electronics = await session.scalar(select(Category).where(Category.slug == "electronics"))
    assert mobiles is not None and electronics is not None
    assert mobiles.parent_id == electronics.id
