"""Email/password accounts and sessions (Milestone 5.2).

A *session* is a refresh-token family: login/signup starts one, every refresh rotates the token
inside it, logout revokes it. Only token hashes are stored.

Refresh rotation:
- The presented token's row is locked (SELECT ... FOR UPDATE), so two parallel refreshes with the
  same token can't both succeed.
- A token that was already rotated and is presented again more than
  `REFRESH_REUSE_GRACE_SECONDS` later means it was copied: the whole family is revoked
  (the thief and the user are both signed out) and a security event is logged.
- Within the grace window it is treated as a harmless race between two tabs: plain 401.

Errors never reveal which part of a login was wrong.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, UnauthorizedError
from app.core.security import (
    TokenError,
    create_access_token,
    hash_password_async,
    hash_token,
    new_refresh_token,
    password_needs_rehash,
    password_problem,
    verify_password_async,
)
from app.core.security_log import log_auth_event
from app.models import RefreshToken, User
from app.repositories.users import DuplicateEmailError, UserRepository
from app.schemas.auth import LoginRequest, SignupRequest
from app.schemas.common import ErrorDetail

DUPLICATE_EMAIL_MESSAGE = "An account with this email already exists. Please log in."
BAD_LOGIN_MESSAGE = "Incorrect email or password."
SESSION_ENDED_MESSAGE = "Your session has ended. Please log in again."
_MAX_USER_AGENT = 512


class EmailTakenError(ConflictError):
    code = "email_taken"
    message = DUPLICATE_EMAIL_MESSAGE


class WeakPasswordError(AppError):
    status_code = 422
    code = "validation_error"
    message = "Request validation failed."


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"
    message = BAD_LOGIN_MESSAGE


class SessionEndedError(UnauthorizedError):
    """Refresh failed: the caller must clear cookies and log in again."""

    message = SESSION_ENDED_MESSAGE


@dataclass(frozen=True, slots=True)
class ClientContext:
    ip: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    access_token: str
    access_expires: datetime
    refresh_token: str
    refresh_expires: datetime
    family_id: uuid.UUID


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._settings = settings
        self._now = clock or (lambda: datetime.now(UTC))

    # ----------------------------------------------------------------------- #
    # Signup / login
    # ----------------------------------------------------------------------- #
    async def signup(self, data: SignupRequest, ctx: ClientContext) -> tuple[User, IssuedSession]:
        problem = password_problem(data.password, email=data.email)
        if problem:
            raise WeakPasswordError(
                details=[
                    ErrorDetail(loc=["body", "password"], message=problem, type="weak_password")
                ]
            )
        if await self._users.get_by_email(data.email) is not None:
            log_auth_event("signup", "failure", ip=ctx.ip, reason="email_taken")
            raise EmailTakenError()
        password_hash = await hash_password_async(data.password)
        try:
            user = await self._users.create(
                email=data.email, password_hash=password_hash, full_name=data.full_name
            )
        except DuplicateEmailError:  # lost a race with an identical signup
            log_auth_event("signup", "failure", ip=ctx.ip, reason="email_taken")
            raise EmailTakenError() from None
        user.last_login_at = self._now()
        issued = await self._start_session(user, ctx)
        await self._session.commit()
        log_auth_event("signup", "success", user_id=user.id, ip=ctx.ip)
        return user, issued

    async def login(self, data: LoginRequest, ctx: ClientContext) -> tuple[User, IssuedSession]:
        user = await self._users.get_by_email(data.email)
        # Always one full Argon2 verification, whether or not the account exists, so the
        # response time doesn't reveal registered emails.
        ok = await verify_password_async(user.password_hash if user else None, data.password)
        if user is None or user.password_hash is None or not ok or not user.is_active:
            reason = "unknown_email" if user is None else ("bad_password" if not ok else "inactive")
            log_auth_event(
                "login", "failure", user_id=user.id if user else None, ip=ctx.ip, reason=reason
            )
            raise InvalidCredentialsError()

        if password_needs_rehash(user.password_hash):
            user.password_hash = await hash_password_async(data.password)
        user.last_login_at = self._now()
        issued = await self._start_session(user, ctx)
        await self._session.commit()
        log_auth_event("login", "success", user_id=user.id, ip=ctx.ip)
        return user, issued

    # ----------------------------------------------------------------------- #
    # Refresh / logout
    # ----------------------------------------------------------------------- #
    async def refresh(self, raw_token: str | None, ctx: ClientContext) -> IssuedSession:
        now = self._now()
        if not raw_token:
            # An anonymous visitor's app checking for a session: normal, not a security event.
            raise SessionEndedError()
        try:
            token_hash = hash_token(raw_token)
        except TokenError:
            log_auth_event("refresh", "failure", ip=ctx.ip, reason="malformed")
            raise SessionEndedError() from None

        row = await self._users.refresh_token_for_update(token_hash)
        if row is None:
            log_auth_event("refresh", "failure", ip=ctx.ip, reason="unknown_token")
            raise SessionEndedError()

        if row.revoked_at is not None:
            await self._handle_revoked(row, row.revoked_at, now, ctx)  # always raises

        user = await self._users.get(row.user_id)
        if row.expires_at <= now or user is None or not user.is_active:
            reason = "expired" if row.expires_at <= now else "user_inactive"
            await self._users.revoke_family(row.family_id, now)
            await self._session.commit()
            log_auth_event("refresh", "failure", user_id=row.user_id, ip=ctx.ip, reason=reason)
            raise SessionEndedError()

        issued, new_row = await self._issue(user, ctx, family_id=row.family_id, now=now)
        row.revoked_at = now
        row.replaced_by_id = new_row.id
        await self._session.commit()
        log_auth_event("refresh", "success", user_id=user.id, ip=ctx.ip)
        return issued

    async def logout(
        self, raw_refresh: str | None, session_id: uuid.UUID | None, ctx: ClientContext
    ) -> None:
        """End the current session. Idempotent; never fails for missing/stale credentials."""
        now = self._now()
        family_id = session_id
        user_id: uuid.UUID | None = None
        if raw_refresh:
            try:
                row = await self._users.refresh_token_for_update(hash_token(raw_refresh))
            except TokenError:
                row = None
            if row is not None:
                family_id, user_id = row.family_id, row.user_id
        if family_id is not None:
            await self._users.revoke_family(family_id, now)
            await self._session.commit()
        log_auth_event("logout", "success", user_id=user_id, ip=ctx.ip)

    # ----------------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------------- #
    async def _handle_revoked(
        self, row: RefreshToken, revoked_at: datetime, now: datetime, ctx: ClientContext
    ) -> None:
        grace = timedelta(seconds=self._settings.refresh_reuse_grace_seconds)
        if row.replaced_by_id is not None and now - revoked_at > grace:
            # A rotated token came back long after rotation: it was copied. End the session
            # for everyone holding any token of this family.
            revoked = await self._users.revoke_family(row.family_id, now)
            await self._session.commit()
            log_auth_event(
                "refresh_token_reuse",
                "blocked",
                user_id=row.user_id,
                ip=ctx.ip,
                reason=f"family_revoked:{revoked}",
            )
        else:
            # Nothing changed; the request's session rolls back (and releases the row lock)
            # when it closes. No explicit rollback here: it would expire `row`.
            reason = "rotated_recently" if row.replaced_by_id else "revoked"
            log_auth_event("refresh", "failure", user_id=row.user_id, ip=ctx.ip, reason=reason)
        raise SessionEndedError()

    async def _start_session(self, user: User, ctx: ClientContext) -> IssuedSession:
        now = self._now()
        # Enforce the session cap: keep the newest (max - 1), then add this one.
        families = await self._users.active_families(user.id, now)
        excess = len(families) - (self._settings.auth_max_sessions - 1)
        if excess > 0:
            await self._users.revoke_families(families[:excess], now)
        issued, _ = await self._issue(user, ctx, family_id=uuid.uuid7(), now=now)
        return issued

    async def _issue(
        self, user: User, ctx: ClientContext, *, family_id: uuid.UUID, now: datetime
    ) -> tuple[IssuedSession, RefreshToken]:
        refresh = new_refresh_token()
        refresh_expires = now + timedelta(days=self._settings.refresh_token_ttl_days)
        row = RefreshToken(
            id=uuid.uuid7(),
            user_id=user.id,
            token_hash=hash_token(refresh),
            family_id=family_id,
            expires_at=refresh_expires,
            user_agent=ctx.user_agent[:_MAX_USER_AGENT] if ctx.user_agent else None,
            ip=ctx.ip,
        )
        await self._users.add_refresh_token(row)
        access, access_expires = create_access_token(
            user.id, self._settings, session_id=family_id, now=now
        )
        return (
            IssuedSession(access, access_expires, refresh, refresh_expires, family_id),
            row,
        )
