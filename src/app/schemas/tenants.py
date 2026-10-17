"""Schemas for tenants, their lease, emergency contacts and invitation."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.schemas.base import ApiModel

PHONE_DESCRIPTION = "Indonesian mobile number; returned as digits starting with 08."


class BillingCycle(StrEnum):
    """How often a lease is billed."""

    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"


class TenantAccountStatus(StrEnum):
    """Whether the Tenant has activated their account through the invitation."""

    NOT_ACTIVATED = "notActivated"
    ACTIVE = "active"


class EmergencyContact(ApiModel):
    """A person to contact about the Tenant in an emergency."""

    name: str = Field(min_length=1)
    relationship: str = Field(min_length=1)
    phone: str = Field(min_length=1, description=PHONE_DESCRIPTION)


class LeaseInput(ApiModel):
    """Lease fields set when adding or editing a tenant."""

    start_date: date | None = None
    end_date: date | None = Field(default=None, description="Not before startDate.")
    billing_cycle: BillingCycle = BillingCycle.MONTHLY
    rent: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Per billing cycle, in rupiah: the amount of one bill. When omitted, "
            "a monthly lease uses the room's base rate; other cycles require it."
        ),
    )
    grace_period_days: int = Field(default=0, ge=0)


class TenantInput(ApiModel):
    """Fields set when editing a tenant."""

    name: str = Field(min_length=1)
    phone: str = Field(min_length=1, description=PHONE_DESCRIPTION)
    occupation: str | None = None
    emergency_contacts: list[EmergencyContact] = Field(
        default=[],
        max_length=4,
        description=(
            "2 to 4 contacts. May be empty only while the Tenant's account is not "
            "activated; the Tenant then completes them during activation. "
            "Exactly 1 is rejected."
        ),
    )
    lease: LeaseInput = Field(default_factory=LeaseInput)


class NewTenantInput(TenantInput):
    """Fields set when adding a tenant to a room."""

    room_id: UUID = Field(description="A vacant room of the property.")


class RoomRef(ApiModel):
    """The room a tenant occupies."""

    id: UUID
    number: str


class Lease(ApiModel):
    """A tenant's lease."""

    start_date: date | None
    end_date: date | None
    rent: int = Field(description="Per billing cycle, in rupiah.")
    billing_cycle: BillingCycle
    grace_period_days: int
    next_bill_date: date | None


class TenantInvitation(ApiModel):
    """The link a Tenant uses to activate their account."""

    url: str | None = Field(
        description="Present while the invitation is unused and not expired."
    )
    created_at: datetime
    expires_at: datetime
    expired: bool


class Tenant(ApiModel):
    """A tenant with their room, lease, emergency contacts and invitation."""

    id: UUID
    name: str
    phone: str = Field(description=PHONE_DESCRIPTION)
    email: str | None
    occupation: str | None
    account_status: TenantAccountStatus
    room: RoomRef
    lease: Lease
    emergency_contacts: list[EmergencyContact]
    invitation: TenantInvitation | None = Field(
        description="Present while the account is not activated."
    )


class TenantSummary(ApiModel):
    """A tenant as shown in the tenant list."""

    id: UUID
    name: str
    room: RoomRef
    account_status: TenantAccountStatus
    billing_cycle: BillingCycle
    lease_end_date: date | None
    invitation_expires_at: datetime | None = Field(
        description="Present while the account is not activated."
    )


class TenantList(ApiModel):
    """Tenants of a property."""

    items: list[TenantSummary]
