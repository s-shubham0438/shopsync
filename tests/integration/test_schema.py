"""Database-level guarantees: constraints, generated columns, cascades, indexes."""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, PriceAlert, PriceHistory, Product, User, Wishlist
from tests.integration.factories import make_listing, make_platform, make_product, make_user


async def expect_integrity_error(session: AsyncSession, *objs: object) -> None:
    """Flush inside a SAVEPOINT so the failure doesn't poison the rest of the test."""
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add_all(objs)
            await session.flush()


async def test_pg_trgm_extension_installed(session: AsyncSession) -> None:
    installed = await session.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"))
    assert installed == 1


async def test_ids_are_uuidv7(session: AsyncSession) -> None:
    a = await make_product(session)
    b = await make_product(session)
    assert a.id.version == 7
    assert a.id < b.id  # time-ordered


async def test_discount_percent_is_computed_by_database(session: AsyncSession) -> None:
    listing = await make_listing(
        session,
        await make_product(session),
        await make_platform(session),
        current_price=75_000,
        mrp=100_000,
    )
    await session.refresh(listing)
    assert listing.discount_percent == 25

    listing.current_price = 100_000  # no discount when price == MRP
    await session.flush()
    await session.refresh(listing)
    assert listing.discount_percent is None


async def test_listing_unique_per_platform_and_external_id(session: AsyncSession) -> None:
    platform, product = await make_platform(session), await make_product(session)
    await make_listing(session, product, platform, external_id="B0SAME")
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await make_listing(session, product, platform, external_id="B0SAME")
    # Same external id on a different store is fine.
    await make_listing(session, product, await make_platform(session), external_id="B0SAME")


async def test_negative_money_rejected(session: AsyncSession) -> None:
    platform, product = await make_platform(session), await make_product(session)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await make_listing(session, product, platform, current_price=-1)


async def test_rating_must_be_between_0_and_5(session: AsyncSession) -> None:
    platform, product = await make_platform(session), await make_product(session)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await make_listing(session, product, platform, rating=5.5)


async def test_ean_is_unique_and_numeric(session: AsyncSession) -> None:
    await make_product(session, ean="8901234567890")
    await expect_integrity_error(session, Product(canonical_title="dup", ean="8901234567890"))
    await expect_integrity_error(session, Product(canonical_title="bad", ean="ABC123"))
    # Many products may have no EAN.
    await make_product(session)
    await make_product(session)


async def test_user_needs_email_or_phone(session: AsyncSession) -> None:
    await expect_integrity_error(session, User(full_name="Nobody"))
    await make_user(session, phone="+919876543210")


async def test_email_unique_case_insensitive(session: AsyncSession) -> None:
    await make_user(session, email="Priya@Example.com")
    await expect_integrity_error(session, User(email="priya@example.com"))


async def test_phone_must_be_e164(session: AsyncSession) -> None:
    await expect_integrity_error(session, User(phone="9876543210"))


async def test_category_cannot_be_its_own_parent(session: AsyncSession) -> None:
    category = Category(name="Loop", slug=f"loop-{uuid.uuid7().hex[-8:]}")
    session.add(category)
    await session.flush()
    category.parent_id = category.id
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.flush()


async def test_one_wishlist_entry_and_alert_per_product(session: AsyncSession) -> None:
    user, product = await make_user(session), await make_product(session)
    session.add(Wishlist(user_id=user.id, product_id=product.id))
    session.add(PriceAlert(user_id=user.id, product_id=product.id, target_price=50_000))
    await session.flush()
    await expect_integrity_error(session, Wishlist(user_id=user.id, product_id=product.id))
    await expect_integrity_error(
        session, PriceAlert(user_id=user.id, product_id=product.id, target_price=40_000)
    )


async def test_deleting_user_cascades_to_their_data(session: AsyncSession) -> None:
    user, product = await make_user(session), await make_product(session)
    session.add(Wishlist(user_id=user.id, product_id=product.id))
    await session.flush()
    await session.delete(user)
    await session.flush()
    remaining = await session.scalar(
        select(func.count()).select_from(Wishlist).where(Wishlist.user_id == user.id)
    )
    assert remaining == 0


async def test_deleting_product_cascades_to_listings_and_history(session: AsyncSession) -> None:
    product = await make_product(session)
    listing = await make_listing(session, product, await make_platform(session))
    session.add(PriceHistory(listing_id=listing.id, price=99_900))
    await session.flush()
    await session.delete(product)
    await session.flush()
    left = await session.scalar(
        select(func.count()).select_from(PriceHistory).where(PriceHistory.listing_id == listing.id)
    )
    assert left == 0


async def test_trigram_similarity_finds_typos(session: AsyncSession) -> None:
    await make_product(session, canonical_title="Sony WH-1000XM5 Wireless Headphones")
    title = await session.scalar(
        select(Product.canonical_title)
        .where(func.lower(Product.canonical_title).op("%")("sony wh1000xm5 headphnes"))
        .order_by(
            func.similarity(func.lower(Product.canonical_title), "sony wh1000xm5 headphnes").desc()
        )
        .limit(1)
    )
    assert title == "Sony WH-1000XM5 Wireless Headphones"
