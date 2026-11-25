"""Milestone 5.1: CurrentUser / OptionalUser and the CSRF origin check, over HTTP with
PostgreSQL (shopsync_test, rolled back). The routes below exist only in this test app."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, OptionalUser
from app.api.v1.router import api_router
from app.core.auth_http import ACCESS_COOKIE, REFRESH_COOKIE, verify_origin
from app.core.config import Environment, Settings
from app.core.security import create_access_token, hash_password
from app.db.session import get_db_session
from app.main import create_app
from app.models import User

FRONTEND = "http://localhost:5173"

probe = APIRouter(prefix="/api/v1/_probe", dependencies=[Depends(verify_origin)])


@probe.get("/me")
async def me(user: CurrentUser) -> dict[str, Any]:
    return {"id": str(user.id), "email": user.email}


@probe.get("/maybe")
async def maybe(user: OptionalUser) -> dict[str, Any]:
    return {"id": str(user.id) if user else None}


@probe.post("/change")
async def change(user: CurrentUser) -> dict[str, str]:
    return {"ok": str(user.id)}


@probe.post("/public")
async def public() -> dict[str, str]:
    return {"ok": "yes"}


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment=Environment.TEST,
        auth_secret_key="integration-secret-" + "k" * 32,
        cors_origins=FRONTEND,
    )


@pytest.fixture
async def client(session: AsyncSession, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    app.include_router(probe)

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = test_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    ) as c:
        yield c


@pytest.fixture
async def user(session: AsyncSession) -> User:
    u = User(email=f"user-{uuid.uuid4().hex[:12]}@example.com", password_hash=hash_password("pw-1"))
    session.add(u)
    await session.flush()
    return u


def cookie(token: str, name: str = ACCESS_COOKIE) -> dict[str, str]:
    return {"Cookie": f"{name}={token}"}


def assert_unauthorized(response: httpx.Response) -> None:
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "unauthorized"


def test_csrf_check_is_on_every_v1_route() -> None:
    assert any(d.dependency is verify_origin for d in api_router.dependencies)


async def test_valid_access_cookie_resolves_the_user(
    client: httpx.AsyncClient, user: User, settings: Settings
) -> None:
    token, _ = create_access_token(user.id, settings)
    response = await client.get("/api/v1/_probe/me", headers=cookie(token))
    assert response.status_code == 200
    body = response.json()
    assert body == {"id": str(user.id), "email": user.email}
    assert "password" not in response.text


async def test_missing_or_bad_credentials_are_401(
    client: httpx.AsyncClient, user: User, settings: Settings
) -> None:
    assert_unauthorized(await client.get("/api/v1/_probe/me"))
    assert_unauthorized(await client.get("/api/v1/_probe/me", headers=cookie("garbage")))

    expired, _ = create_access_token(user.id, settings, now=datetime.now(UTC) - timedelta(hours=1))
    assert_unauthorized(await client.get("/api/v1/_probe/me", headers=cookie(expired)))

    other_key = settings.model_copy(update={"auth_secret_key": None})  # ephemeral key
    forged, _ = create_access_token(user.id, other_key)
    assert_unauthorized(await client.get("/api/v1/_probe/me", headers=cookie(forged)))

    # The refresh cookie is not an access credential.
    token, _ = create_access_token(user.id, settings)
    assert_unauthorized(
        await client.get("/api/v1/_probe/me", headers=cookie(token, REFRESH_COOKIE))
    )


async def test_deleted_or_inactive_user_is_401(
    client: httpx.AsyncClient, user: User, settings: Settings, session: AsyncSession
) -> None:
    ghost, _ = create_access_token(uuid.uuid7(), settings)
    assert_unauthorized(await client.get("/api/v1/_probe/me", headers=cookie(ghost)))

    token, _ = create_access_token(user.id, settings)
    user.is_active = False
    await session.flush()
    assert_unauthorized(await client.get("/api/v1/_probe/me", headers=cookie(token)))


async def test_optional_user(client: httpx.AsyncClient, user: User, settings: Settings) -> None:
    token, _ = create_access_token(user.id, settings)
    assert (await client.get("/api/v1/_probe/maybe")).json() == {"id": None}
    assert (await client.get("/api/v1/_probe/maybe", headers=cookie("bad"))).json() == {"id": None}
    response = await client.get("/api/v1/_probe/maybe", headers=cookie(token))
    assert response.json() == {"id": str(user.id)}


@pytest.mark.parametrize(
    ("headers", "allowed"),
    [
        ({"Origin": FRONTEND}, True),
        ({"Origin": "http://api.test"}, True),  # same origin
        ({"Referer": f"{FRONTEND}/wishlist"}, True),  # Origin missing: Referer fallback
        ({"Origin": "https://evil.example"}, False),
        ({"Origin": "null"}, False),
        ({"Origin": "http://localhost:5173.evil.example"}, False),
        ({"Referer": "https://evil.example/x"}, False),
        ({}, False),
    ],
)
async def test_cookie_authenticated_writes_need_an_allowed_origin(
    client: httpx.AsyncClient,
    user: User,
    settings: Settings,
    headers: dict[str, str],
    allowed: bool,
) -> None:
    token, _ = create_access_token(user.id, settings)
    response = await client.post("/api/v1/_probe/change", headers=cookie(token) | headers)
    if allowed:
        assert response.status_code == 200, response.text
    else:
        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "csrf_failed"
        assert error["request_id"] == response.headers["x-request-id"]


async def test_origin_check_skips_safe_methods_and_cookieless_requests(
    client: httpx.AsyncClient, user: User, settings: Settings
) -> None:
    token, _ = create_access_token(user.id, settings)
    evil = {"Origin": "https://evil.example"}
    # GETs don't change state.
    assert (await client.get("/api/v1/_probe/me", headers=cookie(token) | evil)).status_code == 200
    # No auth cookie: nothing to forge (login/register are cookieless).
    assert (await client.post("/api/v1/_probe/public", headers=evil)).status_code == 200
    # A stale refresh cookie alone still triggers the check.
    stale = cookie("whatever", REFRESH_COOKIE) | evil
    assert (await client.post("/api/v1/_probe/public", headers=stale)).status_code == 403
