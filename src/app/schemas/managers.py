"""Schemas for managers, their assigned properties and invitation."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.base import ApiModel
from app.schemas.tenants import PHONE_DESCRIPTION


class ManagerAccountStatus(StrEnum):
    """Whether the Manager has activated their account through the invitation."""

    NOT_ACTIVATED = "notActivated"
    ACTIVE = "active"


class ManagerInput(ApiModel):
    """Fields an Owner sets when adding or editing a manager."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    nickname: str | None = Field(
        default=None, description="How the Owner calls the Manager; blank means none."
    )
    phone: str = Field(min_length=1, description=PHONE_DESCRIPTION)
    property_ids: list[UUID] = Field(
        min_length=1,
        description=(
            "Properties of the Owner the Manager may access; at least one, "
            "no duplicates."
        ),
    )


class ManagerProperty(ApiModel):
    """A property assigned to a Manager."""

    id: UUID
    name: str
    address: str


class ManagerInvitation(ApiModel):
    """The link a Manager uses to activate their account."""

    url: str | None = Field(
        description="Present while the invitation is unused and not expired."
    )
    created_at: datetime
    expires_at: datetime
    expired: bool


class Manager(ApiModel):
    """A manager with their assigned properties and invitation."""

    id: UUID
    name: str
    nickname: str | None
    phone: str = Field(description=PHONE_DESCRIPTION)
    email: str | None = Field(
        description="Null until the Manager sets it during activation."
    )
    account_status: ManagerAccountStatus
    properties: list[ManagerProperty]
    invitation: ManagerInvitation | None = Field(
        description="Present while the account is not activated."
    )


class ManagerSummary(ApiModel):
    """A manager as shown in the manager list."""

    id: UUID
    name: str
    nickname: str | None
    phone: str = Field(description=PHONE_DESCRIPTION)
    email: str | None = Field(
        description="Null until the Manager sets it during activation."
    )
    account_status: ManagerAccountStatus
    properties: list[ManagerProperty]


class ManagerList(ApiModel):
    """The Owner's managers."""

    items: list[ManagerSummary]
