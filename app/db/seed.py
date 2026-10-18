"""Seed stores, categories and a sample catalogue (with ~90 days of price history).

Idempotent: re-running updates stores/categories and skips products already seeded.

    python -m app.db.seed
"""

import asyncio
import logging
import random
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import quote_plus

from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.seed_data import CATEGORIES, DELIVERY, OFFERS, PLATFORMS, PRODUCTS, ProductSeed
from app.db.session import create_engine, create_sessionmaker
from app.models import Category, Listing, Platform, PriceHistory, Product

logger = logging.getLogger(__name__)

HISTORY_DAYS = 90
SEARCH_PATHS = {
    "amazon": "/s?k={q}",
    "flipkart": "/search?q={q}",
    "myntra": "/{q}",
    "ajio": "/search/?text={q}",
    "croma": "/searchB?q={q}",
    "tatacliq": "/search/?searchCategory=all&text={q}",
}


@dataclass(slots=True)
class SeedReport:
    platforms: int = 0
    categories: int = 0
    products_created: int = 0
    products_skipped: int = 0
    listings_created: int = 0
    history_points: int = 0


def rupees(amount: int) -> int:
    """Rupees → paise."""
    return amount * 100


def listing_external_id(product: ProductSeed, platform_slug: str) -> str:
    return f"seed-{product.key}-{platform_slug}"


def store_search_url(base_url: str, platform_slug: str, title: str) -> str:
    query = quote_plus(title.split("–")[0].strip())  # noqa: RUF001  (titles use an en dash)
    return base_url + SEARCH_PATHS.get(platform_slug, "/search?q={q}").format(q=query)


def price_series(
    seed: str, current: int, mrp: int, days: int, today: datetime
) -> list[tuple[datetime, int]]:
    """Deterministic, realistic-looking daily prices (paise) ending at today's price.

    A mean-reverting random walk that converges on the current price, with occasional sale dips,
    clamped between a floor below today's price and the MRP. Prices end in ...9 like real stores.
    """
    rng = random.Random(seed)  # noqa: S311  (demo data, not security-sensitive)
    floor, ceiling = current * 0.93, min(mrp, current * 1.22)
    price = current * (1.08 + rng.random() * 0.1)
    points: list[tuple[datetime, int]] = []
    for d in range(days, -1, -1):
        if d == 0:
            value = current
        else:
            pull = 1 / (d + 1) if d <= 10 else 0.6 / d
            price += (current - price) * pull + (rng.random() - 0.5) * current * 0.015
            if d > 10 and rng.random() < 0.025:
                price *= 0.9  # flash sale
            price = min(ceiling, max(floor, price))
            value = max(100, (round(price / 1000) * 10 - 1) * 100)  # whole rupees ending in 9
        points.append((today - timedelta(days=d), value))
    return points


async def seed_platforms(session: AsyncSession) -> dict[str, uuid.UUID]:
    insert_stmt = pg_insert(Platform).values(
        [
            {"id": uuid.uuid7(), "slug": p.slug, "name": p.name, "base_url": p.base_url}
            for p in PLATFORMS
        ]
    )
    upsert = insert_stmt.on_conflict_do_update(
        index_elements=[Platform.slug],
        set_={
            "name": insert_stmt.excluded.name,
            "base_url": insert_stmt.excluded.base_url,
            "updated_at": func.now(),
        },
    ).returning(Platform.slug, Platform.id)
    return {slug: id_ for slug, id_ in (await session.execute(upsert)).all()}


async def seed_categories(session: AsyncSession) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for c in CATEGORIES:  # parents are listed before children
        insert_stmt = pg_insert(Category).values(
            id=uuid.uuid7(), slug=c.slug, name=c.name, parent_id=ids[c.parent] if c.parent else None
        )
        upsert = insert_stmt.on_conflict_do_update(
            index_elements=[Category.slug],
            set_={
                "name": insert_stmt.excluded.name,
                "parent_id": insert_stmt.excluded.parent_id,
                "updated_at": func.now(),
            },
        ).returning(Category.id)
        ids[c.slug] = (await session.execute(upsert)).scalar_one()
    return ids


async def seed_catalogue(session: AsyncSession, report: SeedReport) -> None:
    platform_ids = await seed_platforms(session)
    category_ids = await seed_categories(session)
    report.platforms, report.categories = len(platform_ids), len(category_ids)

    existing = set(
        (
            await session.execute(
                select(Listing.external_id).where(Listing.external_id.like("seed-%"))
            )
        ).scalars()
    )
    today = datetime.combine(datetime.now(UTC).date(), time(6, 30), tzinfo=UTC)  # ~noon IST
    history_rows: list[dict[str, object]] = []

    for p in PRODUCTS:
        if any(listing_external_id(p, slug) in existing for slug in p.prices):
            report.products_skipped += 1
            continue

        product = Product(
            canonical_title=p.title,
            brand=p.brand,
            model_number=p.model,
            ean=p.ean,
            category_id=category_ids[p.category],
            attributes=dict(p.attributes),
        )
        session.add(product)
        report.products_created += 1

        for i, (slug, price) in enumerate(p.prices.items()):
            platform = next(pl for pl in PLATFORMS if pl.slug == slug)
            jitter = ((i % 3) - 1) * 0.1  # small per-store rating differences
            listing = Listing(
                product=product,
                platform_id=platform_ids[slug],
                external_id=listing_external_id(p, slug),
                title=p.title,
                url=store_search_url(platform.base_url, slug, p.title),
                current_price=rupees(price),
                mrp=rupees(p.mrp),
                offers=OFFERS[slug],
                rating=Decimal(str(round(min(5.0, max(3.5, p.rating + jitter)), 1))),
                review_count=round(p.reviews * (0.25 + ((i * 37) % 60) / 100)),
                in_stock=slug not in p.out_of_stock,
                delivery_info=DELIVERY[slug],
            )
            session.add(listing)
            await session.flush()  # assigns listing.id for the history rows
            report.listings_created += 1

            for recorded_at, value in price_series(
                listing.external_id, rupees(price), rupees(p.mrp), HISTORY_DAYS, today
            ):
                history_rows.append(
                    {
                        "listing_id": listing.id,
                        "price": value,
                        "mrp": rupees(p.mrp),
                        "recorded_at": recorded_at,
                    }
                )

    if history_rows:
        await session.execute(insert(PriceHistory), history_rows)
        report.history_points = len(history_rows)


async def run_seed(session: AsyncSession) -> SeedReport:
    report = SeedReport()
    await seed_catalogue(session, report)
    await session.commit()
    return report


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            report = await run_seed(session)
        logger.info("seed_complete", extra=asdict(report))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
