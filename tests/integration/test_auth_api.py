"""Milestone 5.2 email/password auth over HTTP: real app and routes, PostgreSQL (shopsync_test,
rolled back), in-memory Redis for rate limits. Cookies travel through httpx's cookie jar exactly
as a browser would send them (Secure, path-scoped), so the API is served over https://."""

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_http import ACCESS_COOKIE, REFRESH_COOKIE
from app.core.config import Environment, Settings
from app.core.security import hash_password, hash_token
from app.db.session import get_db_session
from app.main import create_app
from app.models import RefreshToken, User
from app.repositories.users import UserRepository
from app.services.auth import BAD_LOGIN_MESSAGE, DUPLICATE_EMAIL_MESSAGE
from app.services.rate_limit import RateLimiter
from tests.auth.test_security_unit import CounterRedis

BASE = "https://api.test"
PASSWORD = "correct horse battery"
USER_FIELDS = {"id", "email", "phone", "full_name", "is_email_verified", "is_phone_verified"}

ClientFactory = Callable[..., Awaitable[httpx.AsyncClient]]


@pytest.fixture
async def make_client(session: AsyncSession) -> AsyncIterator[ClientFactory]:
    clients: list[httpx.AsyncClient] = []
    redis = CounterRedis()  # shared by every client: limits are per deployment, not per client

    async def factory(**overrides: Any) -> httpx.AsyncClient:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment=Environment.TEST,
            auth_secret_key="api-test-secret-" + "q" * 32,
            **overrides,
        )
        app = create_app(settings)
        app.state.rate_limiter = RateLimiter(redis, secret=settings.auth_signing_key)

        async def test_session() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_db_session] = test_session
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("203.0.113.7", 4000)),
            base_url=f"{BASE}/api/v1",
            headers={"Origin": BASE, "User-Agent": "pytest-browser/1.0"},
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()


@pytest.fixture
def security_events() -> Iterator[list[logging.LogRecord]]:
    """Records from app.security. A handler on that logger survives create_app()'s logging
    setup, which replaces root handlers (and with them pytest's caplog handler)."""
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Collect(level=logging.DEBUG)
    logger = logging.getLogger("app.security")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


@pytest.fixture
async def client(make_client: ClientFactory) -> httpx.AsyncClient:
    return await make_client()


def new_email() -> str:
    return f"Shopper.{uuid.uuid4().hex[:12]}@Example.COM"  # uuid4: random, unlike uuid7's prefix


async def signup(client: httpx.AsyncClient, email: str | None = None, **kw: Any) -> httpx.Response:
    body = {"full_name": "  Asha   Rao ", "email": email or new_email(), "password": PASSWORD}
    return await client.post("/auth/signup", json=body | kw)


async def existing_user(session: AsyncSession, **kw: Any) -> User:
    user = User(
        email=kw.pop("email", new_email().lower()),
        password_hash=kw.pop("password_hash", hash_password(PASSWORD)),
        full_name="Existing",
        **kw,
    )
    session.add(user)
    await session.commit()  # survive service-side rollbacks in the test transaction
    return user


def error_of(response: httpx.Response) -> dict[str, Any]:
    error: dict[str, Any] = response.json()["error"]
    return error


def cleared(response: httpx.Response) -> set[str]:
    return {
        h.split("=", 1)[0]
        for h in response.headers.get_list("set-cookie")
        if "max-age=0" in h.lower()
    }


async def tokens_of(session: AsyncSession, user_id: uuid.UUID) -> list[RefreshToken]:
    rows = await session.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .order_by(RefreshToken.id)
        .execution_options(populate_existing=True)
    )
    return list(rows)


# --------------------------------------------------------------------------- #
# Signup
# --------------------------------------------------------------------------- #
async def test_signup_creates_account_and_signs_in(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    email = new_email()
    response = await signup(client, email)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == USER_FIELDS | {"verification_email_sent"}
    assert body.pop("verification_email_sent") is False  # no email provider in tests: never claimed
    assert body["email"] == email.lower()
    assert body["full_name"] == "Asha Rao"
    assert body["is_email_verified"] is False
    assert response.headers["cache-control"] == "no-store"
    assert {ACCESS_COOKIE, REFRESH_COOKIE} <= set(client.cookies.keys())
    assert "argon2" not in response.text and PASSWORD not in response.text

    user = await session.scalar(select(User).where(User.email == email.lower()))
    assert user is not None and user.password_hash is not None
    assert user.password_hash.startswith("$argon2id$")
    assert user.last_login_at is not None
    (token,) = await tokens_of(session, user.id)
    raw_refresh = client.cookies[REFRESH_COOKIE]
    assert token.token_hash == hash_token(raw_refresh) != raw_refresh
    assert token.user_agent == "pytest-browser/1.0"
    assert str(token.ip) == "203.0.113.7"

    me = await client.get("/auth/me")
    assert me.status_code == 200 and me.json() == body


async def test_duplicate_email_any_case(client: httpx.AsyncClient) -> None:
    email = new_email()
    assert (await signup(client, email)).status_code == 201
    response = await signup(client, email.upper())
    assert response.status_code == 409
    error = error_of(response)
    assert error["code"] == "email_taken"
    assert (
        error["message"]
        == DUPLICATE_EMAIL_MESSAGE
        == ("An account with this email already exists. Please log in.")
    )


async def test_duplicate_signup_race_is_caught_by_the_unique_index(
    client: httpx.AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken = await existing_user(session)

    async def not_found(self: UserRepository, email: str) -> None:
        return None  # simulate the check running before the other request committed

    monkeypatch.setattr(UserRepository, "get_by_email", not_found)
    response = await signup(client, (taken.email or "").upper())
    assert response.status_code == 409
    assert error_of(response)["message"] == DUPLICATE_EMAIL_MESSAGE


@pytest.mark.parametrize(
    ("overrides", "loc"),
    [
        ({"password": "short"}, ["body", "password"]),
        ({"password": "password123"}, ["body", "password"]),
        ({"email": "not-an-email"}, ["body", "email"]),
        ({"email": "a@b"}, ["body", "email"]),
        ({"full_name": "   "}, ["body", "full_name"]),
        ({"is_admin": True}, ["body", "is_admin"]),
    ],
)
async def test_signup_validation(
    client: httpx.AsyncClient, overrides: dict[str, Any], loc: list[str]
) -> None:
    response = await signup(client, **overrides)
    assert response.status_code == 422, response.text
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert any(d["loc"] == loc for d in error["details"])
    assert "password123" not in response.text  # rejected inputs are never echoed
    assert ACCESS_COOKIE not in client.cookies


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
async def test_login_with_any_email_case(client: httpx.AsyncClient, session: AsyncSession) -> None:
    user = await existing_user(session)
    response = await client.post(
        "/auth/login", json={"email": (user.email or "").upper(), "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(user.id)
    assert (await client.get("/auth/me")).json()["id"] == str(user.id)


async def test_every_login_failure_looks_the_same(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    active = await existing_user(session)
    inactive = await existing_user(session, is_active=False)
    no_password = await existing_user(session, password_hash=None)
    attempts = [
        (active.email, "wrong password!"),
        (new_email(), PASSWORD),  # no such account
        (inactive.email, PASSWORD),  # right password, disabled account
        (no_password.email, PASSWORD),  # Google/OTP-only account
    ]
    shapes = set()
    for email, password in attempts:
        client = await make_client()
        response = await client.post("/auth/login", json={"email": email, "password": password})
        error = error_of(response)
        shapes.add((response.status_code, error["code"], error["message"]))
        assert not client.cookies
    assert shapes == {(401, "invalid_credentials", BAD_LOGIN_MESSAGE)}


async def test_login_upgrades_weak_password_hashes(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash(PASSWORD)
    user = await existing_user(session, password_hash=weak)
    response = await client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200
    await session.refresh(user)
    assert user.password_hash != weak
    assert "m=65536" in (user.password_hash or "")


# --------------------------------------------------------------------------- #
# Refresh
# --------------------------------------------------------------------------- #
async def test_refresh_rotates_within_the_family(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user_id = uuid.UUID((await signup(client)).json()["id"])
    old_access, old_refresh = client.cookies[ACCESS_COOKIE], client.cookies[REFRESH_COOKIE]

    response = await client.post("/auth/refresh")
    assert response.status_code == 204, response.text
    assert client.cookies[REFRESH_COOKIE] != old_refresh
    assert client.cookies[ACCESS_COOKIE] != old_access
    assert (await client.get("/auth/me")).status_code == 200

    first, second = await tokens_of(session, user_id)
    assert first.family_id == second.family_id
    assert first.revoked_at is not None and first.replaced_by_id == second.id
    assert second.revoked_at is None


async def test_reused_refresh_token_revokes_the_whole_session(
    make_client: ClientFactory,
    session: AsyncSession,
    security_events: list[logging.LogRecord],
) -> None:
    client = await make_client(refresh_reuse_grace_seconds=0)
    attacker = await make_client(refresh_reuse_grace_seconds=0)
    user_id = uuid.UUID((await signup(client)).json()["id"])
    stolen = client.cookies[REFRESH_COOKIE]
    assert (await client.post("/auth/refresh")).status_code == 204  # the real user rotates

    replay = await attacker.post("/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={stolen}"})
    assert replay.status_code == 401
    assert {ACCESS_COOKIE, REFRESH_COOKIE} <= cleared(replay)
    reuse = [r for r in security_events if r.getMessage() == "refresh_token_reuse"]
    assert len(reuse) == 1 and reuse[0].levelno == logging.WARNING

    # The legitimate user's newer token is dead too: the family is revoked.
    assert (await client.post("/auth/refresh")).status_code == 401
    assert all(t.revoked_at is not None for t in await tokens_of(session, user_id))


async def test_parallel_tab_refresh_within_grace_keeps_the_session(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    client = await make_client()
    user_id = uuid.UUID((await signup(client)).json()["id"])
    previous = client.cookies[REFRESH_COOKIE]
    assert (await client.post("/auth/refresh")).status_code == 204
    current = client.cookies[REFRESH_COOKIE]

    other_tab = await make_client()
    stale = await other_tab.post(
        "/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={previous}"}
    )
    assert stale.status_code == 401
    tokens = await tokens_of(session, user_id)
    assert tokens[-1].revoked_at is None  # not revoked
    again = await other_tab.post("/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={current}"})
    assert again.status_code == 204


async def test_expired_unknown_and_missing_refresh_tokens(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user_id = uuid.UUID((await signup(client)).json()["id"])
    (token,) = await tokens_of(session, user_id)
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()

    expired = await client.post("/auth/refresh")
    assert expired.status_code == 401
    assert error_of(expired)["code"] == "unauthorized"
    assert {ACCESS_COOKIE, REFRESH_COOKIE} <= cleared(expired)

    for cookie in (f"{REFRESH_COOKIE}=not-a-real-token", f"{REFRESH_COOKIE}={'x' * 500}", ""):
        anon = await client.post("/auth/refresh", headers={"Cookie": cookie} if cookie else {})
        assert anon.status_code == 401


async def test_session_cap_ends_the_oldest_session(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    user = await existing_user(session)
    devices = []
    for _ in range(3):
        device = await make_client(auth_max_sessions=2)
        login = {"email": user.email, "password": PASSWORD}
        assert (await device.post("/auth/login", json=login)).status_code == 200
        devices.append(device)
    assert (await devices[0].post("/auth/refresh")).status_code == 401  # oldest ended
    assert (await devices[1].post("/auth/refresh")).status_code == 204
    assert (await devices[2].post("/auth/refresh")).status_code == 204


# --------------------------------------------------------------------------- #
# Logout and /me
# --------------------------------------------------------------------------- #
async def test_logout_ends_the_session_and_clears_cookies(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    user_id = uuid.UUID((await signup(client)).json()["id"])
    refresh_token = client.cookies[REFRESH_COOKIE]
    response = await client.post("/auth/logout")
    assert response.status_code == 204
    assert {ACCESS_COOKIE, REFRESH_COOKIE} <= cleared(response)
    assert (await client.get("/auth/me")).status_code == 401
    assert all(t.revoked_at is not None for t in await tokens_of(session, user_id))
    replay = await client.post(
        "/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={refresh_token}"}
    )
    assert replay.status_code == 401


async def test_logout_is_idempotent(client: httpx.AsyncClient) -> None:
    assert (await client.post("/auth/logout")).status_code == 204
    garbage = {"Cookie": f"{ACCESS_COOKIE}=junk; {REFRESH_COOKIE}=junk"}
    assert (await client.post("/auth/logout", headers=garbage)).status_code == 204


async def test_me_requires_a_session(client: httpx.AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 401
    assert error_of(response)["code"] == "unauthorized"


async def test_logout_from_another_site_is_blocked(client: httpx.AsyncClient) -> None:
    await signup(client)
    response = await client.post("/auth/logout", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert error_of(response)["code"] == "csrf_failed"
    assert (await client.get("/auth/me")).status_code == 200  # still signed in


# --------------------------------------------------------------------------- #
# Rate limits
# --------------------------------------------------------------------------- #
async def test_login_attempts_are_limited_per_account(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    user = await existing_user(session)
    client = await make_client(auth_rate_limit_per_account=2)
    statuses = []
    for _ in range(3):
        r = await client.post("/auth/login", json={"email": user.email, "password": "nope-nope"})
        statuses.append(r.status_code)
    assert statuses == [401, 401, 429]
    assert int(r.headers["retry-after"]) > 0
    assert error_of(r)["code"] == "rate_limited"
    # Even the right password is refused until the window ends.
    right = await client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert right.status_code == 429


async def test_signup_and_refresh_are_limited_per_ip(make_client: ClientFactory) -> None:
    client = await make_client(auth_signup_limit_per_hour=1, auth_refresh_limit_per_ip=1)
    assert (await signup(client)).status_code == 201
    assert (await signup(client)).status_code == 429
    assert (await client.post("/auth/refresh")).status_code == 204
    assert (await client.post("/auth/refresh")).status_code == 429


# --------------------------------------------------------------------------- #
# Secrets never leak
# --------------------------------------------------------------------------- #
async def test_logs_never_contain_credentials(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    email = new_email()
    await signup(client, email)
    tokens = [client.cookies[ACCESS_COOKIE], client.cookies[REFRESH_COOKIE]]
    await client.post("/auth/refresh")
    tokens += [client.cookies[ACCESS_COOKIE], client.cookies[REFRESH_COOKIE]]
    await client.post("/auth/login", json={"email": email, "password": "wrong-password"})
    await client.post("/auth/logout")

    logged = "\n".join(str(vars(r)) for r in caplog.records)
    assert caplog.records
    for secret in [PASSWORD, "wrong-password", email.lower(), email, *tokens]:
        assert secret not in logged
    events = {r.message for r in caplog.records if r.name == "app.security"}
    assert {"signup", "refresh", "login", "logout"} <= events


async def test_openapi_documents_auth_routes(client: httpx.AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert {
        "/api/v1/auth/signup",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
    } <= set(paths)
