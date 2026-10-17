"""Schemas for confirming the caller's identity before a sensitive change."""

from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel


class ReauthenticationPasswordInput(ApiModel):
    """The caller's current password, taken as typed."""

    password: str = Field(min_length=1)


class ReauthenticationGoogleInput(ApiModel):
    """A fresh Google ID token for the caller's account."""

    model_config = ConfigDict(validate_by_name=False)

    id_token: str = Field(min_length=1)


class Reauthentication(ApiModel):
    """How long the caller's re-authentication stays valid."""

    reauthenticated_until: datetime
