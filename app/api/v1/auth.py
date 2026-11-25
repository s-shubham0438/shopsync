"""Authentication endpoints: email/password (5.2), email verification (5.4), password
recovery (5.5).

Sessions live in HttpOnly cookies (see app/core/auth_http.py); response bodies never contain
tokens or password hashes. Every response is `Cache-Control: no-store`.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.api.deps import CurrentUser, DbSession, EmailSenderDep, RateLimiterDep, SettingsDep
from app.core.auth_http import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    clear_auth_cookies,
    client_ip,
    set_auth_cookies,
)
from app.core.config import Settings
from app.core.errors import error_response
from app.core.security import TokenError, decode_access_token
from app.core.security_log import log_auth_event
from app.schemas.auth import (
    EmailVerificationStatus,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    UserOut,
    VerifyEmailRequest,
)
from app.schemas.common import ErrorResponse
from app.services.account_email import AccountEmailService
from app.services.auth import AuthService, ClientContext, IssuedSession, SessionEndedError
from app.services.messaging import DeliveryUnavailableError, EmailSender, OutgoingEmail
from app.services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

NO_STORE = {"Cache-Control": "no-store"}
SIGNUP_WINDOW_SECONDS = 3600
HOUR = 3600
RESET_LINK_RESPONSE = (
    "If an account exists for that email, we've sent a link to reset the password. "
    "It expires soon, so use it right away."
)


def _no_store(response: Response) -> None:
    response.headers.update(NO_STORE)


router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(_no_store)])


def _err(code: int, description: str) -> dict[int | str, dict[str, object]]:
    return {code: {"model": ErrorResponse, "description": description}}


RATE_LIMITED = _err(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts (see Retry-After)")
UNAUTHORIZED = _err(status.HTTP_401_UNAUTHORIZED, "Not signed in or session ended")


def get_auth_service(session: DbSession, settings: SettingsDep) -> AuthService:
    return AuthService(session, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_account_email_service(
    session: DbSession, settings: SettingsDep, sender: EmailSenderDep
) -> AccountEmailService:
    return AccountEmailService(session, settings, sender)


AccountEmailServiceDep = Annotated[AccountEmailService, Depends(get_account_email_service)]


def client_context(request: Request, settings: SettingsDep) -> ClientContext:
    return ClientContext(
        ip=client_ip(request, settings), user_agent=request.headers.get("user-agent")
    )


ClientContextDep = Annotated[ClientContext, Depends(client_context)]


async def _limit(
    limiter: RateLimiter,
    ctx: ClientContext,
    bucket: str,
    identifier: str,
    *,
    limit: int,
    window: int,
) -> None:
    result = await limiter.hit(bucket, identifier, limit=limit, window=window)
    if not result.allowed:
        log_auth_event("rate_limited", "blocked", ip=ctx.ip, reason=bucket)
        result.raise_if_blocked()


def _set_session(response: Response, settings: Settings, issued: IssuedSession) -> None:
    set_auth_cookies(
        response,
        settings,
        access_token=issued.access_token,
        access_expires=issued.access_expires,
        refresh_token=issued.refresh_token,
        refresh_expires=issued.refresh_expires,
    )


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and sign in",
    responses={
        **_err(status.HTTP_409_CONFLICT, "An account with this email already exists"),
        **RATE_LIMITED,
    },
)
async def signup(
    data: SignupRequest,
    response: Response,
    settings: SettingsDep,
    service: AuthServiceDep,
    emails: AccountEmailServiceDep,
    limiter: RateLimiterDep,
    ctx: ClientContextDep,
) -> SignupResponse:
    await _limit(
        limiter,
        ctx,
        "signup:ip",
        ctx.ip or "unknown",
        limit=settings.auth_signup_limit_per_hour,
        window=SIGNUP_WINDOW_SECONDS,
    )
    user, issued = await service.signup(data, ctx)
    _set_session(response, settings, issued)
    sent = await emails.send_verification(user)
    return SignupResponse(**UserOut.model_validate(user).model_dump(), verification_email_sent=sent)


@router.post(
    "/login",
    response_model=UserOut,
    summary="Sign in with email and password",
    responses={**_err(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password"), **RATE_LIMITED},
)
async def login(
    data: LoginRequest,
    response: Response,
    settings: SettingsDep,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ctx: ClientContextDep,
) -> UserOut:
    window = settings.auth_rate_limit_window_seconds
    await _limit(
        limiter, ctx, "login:ip", ctx.ip or "unknown",
        limit=settings.auth_rate_limit_per_ip, window=window,
    )  # fmt: skip
    await _limit(
        limiter, ctx, "login:account", data.email,
        limit=settings.auth_rate_limit_per_account, window=window,
    )  # fmt: skip
    user, issued = await service.login(data, ctx)
    _set_session(response, settings, issued)
    return UserOut.model_validate(user)


@router.post(
    "/refresh",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Rotate the session cookies",
    description="Uses the refresh cookie. On failure the cookies are cleared and the user must "
    "log in again.",
    responses={**UNAUTHORIZED, **RATE_LIMITED},
)
async def refresh(
    request: Request,
    settings: SettingsDep,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    ctx: ClientContextDep,
) -> Response:
    await _limit(
        limiter, ctx, "refresh:ip", ctx.ip or "unknown",
        limit=settings.auth_refresh_limit_per_ip, window=settings.auth_rate_limit_window_seconds,
    )  # fmt: skip
    try:
        issued = await service.refresh(request.cookies.get(REFRESH_COOKIE), ctx)
    except SessionEndedError as exc:
        failed = error_response(exc.status_code, exc.code, exc.message, headers=NO_STORE)
        clear_auth_cookies(failed, settings)
        return failed
    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers=NO_STORE)
    _set_session(response, settings, issued)
    return response


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out of this session",
    description="Ends the current session and clears the cookies. Always succeeds.",
)
async def logout(
    request: Request, settings: SettingsDep, service: AuthServiceDep, ctx: ClientContextDep
) -> Response:
    session_id = None
    access = request.cookies.get(ACCESS_COOKIE)
    if access:
        try:
            session_id = decode_access_token(access, settings).session_id
        except TokenError:
            session_id = None
    await service.logout(request.cookies.get(REFRESH_COOKIE), session_id, ctx)
    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers=NO_STORE)
    clear_auth_cookies(response, settings)
    return response


@router.get("/me", response_model=UserOut, summary="The signed-in user", responses=UNAUTHORIZED)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


# --------------------------------------------------------------------------- #
# Email verification (5.4)
# --------------------------------------------------------------------------- #
@router.post(
    "/email/verify",
    response_model=UserOut,
    summary="Confirm an email address with the emailed token",
    responses={**_err(status.HTTP_400_BAD_REQUEST, "Invalid or expired link"), **RATE_LIMITED},
)
async def verify_email(
    data: VerifyEmailRequest,
    settings: SettingsDep,
    emails: AccountEmailServiceDep,
    limiter: RateLimiterDep,
    ctx: ClientContextDep,
) -> UserOut:
    await _limit(
        limiter, ctx, "email_verify:ip", ctx.ip or "unknown",
        limit=settings.auth_rate_limit_per_ip, window=settings.auth_rate_limit_window_seconds,
    )  # fmt: skip
    return UserOut.model_validate(await emails.verify_email(data.token, ctx))


@router.post(
    "/email/resend",
    response_model=EmailVerificationStatus,
    summary="Send a new verification link to the signed-in user",
    responses={
        **UNAUTHORIZED,
        **RATE_LIMITED,
        **_err(status.HTTP_503_SERVICE_UNAVAILABLE, "Email can't be sent right now"),
    },
)
async def resend_verification(
    user: CurrentUser,
    emails: AccountEmailServiceDep,
    limiter: RateLimiterDep,
    ctx: ClientContextDep,
) -> EmailVerificationStatus:
    if user.is_email_verified:
        return EmailVerificationStatus(sent=False, already_verified=True)
    await _limit(limiter, ctx, "email_resend:user", str(user.id), limit=3, window=HOUR)
    sent = await emails.resend_verification(user)
    return EmailVerificationStatus(sent=sent, already_verified=False)


# --------------------------------------------------------------------------- #
# Password recovery (5.5)
# --------------------------------------------------------------------------- #
async def _send_quietly(sender: EmailSender, message: OutgoingEmail) -> None:
    try:
        await sender.send(message)
    except DeliveryUnavailableError:
        logger.warning("password_reset_email_not_sent")


@router.post(
    "/password/forgot",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a password-reset link",
    description="Always answers the same way, whether or not the email is registered.",
    responses={
        **RATE_LIMITED,
        **_err(status.HTTP_503_SERVICE_UNAVAILABLE, "Email can't be sent right now"),
    },
)
async def forgot_password(
    data: ForgotPasswordRequest,
    background: BackgroundTasks,
    settings: SettingsDep,
    emails: AccountEmailServiceDep,
    sender: EmailSenderDep,
    limiter: RateLimiterDep,
    ctx: ClientContextDep,
) -> MessageResponse:
    window = settings.auth_rate_limit_window_seconds
    await _limit(limiter, ctx, "forgot:ip", ctx.ip or "unknown", limit=5, window=window)
    await _limit(limiter, ctx, "forgot:account", data.email, limit=3, window=HOUR)
    message = await emails.prepare_password_reset(data.email, ctx)
    if message is not None:
        # Sent after the response, so response time doesn't reveal whether the account exists.
        background.add_task(_send_quietly, sender, message)
    return MessageResponse(message=RESET_LINK_RESPONSE)


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password with the emailed token",
    description="Signs out every device; the user then logs in with the new password.",
    responses={**_err(status.HTTP_400_BAD_REQUEST, "Invalid or expired link"), **RATE_LIMITED},
)
async def reset_password(
    data: ResetPasswordRequest,
    settings: SettingsDep,
    emails: AccountEmailServiceDep,
    limiter: RateLimiterDep,
    ctx: ClientContextDep,
) -> Response:
    await _limit(
        limiter, ctx, "reset:ip", ctx.ip or "unknown",
        limit=10, window=settings.auth_rate_limit_window_seconds,
    )  # fmt: skip
    await emails.reset_password(data.token, data.password, ctx)
    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers=NO_STORE)
    clear_auth_cookies(response, settings)
    return response
