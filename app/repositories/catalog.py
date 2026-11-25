"""Read-only catalogue queries. Every method runs a fixed number of queries (no N+1)."""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models import Category, Listing, Platform, PriceHistory, Product


@dataclass(frozen=True, slots=True)
class HistoryPoint:
    listing_id: uuid.UUID
    recorded_at: datetime
    price: int
    mrp: int | None


@dataclass(frozen=True, slots=True)
class ResolvedListing:
    """Where a store's (platform slug, external id) lives in ShopSync's database."""

    listing_id: uuid.UUID
    product_id: uuid.UUID
    platform: Platform


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_listings(
        self, keys: Collection[tuple[str, str]]
    ) -> dict[tuple[str, str], ResolvedListing]:
        """Map (platform_slug, external_id) pairs to existing listings, in one query.

        Uses the unique (platform_id, external_id) index. Pairs with no listing are absent.
        """
        if not keys:
            return {}
        rows = await self._session.execute(
            select(Platform, Listing.external_id, Listing.id, Listing.product_id)
            .join(Listing, Listing.platform_id == Platform.id)
            .where(tuple_(Platform.slug, Listing.external_id).in_(list(keys)))
        )
        return {
            (platform.slug, external_id): ResolvedListing(listing_id, product_id, platform)
            for platform, external_id, listing_id, product_id in rows.all()
        }

    async def get_products(self, ids: Collection[uuid.UUID]) -> dict[uuid.UUID, Product]:
        """Products (with their category) by id, in one query."""
        if not ids:
            return {}
        rows = await self._session.scalars(
            select(Product).options(joinedload(Product.category)).where(Product.id.in_(list(ids)))
        )
        return {p.id: p for p in rows.unique()}

    async def category_with_descendants(self, slug: str) -> set[uuid.UUID] | None:
        """Ids of the category `slug` and every category below it; None if `slug` doesn't exist.

        The category table is tiny, so one query loads it and the tree is walked in memory.
        """
        rows = (
            await self._session.execute(select(Category.id, Category.slug, Category.parent_id))
        ).all()
        root = next((cid for cid, cslug, _ in rows if cslug == slug), None)
        if root is None:
            return None
        children: dict[uuid.UUID, list[uuid.UUID]] = {}
        for cid, _, parent in rows:
            if parent is not None:
                children.setdefault(parent, []).append(cid)
        found: set[uuid.UUID] = set()
        stack = [root]
        while stack:  # iterative walk; `found` also guards against accidental cycles
            current = stack.pop()
            if current in found:
                continue
            found.add(current)
            stack.extend(children.get(current, []))
        return found

    async def browse_products(self, category_ids: set[uuid.UUID] | None) -> list[Product]:
        """Products (optionally limited to categories) with category, listings and each
        listing's platform: 2 queries (products+category, then all their listings+platforms).

        Loads the whole selection; fine for the curated catalogue (see tech-debt B1).
        """
        stmt = select(Product).options(
            joinedload(Product.category),
            selectinload(Product.listings).joinedload(Listing.platform),
        )
        if category_ids is not None:
            stmt = stmt.where(Product.category_id.in_(list(category_ids)))
        return list((await self._session.scalars(stmt)).unique())

    async def get_product_with_listings(self, product_id: uuid.UUID) -> Product | None:
        """One product with category, listings and platforms (2 queries), or None."""
        rows = await self._session.scalars(
            select(Product)
            .options(
                joinedload(Product.category),
                selectinload(Product.listings).joinedload(Listing.platform),
            )
            .where(Product.id == product_id)
        )
        return rows.unique().one_or_none()

    async def product_exists(self, product_id: uuid.UUID) -> bool:
        found = await self._session.scalar(select(Product.id).where(Product.id == product_id))
        return found is not None

    async def active_listings(self, product_id: uuid.UUID) -> list[tuple[uuid.UUID, Platform]]:
        """(listing id, platform) for the product's listings on active platforms (1 query)."""
        rows = await self._session.execute(
            select(Listing.id, Platform)
            .join(Platform, Listing.platform_id == Platform.id)
            .where(Listing.product_id == product_id, Platform.is_active.is_(True))
            .order_by(Platform.name, Listing.id)
        )
        return [(listing_id, platform) for listing_id, platform in rows.all()]

    async def price_points(
        self, listing_ids: Collection[uuid.UUID], since: datetime
    ) -> list[HistoryPoint]:
        """Price history of these listings recorded at or after `since`, oldest first
        (1 query on the (listing_id, recorded_at) index)."""
        if not listing_ids:
            return []
        rows = await self._session.execute(
            select(
                PriceHistory.listing_id,
                PriceHistory.recorded_at,
                PriceHistory.price,
                PriceHistory.mrp,
            )
            .where(
                PriceHistory.listing_id.in_(list(listing_ids)),
                PriceHistory.recorded_at >= since,
            )
            .order_by(PriceHistory.listing_id, PriceHistory.recorded_at, PriceHistory.id)
        )
        return [HistoryPoint(*row) for row in rows.all()]

    async def list_categories(self) -> list[Category]:
        rows = await self._session.scalars(select(Category).order_by(Category.name, Category.slug))
        return list(rows)

    async def list_active_platforms(self) -> list[Platform]:
        rows = await self._session.scalars(
            select(Platform).where(Platform.is_active.is_(True)).order_by(Platform.name)
        )
        return list(rows)
