"""Signed-in user activity: wishlist, price alerts, search history."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.models.catalog import Product


class Wishlist(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "wishlists"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    target_price: Mapped[int | None] = mapped_column(BigInteger)  # paise

    product: Mapped[Product] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "product_id"),  # also serves "my wishlist" lookups
        CheckConstraint("target_price IS NULL OR target_price > 0", name="target_price_positive"),
    )


class PriceAlert(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "price_alerts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    target_price: Mapped[int] = mapped_column(BigInteger)  # paise
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped[Product] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "product_id"),  # one alert per product per user
        CheckConstraint("target_price > 0", name="target_price_positive"),
        # The alert worker scans active alerts by product after each price refresh.
        Index("ix_price_alerts_active_product", "product_id", postgresql_where=text("is_active")),
    )


class SearchHistory(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "search_history"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    query: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("length(query) BETWEEN 1 AND 200", name="query_length"),
        Index("ix_search_history_user_created", "user_id", text("created_at DESC")),
    )
