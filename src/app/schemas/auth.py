"""Schemas for sign-up, login, tokens, email verification and password reset."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BeforeValidator, EmailStr, Field, StringConstraints

from app.schemas.base import ApiModel

Password = Annotated[
    str,
    Field(
        min_length=8,
        max_length=128,
        description="8 to 128 characters; not trimmed.",
    ),
]
PersonName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
OpaqueToken = Annotated[str, Field(min_length=1)]


class UserRole(StrEnum):
    """What an account may do."""

    TENANT = "tenant"
    OWNER = "owner"
    MANAGER = "manager"
    ADMIN = "admin"


class DeviceInfo(ApiModel):
    """The device a session starts on."""

    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    platform: str = Field(min_length=1, max_length=50)


TrimmedEmail = Annotated[
    EmailStr, BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v)
]


class RegisterOwnerInput(ApiModel):
    """Fields set when an Owner signs up with a password."""

    name: PersonName
    email: TrimmedEmail
    password: Password
    device: DeviceInfo


class LoginInput(ApiModel):
    """Email and password of a login."""

    email: TrimmedEmail
    password: str = Field(min_length=1)
    device: DeviceInfo


class GoogleAuthInput(ApiModel):
    """A Google ID token used to sign up or log in."""

    id_token: OpaqueToken
    device: DeviceInfo


class RefreshInput(ApiModel):
    """The refresh token to exchange for a new token pair."""

    refresh_token: OpaqueToken


class AuthTokens(ApiModel):
    """An access token and a refresh token."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"]
    expires_in: int = Field(le=900, description="Lifetime of the access token.")


class Account(ApiModel):
    """The caller's account and sign-in methods."""

    id: UUID
    name: str
    email: EmailStr
    role: UserRole
    email_verified: bool
    has_password: bool
    google_email: str | None = Field(
        description="Null when no Google account is linked."
    )

    @classmethod
    def from_user(cls, user: Any) -> Account:
        """Build the account view of a `UserAccount`."""
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            email_verified=user.email_verified,
            has_password=user.password_hash is not None,
            google_email=None,
        )


class AuthSession(AuthTokens):
    """Tokens of a new session together with its account."""

    account: Account


class EmailVerificationSent(ApiModel):
    """When another verification code may be requested."""

    resend_available_at: datetime


class EmailConfirmationInput(ApiModel):
    """The 6-digit code emailed to the account."""

    # \d would also match non-ASCII digits, so validation uses [0-9]; the
    # published pattern keeps the portable \d form.
    code: str = Field(pattern=r"^[0-9]{6}$", json_schema_extra={"pattern": r"^\d{6}$"})


class PasswordResetRequestInput(ApiModel):
    """The email to send a password-reset link to."""

    email: EmailStr


class TokenInput(ApiModel):
    """An opaque token from a link."""

    token: OpaqueToken


class PasswordResetPreview(ApiModel):
    """The account a password-reset link belongs to."""

    email: EmailStr


class PasswordResetInput(ApiModel):
    """A password-reset token and the new password."""

    token: OpaqueToken
    new_password: Password


class AddLocalPasswordInput(ApiModel):
    """Adds a password to a Google account."""

    google_id_token: str = Field(
        min_length=1, description="Fresh Google ID token of the linked Google account."
    )
    password: Password


class LinkGoogleInput(ApiModel):
    """A Google ID token of the account to link."""

    id_token: OpaqueToken
