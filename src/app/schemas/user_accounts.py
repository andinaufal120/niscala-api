"""Schemas for the Admin view of user accounts."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import EmailStr, Field

from app.schemas.auth import PersonName, UserRole
from app.schemas.base import ApiModel
from app.schemas.sessions import LoginMethod


class UserAccountStatus(StrEnum):
    """Status of an account as shown to an Admin."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETED = "deleted"


class EditableAccountStatus(StrEnum):
    """Statuses an Admin can set; deleted is reached only by deleting the account."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class UserAccountInput(ApiModel):
    """Fields an Admin can change on an account."""

    name: PersonName
    email: EmailStr = Field(
        description="Compared case-insensitively. A value different from the current "
        "email starts a pending change; the current email cancels a pending one."
    )
    status: EditableAccountStatus


class UserAccountSummary(ApiModel):
    """An account as listed to an Admin."""

    id: UUID
    name: str
    email: str
    role: UserRole
    status: UserAccountStatus


class UserAccountList(ApiModel):
    """User accounts matching a search."""

    items: list[UserAccountSummary]


class AccountPropertyRef(ApiModel):
    """A property an account is linked to."""

    id: UUID
    name: str


class AccountTenancy(ApiModel):
    """The room a Tenant account currently leases."""

    property_name: str
    room_number: str
    lease_end_date: date | None


class UserAccount(ApiModel):
    """An account with its login details and what it is linked to."""

    id: UUID
    name: str
    email: str = Field(description="The email the account logs in with.")
    pending_email: str | None = Field(
        description="New email awaiting verification; null when none."
    )
    pending_email_expires_at: datetime | None = Field(
        description="Present only with pendingEmail."
    )
    role: UserRole
    status: UserAccountStatus
    registered_at: datetime
    last_login_at: datetime | None
    login_methods: list[LoginMethod]
    properties: list[AccountPropertyRef] = Field(
        description="Owned (Owner) or assigned (Manager); empty for other roles."
    )
    active_lease_count: int = Field(
        ge=0,
        description="Owner: across owned properties. Tenant: 0 or 1. Otherwise 0.",
    )
    tenancy: AccountTenancy | None = Field(
        description="Tenant with an active lease; otherwise null."
    )
