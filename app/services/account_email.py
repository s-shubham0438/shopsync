"""Email verification (Milestone 5.4) and password recovery (Milestone 5.5).

Tokens: 256 random bits, single-use, short-lived, stored as SHA-256 in `auth_tokens` together
with the address they were sent to. Issuing a new token retires the older ones.

Links carry the token in the URL *fragment* (`/verify-email#token=...`): fragments are never
sent to servers, so the token can't leak through access logs, proxies or the Referer header.

Password recovery never reveals whether an email is registered: the response is identical
either way and the email is sent after the response (see the route).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ServiceUnavailableError
from app.core.security import (
    TokenError,
    hash_password_async,
    hash_token,
    new_refresh_token,
    password_problem,
)
from app.core.security_log import log_auth_event
from app.models import AuthToken, User
from app.repositories.users import UserRepository
from app.schemas.common import ErrorDetail
from app.services.auth import ClientContext, WeakPasswordError
from app.services.messaging import DeliveryUnavailableError, EmailSender, OutgoingEmail

EMAIL_VERIFY = "email_verify"
PASSWORD_RESET = "password_reset"  # noqa: S105 - a purpose label, not a password


class InvalidTokenError(AppError):
    status_code = 400
    code = "invalid_token"
    message = "This link is invalid or has expired. Please request a new one."


class EmailUnavailableError(ServiceUnavailableError):
    code = "email_unavailable"
    message = "We can't send emails right now. Please try again later."


class AccountEmailService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        sender: EmailSender,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._settings = settings
        self._sender = sender
        self._now = clock or (lambda: datetime.now(UTC))

    # ----------------------------------------------------------------------- #
    # Verification
    # ----------------------------------------------------------------------- #
    async def send_verification(self, user: User) -> bool:
        """Issue a fresh link and send it. True only if the message was handed to the
        provider; never raises for delivery problems (signup must not fail on email)."""
        if not user.email or user.is_email_verified or not self._sender.available:
            return False
        raw = await self._issue(
            user, EMAIL_VERIFY, timedelta(hours=self._settings.email_verify_ttl_hours)
        )
        link = f"{self._settings.frontend_url}/verify-email#token={raw}"
        try:
            await self._sender.send(
                OutgoingEmail(
                    to=user.email,
                    subject="Confirm your email for ShopSync",
                    text=(
                        f"Hi {user.full_name or 'there'},\n\n"
                        "Please confirm your email address for ShopSync:\n\n"
                        f"{link}\n\n"
                        f"This link expires in {self._settings.email_verify_ttl_hours} hours. "
                        "If you didn't create a ShopSync account, you can ignore this email.\n"
                    ),
                )
            )
        except DeliveryUnavailableError:
            return False
        return True

    async def resend_verification(self, user: User) -> bool:
        """For the signed-in user. Raises EmailUnavailableError if nothing could be sent."""
        if user.is_email_verified or not user.email:
            return False
        if not self._sender.available or not await self.send_verification(user):
            raise EmailUnavailableError()
        return True

    async def verify_email(self, raw_token: str, ctx: ClientContext) -> User:
        row = await self._valid_token(raw_token, EMAIL_VERIFY)
        user = await self._users.get(row.user_id)
        if user is None or not user.email or user.email.lower() != row.email.lower():
            raise InvalidTokenError()  # the account's email changed since the link was sent
        now = self._now()
        user.is_email_verified = True
        await self._users.retire_auth_tokens(user.id, EMAIL_VERIFY, now)
        await self._session.commit()
        log_auth_event("email_verified", "success", user_id=user.id, ip=ctx.ip)
        return user

    # ----------------------------------------------------------------------- #
    # Password recovery
    # ----------------------------------------------------------------------- #
    async def prepare_password_reset(self, email: str, ctx: ClientContext) -> OutgoingEmail | None:
        """Create a reset link for an existing, active account. Returns the message to send
        (by the caller, after responding) or None. The caller responds identically either way."""
        if not self._sender.available:
            raise EmailUnavailableError()  # same for every address: reveals nothing
        user = await self._users.get_by_email(email)
        if user is None or not user.is_active or not user.email:
            log_auth_event("password_reset_requested", "failure", ip=ctx.ip, reason="no_account")
            return None
        ttl = timedelta(minutes=self._settings.password_reset_ttl_minutes)
        raw = await self._issue(user, PASSWORD_RESET, ttl)
        log_auth_event("password_reset_requested", "success", user_id=user.id, ip=ctx.ip)
        return OutgoingEmail(
            to=user.email,
            subject="Reset your ShopSync password",
            text=(
                f"Hi {user.full_name or 'there'},\n\n"
                "Someone (hopefully you) asked to reset your ShopSync password:\n\n"
                f"{self._settings.frontend_url}/reset-password#token={raw}\n\n"
                f"This link expires in {self._settings.password_reset_ttl_minutes} minutes and "
                "works once. If you didn't ask for this, ignore this email: your password "
                "stays the same.\n"
            ),
        )

    async def reset_password(self, raw_token: str, new_password: str, ctx: ClientContext) -> None:
        row = await self._valid_token(raw_token, PASSWORD_RESET)
        user = await self._users.get(row.user_id)
        if (
            user is None
            or not user.is_active
            or not user.email
            or user.email.lower() != row.email.lower()
        ):
            raise InvalidTokenError()
        problem = password_problem(new_password, email=user.email)
        if problem:
            raise WeakPasswordError(
                details=[
                    ErrorDetail(loc=["body", "password"], message=problem, type="weak_password")
                ]
            )
        now = self._now()
        user.password_hash = await hash_password_async(new_password)
        user.is_email_verified = True  # following the emailed link proves inbox ownership
        await self._users.retire_auth_tokens(user.id, PASSWORD_RESET, now)
        await self._users.revoke_all_sessions(user.id, now)  # sign out every device
        await self._session.commit()
        log_auth_event("password_reset", "success", user_id=user.id, ip=ctx.ip)

    # ----------------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------------- #
    async def _issue(self, user: User, purpose: str, ttl: timedelta) -> str:
        now = self._now()
        await self._users.retire_auth_tokens(user.id, purpose, now)
        raw = new_refresh_token()  # same strength as session tokens: 256 random bits
        await self._users.add_auth_token(
            AuthToken(
                id=uuid.uuid7(),
                user_id=user.id,
                purpose=purpose,
                token_hash=hash_token(raw),
                email=user.email or "",
                expires_at=now + ttl,
            )
        )
        await self._session.commit()
        return raw

    async def _valid_token(self, raw_token: str, purpose: str) -> AuthToken:
        try:
            token_hash = hash_token(raw_token)
        except TokenError:
            raise InvalidTokenError() from None
        row = await self._users.auth_token_for_update(token_hash, purpose)
        if row is None or row.used_at is not None or row.expires_at <= self._now():
            raise InvalidTokenError()
        return row
