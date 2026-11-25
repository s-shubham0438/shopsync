"""Auth request/response schemas (Milestone 5.2)."""

import uuid

import pytest
from pydantic import ValidationError

from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, UserOut


def test_email_is_validated_and_lowercased() -> None:
    req = SignupRequest(full_name="A", email="  Asha.Rao@Example.COM ", password="pw-long-enough")
    assert req.email == "asha.rao@example.com"


@pytest.mark.parametrize("email", ["plain", "a@b", "a@@b.com", "a b@c.com", "x" * 310 + "@a.com"])
def test_bad_emails_rejected(email: str) -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email=email, password="x")


def test_name_whitespace_is_collapsed_but_password_is_kept_exactly() -> None:
    req = SignupRequest(full_name="  Asha \t  Rao ", email="a@example.com", password="  pw  pw  ")
    assert req.full_name == "Asha Rao"
    assert req.password == "  pw  pw  "


@pytest.mark.parametrize(
    "body",
    [
        {"full_name": "   ", "email": "a@example.com", "password": "x"},
        {"full_name": "A" * 201, "email": "a@example.com", "password": "x"},
        {"full_name": "A", "email": "a@example.com", "password": ""},
        {"full_name": "A", "email": "a@example.com", "password": "x" * 1025},
        {"full_name": "A", "email": "a@example.com", "password": "x", "is_admin": True},
    ],
)
def test_signup_rejects(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SignupRequest.model_validate(body)


def test_user_out_exposes_only_safe_fields() -> None:
    user = User(
        id=uuid.uuid7(),
        email="a@example.com",
        phone=None,
        full_name="A",
        password_hash="$argon2id$secret",
        is_email_verified=False,
        is_phone_verified=False,
        is_active=True,
    )
    dumped = UserOut.model_validate(user).model_dump()
    assert set(dumped) == {
        "id", "email", "phone", "full_name", "is_email_verified", "is_phone_verified",
    }  # fmt: skip
    assert "argon2" not in str(dumped)
