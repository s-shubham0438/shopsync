"""Milestone 5.1 security foundation: passwords, tokens, cookies, client IP, rate limiting,
settings. No database."""

import base64
import json
import logging
import uuid
import warnings
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from typing import Any

import jwt
import pytest
from argon2 import PasswordHasher
from fastapi import Response
from pydantic import ValidationError
from starlette.requests import Request

from app.core import security
from app.core.auth_http import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    clear_auth_cookies,
    client_ip,
    set_auth_cookies,
)
from app.core.config import EXAMPLE_SECRET, Environment, Settings
from app.core.errors import RateLimitedError
from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_password_async,
    hash_token,
    new_refresh_token,
    password_needs_rehash,
    password_problem,
    verify_password,
    verify_password_async,
)
from app.services.rate_limit import RateLimiter
from tests.services.test_cache_unit import FakeRedis

SECRET = "unit-test-secret-" + "x" * 32


def settings(**kw: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment=Environment.TEST,
        auth_secret_key=kw.pop("auth_secret_key", SECRET),
        **kw,
    )


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def test_hash_is_argon2id_salted_and_verifies() -> None:
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first.startswith("$argon2id$")
    assert first != second  # random salt
    assert "correct horse" not in first
    assert verify_password(first, "correct horse")
    assert not verify_password(first, "correct horsE")
    assert not verify_password(first, "")


def test_missing_or_broken_hash_never_verifies_or_raises() -> None:
    assert not verify_password(None, "anything")
    assert not verify_password("", "anything")
    assert not verify_password("not-a-hash", "anything")
    assert not verify_password("$argon2id$v=19$m=1,t=1,p=1$bad$bad", "anything")


def test_unknown_account_path_does_a_real_argon2_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real = security._hasher

    class Spy:
        def verify(self, hash_: str, password: str) -> bool:
            calls.append(hash_)
            return real.verify(hash_, password)

    monkeypatch.setattr(security, "_hasher", Spy())
    assert not verify_password(None, "guess")
    assert len(calls) == 1 and calls[0].startswith("$argon2id$")  # same cost as a real check


def test_rehash_needed_for_weaker_parameters() -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash("pw-123456")
    assert password_needs_rehash(weak)
    assert verify_password(weak, "pw-123456")  # still verifies, so it can be upgraded at login
    assert not password_needs_rehash(hash_password("pw-123456"))
    assert password_needs_rehash("garbage")


async def test_warm_up_prebuilds_the_dummy_hash() -> None:
    security._dummy_hash.cache_clear()
    await security.warm_up()
    assert security._dummy_hash.cache_info().currsize == 1


async def test_async_wrappers() -> None:
    hashed = await hash_password_async("async-pass-1")
    assert await verify_password_async(hashed, "async-pass-1")
    assert not await verify_password_async(hashed, "nope")


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("short1", "at least 8"),
        ("x" * 129, "at most 128"),
        (" " * 10, "only spaces"),
        ("Password123", "too common"),
        ("aaaaaaaaaa", "too common"),
        ("abababab", "too common"),
        ("priya.sharma", "email name"),
    ],
)
def test_password_policy_rejects(password: str, fragment: str) -> None:
    problem = password_problem(password, email="Priya.Sharma@example.com")
    assert problem is not None and fragment in problem


@pytest.mark.parametrize("password", ["correct horse battery", "Tr0ub4dor&3", "मेरा पासवर्ड 42"])
def test_password_policy_accepts(password: str) -> None:
    assert password_problem(password, email="someone@example.com") is None


# --------------------------------------------------------------------------- #
# Access tokens
# --------------------------------------------------------------------------- #
def test_access_token_round_trip() -> None:
    s = settings()
    user, session_id = uuid.uuid7(), uuid.uuid7()
    token, expires = create_access_token(user, s, session_id=session_id)
    claims = decode_access_token(token, s)
    assert claims.user_id == user
    assert claims.session_id == session_id
    assert claims.expires_at == expires
    assert claims.expires_at - claims.issued_at == timedelta(seconds=s.access_token_ttl_seconds)
    assert decode_access_token(create_access_token(user, s)[0], s).session_id is None


def _b64(data: dict[str, Any]) -> str:
    data = {k: int(v.timestamp()) if isinstance(v, datetime) else v for k, v in data.items()}
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _claims(s: Settings, **overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(uuid.uuid7()),
        "typ": "access",
        "iss": s.auth_issuer,
        "aud": s.auth_audience,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "j",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _hs512(claims: dict[str, Any], key: str) -> str:
    with warnings.catch_warnings():  # short key for SHA-512 is the point of this case
        warnings.simplefilter("ignore")
        return jwt.encode(claims, key, algorithm="HS512")


def bad_tokens(s: Settings) -> dict[str, str]:
    good, _ = create_access_token(uuid.uuid7(), s)
    header, payload, signature = good.split(".")
    tampered_payload = _b64(_claims(s, sub=str(uuid.uuid7())))
    return {
        "tampered_payload": f"{header}.{tampered_payload}.{signature}",
        "bad_signature": f"{header}.{payload}.{signature[::-1]}",
        "alg_none": f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{payload}.",
        "other_key": jwt.encode(_claims(s), "another-secret-" + "y" * 32, algorithm="HS256"),
        "other_hmac_alg": _hs512(_claims(s), s.auth_signing_key),
        "expired": jwt.encode(
            _claims(
                s,
                iat=datetime.now(UTC) - timedelta(hours=2),
                exp=datetime.now(UTC) - timedelta(minutes=1),
            ),
            s.auth_signing_key,
            algorithm="HS256",
        ),
        "wrong_audience": jwt.encode(_claims(s, aud="other"), s.auth_signing_key, "HS256"),
        "wrong_issuer": jwt.encode(_claims(s, iss="evil"), s.auth_signing_key, "HS256"),
        "wrong_type": jwt.encode(_claims(s, typ="refresh"), s.auth_signing_key, "HS256"),
        "missing_jti": jwt.encode(_claims(s, jti=None), s.auth_signing_key, "HS256"),
        "missing_exp": jwt.encode(_claims(s, exp=None), s.auth_signing_key, "HS256"),
        "sub_not_uuid": jwt.encode(_claims(s, sub="admin"), s.auth_signing_key, "HS256"),
        "garbage": "not.a.jwt",
        "empty": "",
        "huge": "a" * 5000,
    }


@pytest.mark.parametrize("case", list(bad_tokens(settings())))
def test_bad_tokens_are_rejected_without_echoing_them(case: str) -> None:
    s = settings()
    token = bad_tokens(s)[case]
    with pytest.raises(TokenError) as exc_info:
        decode_access_token(token, s)
    if len(token) > 20:
        assert token not in str(exc_info.value)


def test_small_clock_skew_is_tolerated() -> None:
    s = settings()
    past = datetime.now(UTC) - timedelta(seconds=s.access_token_ttl_seconds + 5)
    token, _ = create_access_token(uuid.uuid7(), s, now=past)  # expired 5 s ago
    decode_access_token(token, s)


def test_tokens_from_another_deployment_are_rejected() -> None:
    token, _ = create_access_token(uuid.uuid7(), settings())
    with pytest.raises(TokenError):
        decode_access_token(token, settings(auth_secret_key="z" * 40))


# --------------------------------------------------------------------------- #
# Refresh tokens
# --------------------------------------------------------------------------- #
def test_refresh_tokens_are_random_and_stored_as_sha256() -> None:
    tokens = {new_refresh_token() for _ in range(100)}
    assert len(tokens) == 100
    token = tokens.pop()
    assert len(token) >= 43  # 256 bits, base64url
    digest = hash_token(token)
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert digest == hash_token(token)
    assert token not in digest
    for bad in ("", "x" * 129):
        with pytest.raises(TokenError):
            hash_token(bad)


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #
def parsed_cookies(response: Response) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for header in response.headers.getlist("set-cookie"):
        jar = SimpleCookie()
        jar.load(header)
        for name, morsel in jar.items():
            out[name] = {"value": morsel.value, "raw": header.lower(), **dict(morsel)}
    return out


def test_auth_cookies_are_httponly_secure_lax_and_scoped() -> None:
    s = settings()
    response = Response()
    expires = datetime.now(UTC) + timedelta(minutes=15)
    set_auth_cookies(
        response, s, access_token="AAA", access_expires=expires,
        refresh_token="RRR", refresh_expires=expires + timedelta(days=30),
    )  # fmt: skip
    cookies = parsed_cookies(response)
    access, refresh = cookies[ACCESS_COOKIE], cookies[REFRESH_COOKIE]
    assert access["value"] == "AAA" and refresh["value"] == "RRR"
    for c in (access, refresh):
        assert "httponly" in c["raw"] and "secure" in c["raw"] and "samesite=lax" in c["raw"]
        assert "domain" not in c["raw"]
    assert access["path"] == "/api/v1"
    assert refresh["path"] == "/api/v1/auth"  # refresh token only goes to auth endpoints


def test_cookie_domain_and_strict_samesite_are_configurable() -> None:
    response = Response()
    now = datetime.now(UTC)
    set_auth_cookies(
        response, settings(cookie_domain="shopsync.example", cookie_samesite="strict"),
        access_token="a", access_expires=now, refresh_token="r", refresh_expires=now,
    )  # fmt: skip
    raw = parsed_cookies(response)[ACCESS_COOKIE]["raw"]
    assert "domain=shopsync.example" in raw and "samesite=strict" in raw


def test_clearing_cookies_matches_their_attributes() -> None:
    response = Response()
    clear_auth_cookies(response, settings())
    cookies = parsed_cookies(response)
    assert cookies[ACCESS_COOKIE]["max-age"] == "0"
    assert cookies[ACCESS_COOKIE]["path"] == "/api/v1"
    assert cookies[REFRESH_COOKIE]["path"] == "/api/v1/auth"
    assert all("httponly" in c["raw"] and "secure" in c["raw"] for c in cookies.values())


# --------------------------------------------------------------------------- #
# Client IP
# --------------------------------------------------------------------------- #
def request_from(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_forwarded_for_ignored_unless_proxies_are_trusted() -> None:
    req = request_from("10.0.0.5", "6.6.6.6")
    assert client_ip(req, settings()) == "10.0.0.5"


@pytest.mark.parametrize(
    ("proxies", "xff", "expected"),
    [
        (1, "1.2.3.4", "1.2.3.4"),
        (1, "6.6.6.6, 1.2.3.4", "1.2.3.4"),  # spoofed left-most entry ignored
        (2, "6.6.6.6, 1.2.3.4, 10.0.0.1", "1.2.3.4"),
        (2, "1.2.3.4", "10.0.0.5"),  # fewer hops than proxies: use the peer
        (1, "not-an-ip", None),
        (1, "2001:db8::1", "2001:db8::1"),
    ],
)
def test_trusted_proxy_hops(proxies: int, xff: str, expected: str | None) -> None:
    assert client_ip(request_from("10.0.0.5", xff), settings(trusted_proxy_count=proxies)) == (
        expected
    )


# --------------------------------------------------------------------------- #
# Rate limiter
# --------------------------------------------------------------------------- #
class CounterRedis(FakeRedis):
    async def expire(self, name: str, time: int) -> bool:
        await self._op("expire")
        self.ttls[name] = time
        return True


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def limiter(redis: CounterRedis | None = None, clock: Clock | None = None) -> RateLimiter:
    return RateLimiter(
        redis if redis is not None else CounterRedis(), secret=SECRET, clock=clock or Clock()
    )


async def test_limit_window_and_reset() -> None:
    clock = Clock(1_000_000.0)  # window boundary at 1_000_200 for window=300? computed below
    rl = limiter(clock=clock)
    results = [await rl.hit("login", "a@example.com", limit=3, window=60) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert results[-1].count == 4
    assert 1 <= results[-1].retry_after <= 60
    with pytest.raises(RateLimitedError) as exc_info:
        results[-1].raise_if_blocked()
    assert exc_info.value.headers == {"Retry-After": str(results[-1].retry_after)}

    clock.now += 60  # next window
    assert (await rl.hit("login", "a@example.com", limit=3, window=60)).allowed


async def test_identifiers_and_buckets_are_separate_and_hashed() -> None:
    redis = CounterRedis()
    rl = limiter(redis)
    for _ in range(2):
        await rl.hit("login", "a@example.com", limit=1, window=60)
    assert (await rl.hit("login", "b@example.com", limit=1, window=60)).allowed
    assert (await rl.hit("register", "a@example.com", limit=1, window=60)).allowed
    assert all("example.com" not in key for key in redis.data)
    assert all(key.startswith("shopsync:v1:rl:") for key in redis.data)
    assert set(redis.ttls.values()) == {61}


async def test_redis_failure_falls_back_to_local_limits_and_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis, clock = CounterRedis(), Clock()
    redis.fail = True
    rl = limiter(redis, clock)
    caplog.set_level(logging.INFO, logger="app.services.rate_limit")

    results = [await rl.hit("login", "x", limit=2, window=60) for _ in range(3)]
    assert [r.allowed for r in results] == [True, True, False]  # still limited
    assert [r.message for r in caplog.records].count("rate_limit_redis_unavailable") == 1
    assert redis.calls == ["incr"]  # back-off: Redis not retried every request

    clock.now += 31
    redis.fail = False
    assert (await rl.hit("login", "y", limit=2, window=60)).allowed
    assert "rate_limit_redis_recovered" in caplog.text


async def test_no_redis_at_all_still_limits() -> None:
    rl = RateLimiter(None, secret=SECRET, clock=Clock())
    results = [await rl.hit("otp", "+919876543210", limit=1, window=60) for _ in range(2)]
    assert [r.allowed for r in results] == [True, False]


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
PROD = {
    "environment": Environment.PRODUCTION,
    "cors_origins": "https://shopsync.example",
    "frontend_url": "https://shopsync.example",
}


def prod(**kw: Any) -> Settings:
    return Settings(_env_file=None, **(PROD | kw))  # type: ignore[arg-type]


def test_production_requires_a_strong_secret() -> None:
    with pytest.raises(ValidationError, match="AUTH_SECRET_KEY"):
        prod()
    with pytest.raises(ValidationError, match="AUTH_SECRET_KEY"):
        prod(auth_secret_key=EXAMPLE_SECRET)
    assert prod(auth_secret_key="s" * 40).auth_signing_key == "s" * 40


def test_short_secret_rejected_everywhere_without_echoing_it() -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings(auth_secret_key="tooShortSecret123")
    assert "tooShortSecret123" not in str(exc_info.value)


def test_production_requires_secure_cookies_and_https_origins() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        prod(auth_secret_key="s" * 40, cookie_secure=False)
    with pytest.raises(ValidationError, match="https"):
        prod(auth_secret_key="s" * 40, cors_origins="http://shopsync.example")


def test_cross_site_samesite_none_is_not_supported() -> None:
    with pytest.raises(ValidationError):
        settings(cookie_samesite="none")


def test_unset_secret_uses_a_stable_per_process_key_outside_production() -> None:
    a = Settings(_env_file=None, environment=Environment.DEVELOPMENT)  # type: ignore[call-arg]
    b = Settings(_env_file=None, environment=Environment.DEVELOPMENT)  # type: ignore[call-arg]
    assert a.auth_secret_key is None
    assert a.auth_signing_key == b.auth_signing_key
    assert len(a.auth_signing_key) >= 32
    assert a.auth_signing_key not in repr(a)


@pytest.mark.parametrize(
    "field",
    [
        "access_token_ttl_seconds",
        "refresh_token_ttl_days",
        "trusted_proxy_count",
        "auth_rate_limit_window_seconds",
        "auth_rate_limit_per_ip",
        "auth_rate_limit_per_account",
    ],
)
def test_auth_numbers_reject_booleans(field: str) -> None:
    with pytest.raises(ValidationError, match="must be a number"):
        settings(**{field: True})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_token_ttl_seconds", 30),
        ("access_token_ttl_seconds", 7200),
        ("refresh_token_ttl_days", 0),
        ("refresh_token_ttl_days", 91),
        ("trusted_proxy_count", 6),
    ],
)
def test_auth_number_ranges(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        settings(**{field: value})


def test_secret_never_appears_in_settings_repr() -> None:
    s = settings()
    assert SECRET not in repr(s) and SECRET not in str(s.model_dump())
