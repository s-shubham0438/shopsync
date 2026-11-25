"""Catalogue: stores, categories, canonical products, per-store listings and price history.

Money is always BIGINT paise (₹1 = 100). Never floats.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey


class Platform(UUIDPrimaryKey, Timestamps, Base):
    """A store we compare (Amazon, Flipkart, …)."""

    __tablename__ = "platforms"

    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    logo_url: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    listings: Mapped[list[Listing]] = relationship(back_populates="platform")

    __table_args__ = (CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="slug_format"),)


class Category(UUIDPrimaryKey, Timestamps, Base):
    """Category tree via parent_id (e.g. Electronics → Mobiles)."""

    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )

    parent: Mapped[Category | None] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list[Category]] = relationship(back_populates="parent")

    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="slug_format"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )


class Product(UUIDPrimaryKey, Timestamps, Base):
    """One real-world product; every store's listing of it points here."""

    __tablename__ = "products"

    canonical_title: Mapped[str] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(String(120))
    model_number: Mapped[str | None] = mapped_column(String(120))
    ean: Mapped[str | None] = mapped_column(String(14))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    image_url: Mapped[str | None] = mapped_column(Text)
    # Category-specific specs (storage, size, colour…), queried with @> via the GIN index.
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    category: Mapped[Category | None] = relationship()
    listings: Mapped[list[Listing]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("ean IS NULL OR ean ~ '^[0-9]{8,14}$'", name="ean_digits"),
        # A barcode identifies exactly one product: the strongest matching key.
        Index("uq_products_ean", "ean", unique=True, postgresql_where=text("ean IS NOT NULL")),
        Index("ix_products_brand_model", text("lower(brand)"), text("lower(model_number)")),
        # Fuzzy title matching / search (pg_trgm).
        Index(
            "ix_products_title_trgm",
            text("lower(canonical_title) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index(
            "ix_products_attributes",
            "attributes",
            postgresql_using="gin",
            postgresql_ops={"attributes": "jsonb_path_ops"},
        ),
    )


class Listing(UUIDPrimaryKey, Timestamps, Base):
    """A product as sold on one store, with that store's current price and offers."""

    __tablename__ = "listings"

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    platform_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platforms.id", ondelete="RESTRICT"))
    external_id: Mapped[str] = mapped_column(String(120))  # the store's own id (ASIN, FSN, …)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    affiliate_url: Mapped[str | None] = mapped_column(Text)  # generated server-side (Phase 3)
    current_price: Mapped[int] = mapped_column(BigInteger)
    mrp: Mapped[int | None] = mapped_column(BigInteger)
    # Derived from price and MRP by the database, so it can never disagree with them.
    discount_percent: Mapped[int | None] = mapped_column(
        SmallInteger,
        Computed(
            "CASE WHEN mrp > 0 AND mrp > current_price "
            "THEN ((mrp - current_price) * 100 / mrp)::smallint END",
            persisted=True,
        ),
    )
    # [{"type": "bank", "title": "10% off with HDFC", "description": "…"}]
    offers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    review_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    in_stock: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    delivery_info: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    product: Mapped[Product] = relationship(back_populates="listings")
    platform: Mapped[Platform] = relationship(back_populates="listings")
    price_history: Mapped[list[PriceHistory]] = relationship(
        back_populates="listing", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("platform_id", "external_id"),
        CheckConstraint("current_price >= 0", name="price_non_negative"),
        CheckConstraint("mrp IS NULL OR mrp >= 0", name="mrp_non_negative"),
        CheckConstraint("rating IS NULL OR rating BETWEEN 0 AND 5", name="rating_range"),
        CheckConstraint("review_count >= 0", name="review_count_non_negative"),
        CheckConstraint("jsonb_typeof(offers) = 'array'", name="offers_is_array"),
        # "All listings of a product, cheapest first" + best-deal lookup.
        Index("ix_listings_product_price", "product_id", "current_price"),
        # Refresh worker picks the stalest listings first.
        Index("ix_listings_last_checked_at", "last_checked_at"),
        Index("ix_listings_title_trgm", text("lower(title) gin_trgm_ops"), postgresql_using="gin"),
    )


class PriceHistory(UUIDPrimaryKey, CreatedAt, Base):
    """Append-only price snapshots per listing (written by the refresh worker)."""

    __tablename__ = "price_history"

    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    price: Mapped[int] = mapped_column(BigInteger)
    mrp: Mapped[int | None] = mapped_column(BigInteger)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    listing: Mapped[Listing] = relationship(back_populates="price_history")

    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("mrp IS NULL OR mrp >= 0", name="mrp_non_negative"),
        # "History for listing X over the last N days", newest first.
        Index("ix_price_history_listing_recorded", "listing_id", text("recorded_at DESC")),
    )
