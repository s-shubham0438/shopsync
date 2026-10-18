"""Minimal builders for test rows. Unique-ish values come from uuid7 so tests don't collide."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Listing, Platform, Product, User


def _suffix() -> str:
    return uuid.uuid7().hex[-10:]


async def make_platform(session: AsyncSession, **kw: Any) -> Platform:
    slug = kw.pop("slug", f"store-{_suffix()}")
    platform = Platform(
        slug=slug, name=kw.pop("name", slug.title()), base_url="https://example.com", **kw
    )
    session.add(platform)
    await session.flush()
    return platform


async def make_product(session: AsyncSession, **kw: Any) -> Product:
    product = Product(canonical_title=kw.pop("canonical_title", f"Test product {_suffix()}"), **kw)
    session.add(product)
    await session.flush()
    return product


async def make_listing(
    session: AsyncSession, product: Product, platform: Platform, **kw: Any
) -> Listing:
    listing = Listing(
        product_id=product.id,
        platform_id=platform.id,
        external_id=kw.pop("external_id", f"ext-{_suffix()}"),
        title=kw.pop("title", product.canonical_title),
        url=kw.pop("url", "https://example.com/p"),
        current_price=kw.pop("current_price", 99_900),
        **kw,
    )
    session.add(listing)
    await session.flush()
    return listing


async def make_user(session: AsyncSession, **kw: Any) -> User:
    if "email" not in kw and "phone" not in kw:
        kw["email"] = f"user-{_suffix()}@example.com"
    user = User(**kw)
    session.add(user)
    await session.flush()
    return user
