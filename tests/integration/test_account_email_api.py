"""Milestones 5.4 (email verification) and 5.5 (password recovery) over HTTP.

PostgreSQL shopsync_test (rolled back), in-memory Redis, and a fake email sender that captures
messages so the emailed links can be followed like a user would.
"""

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_http import REFRESH_COOKIE
from app.core.config import Environment, Settings
from app.core.security import hash_password
from app.db.session import get_db_session
from app.main import create_app
from app.models import AuthToken, User
from app.services.messaging import DeliveryUnavailableError, OutgoingEmail
from app.services.rate_limit import RateLimiter
from tests.auth.test_security_unit import CounterRedis

BASE = "https://api.test"
FRONTEND = "https://shop.test"
PASSWORD = "correct horse battery"
NEW_PASSWORD = "brand new horse 42"


class FakeEmailSender:
    def __init__(self, *, available: bool = True, fail: bool = False) -> None:
        self.available = available
        self.fail = fail
        self.sent: list[OutgoingEmail] = []

    async def send(self, message: OutgoingEmail) -> None:
        if self.fail or not self.available:
            raise DeliveryUnavailableError("down")
        self.sent.append(message)

    def token(self, index: int = -1) -> str:
        match = re.search(r"#token=([A-Za-z0-9_-]+)", self.sent[index].text)
        assert match, self.sent[index].text
        return match.group(1)


ClientFactory = Callable[..., Awaitable[tuple[httpx.AsyncClient, FakeEmailSender]]]


@pytest.fixture
async def make_client(session: AsyncSession) -> AsyncIterator[ClientFactory]:
    clients: list[httpx.AsyncClient] = []
    redis = CounterRedis()

    async def factory(
        sender: FakeEmailSender | None = None, **overrides: Any
    ) -> tuple[httpx.AsyncClient, FakeEmailSender]:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment=Environment.TEST,
            auth_secret_key="email-test-secret-" + "e" * 32,
            frontend_url=FRONTEND,
            **overrides,
        )
        app = create_app(settings)
        app.state.rate_limiter = RateLimiter(redis, secret=settings.auth_signing_key)
        sender = sender or FakeEmailSender()
        app.state.email_sender = sender

        async def test_session() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_db_session] = test_session
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("203.0.113.9", 4000)),
            base_url=f"{BASE}/api/v1",
            headers={"Origin": BASE},
        )
        clients.append(client)
        return client, sender

    yield factory
    for client in clients:
        await client.aclose()


def new_email() -> str:
    return f"mail.{uuid.uuid4().hex[:12]}@example.com"


async def signup(client: httpx.AsyncClient, email: str | None = None) -> httpx.Response:
    return await client.post(
        "/auth/signup",
        json={"full_name": "Meera", "email": email or new_email(), "password": PASSWORD},
    )


async def existing_user(session: AsyncSession, **kw: Any) -> User:
    user = User(
        email=kw.pop("email", new_email()),
        password_hash=hash_password(PASSWORD),
        full_name="Existing",
        **kw,
    )
    session.add(user)
    await session.commit()
    return user


# --------------------------------------------------------------------------- #
# Verification (5.4)
# --------------------------------------------------------------------------- #
async def test_signup_sends_a_link_that_verifies_the_email(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    client, sender = await make_client()
    email = new_email()
    response = await signup(client, email)
    assert response.status_code == 201
    assert response.json()["verification_email_sent"] is True
    assert response.json()["is_email_verified"] is False

    (message,) = sender.sent
    assert message.to == email
    assert f"{FRONTEND}/verify-email#token=" in message.text  # fragment: never sent to servers
    token = sender.token()
    stored = await session.scalar(select(AuthToken).where(AuthToken.purpose == "email_verify"))
    assert stored is not None and stored.token_hash != token and len(stored.token_hash) == 64

    verified = await client.post("/auth/email/verify", json={"token": token})
    assert verified.status_code == 200, verified.text
    assert verified.json()["is_email_verified"] is True
    assert (await client.get("/auth/me")).json()["is_email_verified"] is True

    again = await client.post("/auth/email/verify", json={"token": token})
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "invalid_token"


async def test_signup_never_claims_an_email_it_could_not_send(make_client: ClientFactory) -> None:
    for sender in (FakeEmailSender(available=False), FakeEmailSender(fail=True)):
        client, _ = await make_client(sender)
        response = await signup(client)
        assert response.status_code == 201  # the account still works
        assert response.json()["verification_email_sent"] is False


@pytest.mark.parametrize(
    "token",
    ["x" * 43, "not-a-real-token-at-all-but-long-enough"],
)
async def test_unknown_tokens_are_rejected(make_client: ClientFactory, token: str) -> None:
    client, _ = await make_client()
    response = await client.post("/auth/email/verify", json={"token": token})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_token"


@pytest.mark.parametrize("token", ["short", "has spaces in it!!!!!!!", "a" * 200])
async def test_malformed_tokens_are_validation_errors(
    make_client: ClientFactory, token: str
) -> None:
    client, _ = await make_client()
    response = await client.post("/auth/email/verify", json={"token": token})
    assert response.status_code == 422


async def test_expired_link_and_changed_email_are_rejected(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    client, sender = await make_client()
    user_id = uuid.UUID((await signup(client)).json()["id"])
    await session.execute(
        update(AuthToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()
    assert (
        await client.post("/auth/email/verify", json={"token": sender.token()})
    ).status_code == 400

    assert (await client.post("/auth/email/resend")).json() == {
        "sent": True,
        "already_verified": False,
    }
    user = await session.get(User, user_id)
    assert user is not None
    user.email = new_email()  # the address changed after the link was sent
    await session.commit()
    assert (
        await client.post("/auth/email/verify", json={"token": sender.token()})
    ).status_code == 400


async def test_resend_retires_older_links(make_client: ClientFactory) -> None:
    client, sender = await make_client()
    await signup(client)
    first = sender.token()
    assert (await client.post("/auth/email/resend")).status_code == 200
    second = sender.token()
    assert (await client.post("/auth/email/verify", json={"token": first})).status_code == 400
    assert (await client.post("/auth/email/verify", json={"token": second})).status_code == 200
    status = await client.post("/auth/email/resend")
    assert status.json() == {"sent": False, "already_verified": True}


async def test_resend_rules(make_client: ClientFactory) -> None:
    client, _ = await make_client()
    assert (await client.post("/auth/email/resend")).status_code == 401  # signed out
    await signup(client)
    statuses = [(await client.post("/auth/email/resend")).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]

    down, _ = await make_client(FakeEmailSender(available=False))
    await signup(down)
    response = await down.post("/auth/email/resend")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "email_unavailable"


# --------------------------------------------------------------------------- #
# Password recovery (5.5)
# --------------------------------------------------------------------------- #
async def test_forgot_password_answers_identically_for_unknown_emails(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    client, sender = await make_client()
    user = await existing_user(session)
    inactive = await existing_user(session, is_active=False)

    known = await client.post("/auth/password/forgot", json={"email": user.email})
    unknown = await client.post("/auth/password/forgot", json={"email": new_email()})
    disabled = await client.post("/auth/password/forgot", json={"email": inactive.email})
    assert known.status_code == unknown.status_code == disabled.status_code == 202
    assert known.json() == unknown.json() == disabled.json()
    assert [m.to for m in sender.sent] == [user.email]  # only the real, active account
    assert f"{FRONTEND}/reset-password#token=" in sender.sent[0].text


async def test_forgot_password_without_email_provider_is_503_for_everyone(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    client, _ = await make_client(FakeEmailSender(available=False))
    user = await existing_user(session)
    for email in (user.email, new_email()):
        response = await client.post("/auth/password/forgot", json={"email": email})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "email_unavailable"


async def test_reset_sets_the_password_and_signs_out_everywhere(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    other_device, _ = await make_client()
    client, sender = await make_client()
    email = new_email()
    assert (await signup(other_device, email)).status_code == 201

    await client.post("/auth/password/forgot", json={"email": email})
    token = sender.token()
    weak = await client.post("/auth/password/reset", json={"token": token, "password": "12345678"})
    assert weak.status_code == 422
    assert weak.json()["error"]["details"][0]["loc"] == ["body", "password"]

    reset = await client.post(
        "/auth/password/reset", json={"token": token, "password": NEW_PASSWORD}
    )
    assert reset.status_code == 204, reset.text

    # Every existing session ended.
    assert (await other_device.post("/auth/refresh")).status_code == 401
    # Old password refused, new one works; inbox ownership proven -> verified.
    old = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert old.status_code == 401
    new = await client.post("/auth/login", json={"email": email, "password": NEW_PASSWORD})
    assert new.status_code == 200 and new.json()["is_email_verified"] is True
    # Single use.
    again = await client.post(
        "/auth/password/reset", json={"token": token, "password": "x" + NEW_PASSWORD}
    )
    assert again.status_code == 400


async def test_only_the_newest_reset_link_works_and_links_expire(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    client, sender = await make_client()
    user = await existing_user(session)
    for _ in range(2):
        await client.post("/auth/password/forgot", json={"email": user.email})
    first, second = sender.token(0), sender.token(1)
    body = {"password": NEW_PASSWORD}
    assert (
        await client.post("/auth/password/reset", json={"token": first} | body)
    ).status_code == 400

    await session.execute(
        update(AuthToken)
        .where(AuthToken.purpose == "password_reset", AuthToken.used_at.is_(None))
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()
    assert (
        await client.post("/auth/password/reset", json={"token": second} | body)
    ).status_code == 400


async def test_verify_token_cannot_reset_a_password(
    make_client: ClientFactory,
) -> None:
    client, sender = await make_client()
    await signup(client)
    verify_token = sender.token()
    response = await client.post(
        "/auth/password/reset", json={"token": verify_token, "password": NEW_PASSWORD}
    )
    assert response.status_code == 400


async def test_forgot_password_is_rate_limited(
    make_client: ClientFactory, session: AsyncSession
) -> None:
    client, _ = await make_client()
    user = await existing_user(session)
    statuses = [
        (await client.post("/auth/password/forgot", json={"email": user.email})).status_code
        for _ in range(4)
    ]
    assert statuses == [202, 202, 202, 429]


async def test_reset_clears_the_callers_cookies(make_client: ClientFactory) -> None:
    client, sender = await make_client()
    email = new_email()
    await signup(client, email)
    await client.post("/auth/password/forgot", json={"email": email})
    response = await client.post(
        "/auth/password/reset", json={"token": sender.token(), "password": NEW_PASSWORD}
    )
    cleared = [h for h in response.headers.get_list("set-cookie") if "max-age=0" in h.lower()]
    assert any(h.startswith(f"{REFRESH_COOKIE}=") for h in cleared)


async def test_tokens_never_reach_the_logs(
    make_client: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    client, sender = await make_client()
    caplog.set_level(logging.DEBUG)
    email = new_email()
    await signup(client, email)
    await client.post("/auth/email/verify", json={"token": sender.token()})
    await client.post("/auth/password/forgot", json={"email": email})
    await client.post(
        "/auth/password/reset", json={"token": sender.token(), "password": NEW_PASSWORD}
    )
    logged = "\n".join(str(vars(r)) for r in caplog.records)
    for message in sender.sent:
        assert re.search(r"#token=([A-Za-z0-9_-]+)", message.text).group(1) not in logged  # type: ignore[union-attr]
    assert NEW_PASSWORD not in logged and email not in logged
