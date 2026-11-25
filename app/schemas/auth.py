"""Auth request/response contracts (match `User` in frontend/src/api/types.ts).

Emails are validated with email-validator (syntax only, no DNS) and stored lowercase.
Password strength is checked in the service so the message can be user-friendly.
Passwords are never stripped: spaces can be part of a password.
"""

import uuid
from typing import Annotated

from pydantic import AfterValidator, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import APIModel

MAX_PASSWORD_INPUT = 1024  # policy max is 128; this only bounds what we accept to parse


def _lower(value: str) -> str:
    return value.lower()


NormalisedEmail = Annotated[EmailStr, Field(max_length=320), AfterValidator(_lower)]
PasswordInput = Annotated[str, Field(min_length=1, max_length=MAX_PASSWORD_INPUT)]


class _Request(APIModel):
    model_config = ConfigDict(extra="forbid")


class SignupRequest(_Request):
    full_name: str = Field(min_length=1, max_length=200)
    email: NormalisedEmail
    password: PasswordInput

    @field_validator("full_name")
    @classmethod
    def _tidy_name(cls, value: str) -> str:
        tidy = " ".join(value.split())
        if not tidy:
            raise ValueError("Name must not be blank.")
        return tidy


class LoginRequest(_Request):
    email: NormalisedEmail
    password: PasswordInput


class UserOut(APIModel):
    """The user's own safe profile. Never includes the password hash or token data."""

    id: uuid.UUID
    email: str | None
    phone: str | None
    full_name: str | None
    is_email_verified: bool
    is_phone_verified: bool


class SignupResponse(UserOut):
    verification_email_sent: bool = Field(
        description="True only if a verification email was handed to the email provider"
    )


TokenInput = Annotated[str, Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class VerifyEmailRequest(_Request):
    token: TokenInput


class EmailVerificationStatus(APIModel):
    sent: bool
    already_verified: bool


class ForgotPasswordRequest(_Request):
    email: NormalisedEmail


class ResetPasswordRequest(_Request):
    token: TokenInput
    password: PasswordInput


class MessageResponse(APIModel):
    message: str
