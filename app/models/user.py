"""Accounts and sessions."""

import uuid
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey


class User(UUIDPrimaryKey, Timestamps, Base):
    """A person can sign up with email, phone, Google, or any mix of them."""

    __tablename__ = "users"

    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(16))  # E.164, e.g. +919876543210
    password_hash: Mapped[str | None] = mapped_column(
        Text
    )  # Argon2; NULL for OTP/Google-only users
    full_name: Mapped[str | None] = mapped_column(String(200))
    is_email_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="has_contact"),
        CheckConstraint("phone IS NULL OR phone ~ '^\\+[1-9][0-9]{7,14}$'", name="phone_e164"),
        # Case-insensitive uniqueness: Foo@x.com and foo@x.com are the same account.
        Index(
            "uq_users_email_lower",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index("uq_users_phone", "phone", unique=True, postgresql_where=text("phone IS NOT NULL")),
    )


class OAuthAccount(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "oauth_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(30))  # "google"
    provider_user_id: Mapped[str] = mapped_column(String(255))  # Google "sub"
    email: Mapped[str | None] = mapped_column(String(320))  # as reported by the provider

    user: Mapped[User] = relationship(back_populates="oauth_accounts")

    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)


class RefreshToken(UUIDPrimaryKey, CreatedAt, Base):
    """Only a SHA-256 hash of the token is stored, so a DB leak can't be replayed as sessions.

    Rotation: using a token revokes it and issues a new one in the same family_id. If a revoked
    token is presented again (stolen + reused), the whole family is revoked.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # hex SHA-256
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    __table_args__ = (CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_hex"),)
