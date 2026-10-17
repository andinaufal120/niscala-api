"""Schemas for the caller's sessions and password change."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.auth import Password
from app.schemas.base import ApiModel


class LoginMethod(StrEnum):
    """How a session was started."""

    GOOGLE = "google"
    PASSWORD = "password"


class Session(ApiModel):
    """A signed-in device of the caller."""

    id: UUID
    device_name: str
    platform: str
    login_method: LoginMethod
    last_active_at: datetime
    is_current: bool = Field(description="True for the session making the request.")


class SessionList(ApiModel):
    """The caller's sessions."""

    items: list[Session]


class PasswordChangeInput(ApiModel):
    """The current password and the one to replace it with."""

    model_config = ConfigDict(validate_by_name=False)

    current_password: str = Field(min_length=1)
    new_password: Password


class PasswordChangeResult(ApiModel):
    """Outcome of a password change."""

    has_other_sessions: bool = Field(
        description="True when sessions other than the current one are still signed in."
    )
