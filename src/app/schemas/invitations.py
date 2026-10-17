"""Schemas for previewing, activating and accepting invitations."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import EmailStr, Field

from app.schemas.auth import DeviceInfo, OpaqueToken, Password, PersonName, UserRole
from app.schemas.base import ApiModel
from app.schemas.tenants import EmergencyContact


class InvitationRole(StrEnum):
    """The role an invitation grants."""

    TENANT = "tenant"
    MANAGER = "manager"


class InvitationLinkStatus(StrEnum):
    """Whether an invitation link can still be used."""

    VALID = "valid"
    EXPIRED = "expired"
    USED = "used"


class InvitationBlocker(StrEnum):
    """Why an existing account cannot accept an invitation."""

    ROLE_MISMATCH = "roleMismatch"
    ACTIVE_LEASE = "activeLease"


class InvitationProperty(ApiModel):
    """A property an invitation is for."""

    name: str
    address: str


class InvitationPreview(ApiModel):
    """What an invitation link is for and whether it is still valid."""

    status: InvitationLinkStatus
    role: InvitationRole
    inviter_name: str
    properties: list[InvitationProperty] = Field(
        description="One for a Tenant, one or more for a Manager."
    )
    room_number: str | None = Field(description="Present for a Tenant invitation.")
    expires_at: datetime
    name: str = Field(description="Pre-filled by management.")
    emergency_contacts_required: bool = Field(
        description="True when a Tenant's emergency contacts are still missing."
    )


class InvitationPasswordActivationInput(ApiModel):
    """Fields set when activating an invitation with a password."""

    token: OpaqueToken
    name: PersonName
    email: EmailStr | None = None
    password: Password
    emergency_contacts: list[EmergencyContact] | None = Field(
        default=None,
        min_length=2,
        max_length=4,
        description="Required when the invitation preview says they are missing.",
    )
    device: DeviceInfo


class InvitationGoogleActivationInput(ApiModel):
    """Fields set when activating an invitation with Google."""

    token: OpaqueToken
    name: PersonName
    id_token: OpaqueToken
    emergency_contacts: list[EmergencyContact] | None = Field(
        default=None,
        min_length=2,
        max_length=4,
        description="Required when the invitation preview says they are missing.",
    )
    device: DeviceInfo


class ActiveLeaseSummary(ApiModel):
    """The active lease that prevents a Tenant from accepting an invitation."""

    property_name: str
    room_number: str
    end_date: date | None


class InvitationAcceptancePreview(ApiModel):
    """Whether the caller's account can accept an invitation."""

    invitation: InvitationPreview
    account_name: str
    account_email: EmailStr
    account_role: UserRole
    can_accept: bool = Field(
        description="True only when the link is valid and there is no blocker."
    )
    blocker: InvitationBlocker | None
    active_lease: ActiveLeaseSummary | None = Field(
        description="Present when the blocker is activeLease."
    )
