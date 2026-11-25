"""Users and refresh tokens. Each method is a fixed number of queries."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthToken, OAuthAccount, RefreshToken, User


class DuplicateEmailError(Exception):
    pass


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Case-insensitive, using the unique index on lower(email)."""
        return await self._session.scalar(
            select(User).where(func.lower(User.email) == email.lower())
        )

    async def get_by_phone(self, phone: str) -> User | None:
        return await self._session.scalar(select(User).where(User.phone == phone))

    async def create(
        self,
        *,
        email: str | None,
        password_hash: str | None,
        full_name: str | None,
        phone: str | None = None,
        is_email_verified: bool = False,
        is_phone_verified: bool = False,
    ) -> User:
        """Insert a user. Raises DuplicateEmailError if the email/phone is taken (also under a
        race: the unique indexes are the final authority)."""
        user = User(
            email=email,
            phone=phone,
            password_hash=password_hash,
            full_name=full_name,
            is_email_verified=is_email_verified,
            is_phone_verified=is_phone_verified,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(user)
                await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateEmailError from exc
        return user

    # ----------------------------------------------------------------------- #
    # Refresh tokens
    # ----------------------------------------------------------------------- #
    async def add_refresh_token(self, token: RefreshToken) -> None:
        self._session.add(token)
        await self._session.flush()

    async def refresh_token_for_update(self, token_hash: str) -> RefreshToken | None:
        """Lock the row so two concurrent refreshes with the same token serialise."""
        return await self._session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )

    async def revoke_family(self, family_id: uuid.UUID, now: datetime) -> int:
        result = await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def active_families(self, user_id: uuid.UUID, now: datetime) -> list[uuid.UUID]:
        """The user's live sessions (families with an unrevoked, unexpired token), oldest first."""
        rows = await self._session.execute(
            select(RefreshToken.family_id)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .group_by(RefreshToken.family_id)
            .order_by(func.min(RefreshToken.created_at), RefreshToken.family_id)
        )
        return list(rows.scalars())

    async def revoke_families(self, family_ids: list[uuid.UUID], now: datetime) -> None:
        if not family_ids:
            return
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id.in_(family_ids), RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def revoke_all_sessions(self, user_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def session_active(self, family_id: uuid.UUID, now: datetime) -> bool:
        """True while the session (refresh-token family) has an unrevoked, unexpired token."""
        found = await self._session.scalar(
            select(RefreshToken.id)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .limit(1)
        )
        return found is not None

    # ----------------------------------------------------------------------- #
    # Emailed single-use tokens
    # ----------------------------------------------------------------------- #
    async def add_auth_token(self, token: AuthToken) -> None:
        self._session.add(token)
        await self._session.flush()

    async def auth_token_for_update(self, token_hash: str, purpose: str) -> AuthToken | None:
        return await self._session.scalar(
            select(AuthToken)
            .where(AuthToken.token_hash == token_hash, AuthToken.purpose == purpose)
            .with_for_update()
        )

    async def retire_auth_tokens(self, user_id: uuid.UUID, purpose: str, now: datetime) -> None:
        """Mark every unused token of this purpose as used (only the newest link should work)."""
        await self._session.execute(
            update(AuthToken)
            .where(
                AuthToken.user_id == user_id,
                AuthToken.purpose == purpose,
                AuthToken.used_at.is_(None),
            )
            .values(used_at=now)
        )

    # ----------------------------------------------------------------------- #
    # OAuth identities
    # ----------------------------------------------------------------------- #
    async def get_by_oauth(self, provider: str, provider_user_id: str) -> User | None:
        return await self._session.scalar(
            select(User)
            .join(OAuthAccount, OAuthAccount.user_id == User.id)
            .where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_user_id == provider_user_id,
            )
        )

    async def link_oauth(
        self, user: User, provider: str, provider_user_id: str, email: str | None
    ) -> None:
        self._session.add(
            OAuthAccount(
                user_id=user.id,
                provider=provider,
                provider_user_id=provider_user_id,
                email=email,
            )
        )
        await self._session.flush()
