"""SQLAlchemy models. Every model module is imported here so Alembic autogenerate
sees the full metadata."""

from app.models.activity import PriceAlert, SearchHistory, Wishlist
from app.models.catalog import Category, Listing, Platform, PriceHistory, Product
from app.models.user import OAuthAccount, RefreshToken, User

__all__ = [
    "Category",
    "Listing",
    "OAuthAccount",
    "Platform",
    "PriceAlert",
    "PriceHistory",
    "Product",
    "RefreshToken",
    "SearchHistory",
    "User",
    "Wishlist",
]
