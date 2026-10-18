"""Adding, listing and reading tenants."""

import logging
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import get_accessible_property
from app.errors import ApiError
from app.models import EmergencyContact as ContactRow
from app.models import Invitation as InvitationRow
from app.models import Lease as LeaseRow
from app.models import Room as RoomRow
from app.models import Tenant as TenantRow
from app.models import UserAccount
from app.schemas.auth import UserRole
from app.schemas.tenants import (
    BillingCycle,
    EmergencyContact,
    Lease,
    NewTenantInput,
    RoomRef,
    Tenant,
    TenantAccountStatus,
    TenantInvitation,
    TenantList,
    TenantSummary,
)
from app.services import invitations
from app.services.leases import next_bill_date
from app.services.rooms import natural_number_key

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Asia/Jakarta")
PHONE_PATTERN = re.compile(r"(?:08|628)[0-9]{8,11}")

type Found = tuple[TenantRow, UserAccount, LeaseRow, RoomRow]


def _invalid(field: str) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", field=field)


def _phone(value: str, field: str) -> str:
    """Strip spaces and dashes and return the number as digits starting with 08."""
    digits = re.sub(r"[\s-]", "", value)
    if not PHONE_PATTERN.fullmatch(digits):
        raise _invalid(field)
    return "08" + digits.removeprefix("628").removeprefix("08")


def _text(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise _invalid(field)
    return text


def _contacts(data: NewTenantInput) -> list[EmergencyContact]:
    if len(data.emergency_contacts) == 1:
        raise _invalid("emergencyContacts")
    contacts = []
    for index, contact in enumerate(data.emergency_contacts):
        prefix = f"emergencyContacts.{index}"
        contacts.append(
            EmergencyContact(
                name=_text(contact.name, f"{prefix}.name"),
                relationship=_text(contact.relationship, f"{prefix}.relationship"),
                phone=_phone(contact.phone, f"{prefix}.phone"),
            )
        )
    return contacts


def _rent(data: NewTenantInput, room: RoomRow) -> int:
    lease = data.lease
    if lease.rent is not None:
        return lease.rent
    if lease.billing_cycle != BillingCycle.MONTHLY:
        raise _invalid("lease.rent")
    return room.base_rate


def _today() -> date:
    return datetime.now(TIMEZONE).date()


def _latest_invitations(
    db: Session, tenant_ids: Iterable[UUID]
) -> dict[UUID, InvitationRow]:
    rows = db.scalars(
        select(InvitationRow)
        .where(InvitationRow.tenant_id.in_(list(tenant_ids)))
        .order_by(InvitationRow.created_at, InvitationRow.id)
    )
    return {row.tenant_id: row for row in rows}


def _invitation(row: InvitationRow | None) -> TenantInvitation | None:
    if row is None:
        return None
    now = datetime.now(UTC)
    unusable = row.used_at is not None or row.invalidated_at is not None
    expired = not unusable and row.expires_at <= now
    usable = not unusable and not expired
    return TenantInvitation(
        url=invitations.invitation_url(invitations.reveal_token(row))
        if usable
        else None,
        created_at=row.created_at,
        expires_at=row.expires_at,
        expired=expired,
    )


def _status(tenant: TenantRow) -> TenantAccountStatus:
    if tenant.activated_at is None:
        return TenantAccountStatus.NOT_ACTIVATED
    return TenantAccountStatus.ACTIVE


def _expiry(tenant: TenantRow, invitation: InvitationRow | None) -> datetime | None:
    if tenant.activated_at is not None or invitation is None:
        return None
    return invitation.expires_at


def _detail(db: Session, found: Found) -> Tenant:
    tenant, user, lease, room = found
    contacts = db.scalars(
        select(ContactRow)
        .where(ContactRow.tenant_id == tenant.user_id)
        .order_by(ContactRow.position)
    )
    invitation = None
    if tenant.activated_at is None:
        invitation = _invitation(
            _latest_invitations(db, [tenant.user_id]).get(tenant.user_id)
        )
    cycle = BillingCycle(lease.billing_cycle)
    return Tenant(
        id=user.id,
        name=user.name,
        phone=tenant.phone,
        email=user.email,
        occupation=tenant.occupation,
        account_status=_status(tenant),
        room=RoomRef(id=room.id, number=room.number),
        lease=Lease(
            start_date=lease.start_date,
            end_date=lease.end_date,
            rent=lease.rent,
            billing_cycle=cycle,
            grace_period_days=lease.grace_period_days,
            next_bill_date=next_bill_date(
                lease.start_date, lease.end_date, cycle, _today()
            ),
        ),
        emergency_contacts=[
            EmergencyContact(name=c.name, relationship=c.relationship, phone=c.phone)
            for c in contacts
        ],
        invitation=invitation,
    )


def _find(db: Session, *conditions) -> list[Found]:
    """Select live tenants with their active lease and room."""
    rows = db.execute(
        select(TenantRow, UserAccount, LeaseRow, RoomRow)
        .join(UserAccount, UserAccount.id == TenantRow.user_id)
        .join(LeaseRow, LeaseRow.tenant_id == TenantRow.user_id)
        .join(RoomRow, RoomRow.id == LeaseRow.room_id)
        .where(TenantRow.deleted_at.is_(None), LeaseRow.ended_at.is_(None), *conditions)
    )
    return [tuple(row) for row in rows]


def create_tenant(
    db: Session, user: UserAccount, property_id: UUID, data: NewTenantInput
) -> Tenant:
    """Add a tenant to a vacant room of a property and invite them.

    Checks in order: access (404 PROPERTY_NOT_FOUND), view-only property (403
    PROPERTY_READ_ONLY), room of the property (404 ROOM_NOT_FOUND), view-only
    room (403 ROOM_READ_ONLY), room already leased (409 ROOM_NOT_VACANT), field
    rules (422 VALIDATION_FAILED). Creates the tenant account, emergency
    contacts and an active lease. A failure to create the invitation is logged
    and leaves the tenant saved without one; any other failure saves nothing.
    """
    parent = get_accessible_property(db, user, property_id)
    if parent.view_only:
        raise ApiError(403, "PROPERTY_READ_ONLY")
    room = db.scalars(
        select(RoomRow).where(
            RoomRow.id == data.room_id,
            RoomRow.property_id == parent.id,
            RoomRow.deleted_at.is_(None),
        )
    ).first()
    if room is None:
        raise ApiError(404, "ROOM_NOT_FOUND")
    if room.view_only:
        raise ApiError(403, "ROOM_READ_ONLY")
    leased = db.scalars(
        select(LeaseRow.id)
        .where(LeaseRow.room_id == room.id, LeaseRow.ended_at.is_(None))
        .limit(1)
    ).first()
    if leased is not None:
        raise ApiError(409, "ROOM_NOT_VACANT", field="roomId")

    name = _text(data.name, "name")
    phone = _phone(data.phone, "phone")
    occupation = (data.occupation or "").strip() or None
    contacts = _contacts(data)
    lease = data.lease
    if (
        lease.start_date is not None
        and lease.end_date is not None
        and lease.end_date < lease.start_date
    ):
        raise _invalid("lease.endDate")
    rent = _rent(data, room)

    account = UserAccount(
        name=name,
        email=None,
        password_hash=None,
        role=UserRole.TENANT,
        email_verified=False,
    )
    db.add(account)
    db.flush()
    tenant = TenantRow(user_id=account.id, phone=phone, occupation=occupation)
    db.add(tenant)
    db.flush()
    db.add_all(
        ContactRow(
            tenant_id=account.id,
            name=c.name,
            relationship=c.relationship,
            phone=c.phone,
            position=position,
        )
        for position, c in enumerate(contacts)
    )
    stored_lease = LeaseRow(
        tenant_id=account.id,
        room_id=room.id,
        start_date=lease.start_date,
        end_date=lease.end_date,
        billing_cycle=lease.billing_cycle.value,
        rent=rent,
        grace_period_days=lease.grace_period_days,
    )
    db.add(stored_lease)
    db.flush()
    try:
        with db.begin_nested():
            invitations.create_invitation(db, account.id)
    except Exception:
        logger.exception("Could not create the invitation of tenant %s", account.id)
    return _detail(db, (tenant, account, stored_lease, room))


def list_tenants(db: Session, user: UserAccount, property_id: UUID) -> TenantList:
    """List the tenants with an active lease in a property, by room number then name."""
    parent = get_accessible_property(db, user, property_id)
    found = sorted(
        _find(db, RoomRow.property_id == parent.id),
        key=lambda f: (natural_number_key(f[3].number), f[1].name, f[1].id),
    )
    latest = _latest_invitations(db, [f[0].user_id for f in found])
    return TenantList(
        items=[
            TenantSummary(
                id=account.id,
                name=account.name,
                room=RoomRef(id=room.id, number=room.number),
                account_status=_status(tenant),
                billing_cycle=BillingCycle(lease.billing_cycle),
                lease_end_date=lease.end_date,
                invitation_expires_at=_expiry(tenant, latest.get(account.id)),
            )
            for tenant, account, lease, room in found
        ]
    )


def get_tenant(db: Session, user: UserAccount, tenant_id: UUID) -> Tenant:
    """Return a tenant with an active lease in a property the user may access.

    Raises 404 TENANT_NOT_FOUND for an unknown, deleted, lease-less or
    inaccessible tenant.
    """
    found = _find(db, TenantRow.user_id == tenant_id)
    if not found:
        raise ApiError(404, "TENANT_NOT_FOUND")
    try:
        get_accessible_property(db, user, found[0][3].property_id)
    except ApiError:
        raise ApiError(404, "TENANT_NOT_FOUND") from None
    return _detail(db, found[0])
