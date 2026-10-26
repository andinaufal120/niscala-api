"""Adding, listing, reading, editing and deleting tenants, and regenerating invitations."""

import logging
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.access import get_accessible_property
from app.errors import ApiError
from app.models import EmergencyContact as ContactRow
from app.models import Invitation as InvitationRow
from app.models import Lease as LeaseRow
from app.models import Property as PropertyRow
from app.models import Room as RoomRow
from app.models import Tenant as TenantRow
from app.models import UserAccount, UserSession
from app.schemas.auth import UserRole
from app.schemas.tenants import (
    BillingCycle,
    CurrentLease,
    CurrentLeaseProperty,
    CurrentLeaseResult,
    CurrentLeaseRoom,
    EmergencyContact,
    Lease,
    NewTenantInput,
    RoomRef,
    Tenant,
    TenantAccountStatus,
    TenantInput,
    TenantInvitation,
    TenantList,
    TenantSummary,
)
from app.services import invitations, sessions
from app.services.leases import next_bill_date
from app.services.rooms import natural_number_key

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Asia/Jakarta")
PHONE_PATTERN = re.compile(r"(?:08|628)[0-9]{8,11}")

type Found = tuple[TenantRow, UserAccount, LeaseRow, RoomRow]


def _invalid(field: str) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", field=field)


def normalize_phone(value: str, field: str) -> str:
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


def clean_contacts(submitted: list[EmergencyContact]) -> list[EmergencyContact]:
    """Trim texts and normalize phones; a single contact is refused."""
    if len(submitted) == 1:
        raise _invalid("emergencyContacts")
    contacts = []
    for index, contact in enumerate(submitted):
        prefix = f"emergencyContacts.{index}"
        contacts.append(
            EmergencyContact(
                name=_text(contact.name, f"{prefix}.name"),
                relationship=_text(contact.relationship, f"{prefix}.relationship"),
                phone=normalize_phone(contact.phone, f"{prefix}.phone"),
            )
        )
    return contacts


def _rent(data: TenantInput, room: RoomRow) -> int:
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


def get_current_lease(db: Session, user: UserAccount) -> CurrentLeaseResult:
    """Return the caller's active lease with its room and property.

    The lease is null when the caller has no active lease. A view-only room or
    property does not hide it.
    """
    found = _find(db, TenantRow.user_id == user.id)
    if not found:
        return CurrentLeaseResult(lease=None)
    _, _, lease, room = found[0]
    parent = db.get(PropertyRow, room.property_id)
    return CurrentLeaseResult(
        lease=CurrentLease(
            room=CurrentLeaseRoom(
                id=room.id,
                number=room.number,
                facilities=room.facilities,
                length_m=room.length_m,
                width_m=room.width_m,
            ),
            property=CurrentLeaseProperty(
                id=parent.id, name=parent.name, address=parent.address
            ),
            start_date=lease.start_date,
            end_date=lease.end_date,
            rent=lease.rent,
            billing_cycle=BillingCycle(lease.billing_cycle),
        )
    )


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
    phone = normalize_phone(data.phone, "phone")
    occupation = (data.occupation or "").strip() or None
    contacts = clean_contacts(data.emergency_contacts)
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


def _find_accessible(db: Session, user: UserAccount, tenant_id: UUID) -> Found:
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
    return found[0]


def get_tenant(db: Session, user: UserAccount, tenant_id: UUID) -> Tenant:
    """Return a tenant with an active lease in a property the user may access.

    Raises 404 TENANT_NOT_FOUND for an unknown, deleted, lease-less or
    inaccessible tenant.
    """
    return _detail(db, _find_accessible(db, user, tenant_id))


def update_tenant(
    db: Session, user: UserAccount, tenant_id: UUID, data: TenantInput
) -> Tenant:
    """Edit a tenant and their active lease; the room cannot change.

    Checks in order: tenant access (404 TENANT_NOT_FOUND), view-only property
    (403 PROPERTY_READ_ONLY), view-only room (403 ROOM_READ_ONLY), field rules
    (422 VALIDATION_FAILED). An activated tenant must keep at least two
    emergency contacts. The emergency contacts are replaced wholesale. A
    failure saves nothing.
    """
    found = _find_accessible(db, user, tenant_id)
    tenant, account, stored_lease, room = found
    if get_accessible_property(db, user, room.property_id).view_only:
        raise ApiError(403, "PROPERTY_READ_ONLY")
    if room.view_only:
        raise ApiError(403, "ROOM_READ_ONLY")

    name = _text(data.name, "name")
    phone = normalize_phone(data.phone, "phone")
    occupation = (data.occupation or "").strip() or None
    contacts = clean_contacts(data.emergency_contacts)
    if tenant.activated_at is not None and not contacts:
        raise _invalid("emergencyContacts")
    lease = data.lease
    if (
        lease.start_date is not None
        and lease.end_date is not None
        and lease.end_date < lease.start_date
    ):
        raise _invalid("lease.endDate")
    rent = _rent(data, room)

    account.name = name
    tenant.phone = phone
    tenant.occupation = occupation
    stored_lease.start_date = lease.start_date
    stored_lease.end_date = lease.end_date
    stored_lease.billing_cycle = lease.billing_cycle.value
    stored_lease.rent = rent
    stored_lease.grace_period_days = lease.grace_period_days
    db.execute(delete(ContactRow).where(ContactRow.tenant_id == tenant.user_id))
    db.flush()
    db.add_all(
        ContactRow(
            tenant_id=tenant.user_id,
            name=c.name,
            relationship=c.relationship,
            phone=c.phone,
            position=position,
        )
        for position, c in enumerate(contacts)
    )
    db.flush()
    return _detail(db, found)


def delete_tenant(db: Session, user: UserAccount, tenant_id: UUID) -> None:
    """End a tenant's lease and revoke their access; history is kept.

    Checks in order: tenant access (404 TENANT_NOT_FOUND), view-only property
    (403 PROPERTY_READ_ONLY), view-only room (403 ROOM_READ_ONLY). Marks the
    tenant deleted, ends the active lease, invalidates unused invitations and
    ends every session of the account. A failure saves nothing.
    """
    tenant, _, stored_lease, room = _find_accessible(db, user, tenant_id)
    if get_accessible_property(db, user, room.property_id).view_only:
        raise ApiError(403, "PROPERTY_READ_ONLY")
    if room.view_only:
        raise ApiError(403, "ROOM_READ_ONLY")

    now = datetime.now(UTC)
    tenant.deleted_at = now
    stored_lease.ended_at = now
    db.execute(
        update(InvitationRow)
        .where(
            InvitationRow.tenant_id == tenant_id,
            InvitationRow.used_at.is_(None),
            InvitationRow.invalidated_at.is_(None),
        )
        .values(invalidated_at=now)
    )
    open_sessions = db.scalars(
        select(UserSession).where(
            UserSession.user_id == tenant_id, UserSession.revoked_at.is_(None)
        )
    ).all()
    for session in open_sessions:
        sessions.end_session(db, session)
    db.flush()


def regenerate_invitation(
    db: Session, user: UserAccount, tenant_id: UUID
) -> TenantInvitation:
    """Create a new invitation for a tenant, invalidating the old one.

    Checks in order: tenant access (404 TENANT_NOT_FOUND), tenant already
    activated (409 TENANT_ALREADY_ACTIVE). Allowed while the room or property
    is view-only. A failure leaves the previous invitation valid.
    """
    tenant = _find_accessible(db, user, tenant_id)[0]
    if tenant.activated_at is not None:
        raise ApiError(409, "TENANT_ALREADY_ACTIVE")
    with db.begin_nested():
        row, _ = invitations.create_invitation(db, tenant_id)
    return _invitation(row)
