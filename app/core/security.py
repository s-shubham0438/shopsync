"""Passwords, access tokens and refresh tokens.

Passwords
    Argon2id (argon2-cffi defaults: RFC 9106 low-memory profile, 64 MiB, 3 passes, 4 lanes).
    Hashing is CPU/memory heavy (~50 ms), so the async helpers run it in a worker thread and
    never block the event loop. `verify_password(None, ...)` still does a full verification
    against a dummy hash, so "no such account" and "wrong password" take the same time.

Access tokens
    Short-lived JWTs (HS256, `AUTH_SECRET_KEY`). Decoding accepts HS256 only (no `none`, no
    algorithm confusion) and requires sub/iss/aud/iat/exp/jti plus `typ=access`. `sid` carries
    the refresh-token family so sessions can be revoked server-side later.

Refresh tokens
    256 random bits, opaque. Only their SHA-256 is stored (`refresh_tokens.token_hash`).
"""

import asyncio
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a claim value, not a secret
JWT_ALGORITHM = "HS256"
_CLOCK_SKEW = timedelta(seconds=10)

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
REFRESH_TOKEN_BYTES = 32
_MAX_REFRESH_TOKEN_CHARS = 128

_hasher = PasswordHasher()

# Short list of the most common passwords that pass the length rule. A full breached-password
# check (e.g. k-anonymity lookup) is a later hardening option (tech-debt P1).
_COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password12", "password123", "password@123", "passw0rd",
        "12345678", "123456789", "1234567890", "0123456789", "87654321", "11111111",
        "00000000", "12341234", "qwertyuiop", "qwerty123", "qwerty12", "1q2w3e4r",
        "1qaz2wsx", "asdfghjkl", "iloveyou", "sunshine", "princess", "football",
        "baseball", "welcome1", "welcome123", "admin123", "letmein1", "trustno1",
        "abcd1234", "abc12345", "monkey123", "dragon123", "superman", "india123",
        "india@123", "shopsync", "shopsync123", "changeme", "computer", "internet",
    }
)  # fmt: skip


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def password_problem(password: str, *, email: str | None = None) -> str | None:
    """Why `password` is unacceptable (a user-facing sentence), or None.

    NIST SP 800-63B style: length and a blocklist, no composition rules.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Password must be at most {PASSWORD_MAX_LENGTH} characters."
    if not password.strip():
        return "Password cannot be only spaces."
    lowered = password.casefold()
    if lowered in _COMMON_PASSWORDS or len(set(lowered)) <= 2:
        return "This password is too common. Please choose a less guessable one."
    if email and lowered == email.split("@", 1)[0].casefold():
        return "Password must not be the same as your email name."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def verify_password(password_hash: str | None, password: str) -> bool:
    """True only for a correct password. Never raises for bad or missing hashes."""
    try:
        return _hasher.verify(password_hash or _dummy_hash(), password) and bool(password_hash)
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses weaker parameters than the current defaults."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


async def warm_up() -> None:
    """Build the dummy hash at startup, so the first login for an unknown email isn't slower
    than a wrong-password login (which would hint that the account doesn't exist)."""
    await asyncio.to_thread(_dummy_hash)


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str | None, password: str) -> bool:
    return await asyncio.to_thread(verify_password, password_hash, password)


# --------------------------------------------------------------------------- #
# Access tokens
# --------------------------------------------------------------------------- #
class TokenError(Exception):
    """The token is missing, malformed, tampered with, expired or not for us."""


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    jti: str
    issued_at: datetime
    expires_at: datetime


def create_access_token(
    user_id: uuid.UUID,
    settings: Settings,
    *,
    session_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Return (token, expiry)."""
    issued = (now or datetime.now(UTC)).replace(microsecond=0)
    expires = issued + timedelta(seconds=settings.access_token_ttl_seconds)
    claims: dict[str, object] = {
        "sub": str(user_id),
        "typ": ACCESS_TOKEN_TYPE,
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
        "iat": issued,
        "exp": expires,
        "jti": secrets.token_urlsafe(16),
    }
    if session_id is not None:
        claims["sid"] = str(session_id)
    token = jwt.encode(claims, settings.auth_signing_key, algorithm=JWT_ALGORITHM)
    return token, expires


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    if not token or len(token) > 4096:
        raise TokenError("bad token length")
    try:
        claims = jwt.decode(
            token,
            settings.auth_signing_key,
            algorithms=[JWT_ALGORITHM],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            leeway=_CLOCK_SKEW,
            options={"require": ["sub", "typ", "iss", "aud", "iat", "exp", "jti"]},
        )
        if claims["typ"] != ACCESS_TOKEN_TYPE:
            raise TokenError("wrong token type")
        sid = claims.get("sid")
        return AccessClaims(
            user_id=uuid.UUID(claims["sub"]),
            session_id=uuid.UUID(sid) if sid is not None else None,
            jti=str(claims["jti"]),
            issued_at=datetime.fromtimestamp(claims["iat"], UTC),
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    except TokenError:
        raise
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        # Only the exception type: never the token itself.
        raise TokenError(type(exc).__name__) from None


# --------------------------------------------------------------------------- #
# Refresh tokens and other opaque secrets
# --------------------------------------------------------------------------- #
def new_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Hex SHA-256 used to store and look up opaque tokens. Raises TokenError if implausible."""
    if not token or len(token) > _MAX_REFRESH_TOKEN_CHARS:
        raise TokenError("bad token length")
    return hashlib.sha256(token.encode()).hexdigest()
