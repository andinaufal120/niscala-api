"""Previewing, activating and accepting a Tenant or Manager invitation link."""

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.email import EmailSender
from app.errors import ApiError
from app.models import EmergencyContact as ContactRow
from app.models import (
    Invitation,
    Lease,
    Manager,
    ManagerAssignment,
    Property,
    Room,
    Tenant,
    UserAccount,
)
from app.schemas.auth import Account, AuthSession
from app.schemas.invitations import (
    ActiveLeaseSummary,
    InvitationAcceptancePreview,
    InvitationBlocker,
    InvitationLinkStatus,
    InvitationPasswordActivationInput,
    InvitationPreview,
    InvitationProperty,
    InvitationRole,
)
from app.schemas.sessions import LoginMethod
from app.services.accounts import find_by_email
from app.services.email_verification import send_code
from app.services.passwords import check_password_allowed, hash_password
from app.services.sessions import start_session
from app.services.tenants import clean_contacts

logger = logging.getLogger(__name__)

MIN_CONTACTS = 2


def notify_manager_activated(record: Manager) -> None:
    """Tell interested parties that a Manager record has been activated.

    Called once after an activation or an acceptance has succeeded. A failure
    here is logged and never undoes the activation.
    """


def _notify_manager_activated(db: Session, record: Manager) -> None:
    # Detached, the record keeps its loaded attributes after the request commits.
    db.expunge(record)
    try:
        notify_manager_activated(record)
    except Exception:
        logger.exception("Manager activation notification failed")


def _link_status(
    invitation: Invitation, activated_at: datetime | None
) -> InvitationLinkStatus:
    if (
        invitation.used_at is not None
        or invitation.invalidated_at is not None
        or activated_at is not None
    ):
        return InvitationLinkStatus.USED
    if invitation.expires_at <= datetime.now(UTC):
        return InvitationLinkStatus.EXPIRED
    return InvitationLinkStatus.VALID


class _TenantLink:
    role = InvitationRole.TENANT

    def __init__(self, db: Session, invitation: Invitation) -> None:
        row = db.execute(
            select(Tenant, UserAccount, Room, Property)
            .join(UserAccount, UserAccount.id == Tenant.user_id)
            .join(Lease, Lease.tenant_id == Tenant.user_id)
            .join(Room, Room.id == Lease.room_id)
            .join(Property, Property.id == Room.property_id)
            .where(
                Tenant.user_id == invitation.tenant_id,
                Tenant.deleted_at.is_(None),
                Lease.ended_at.is_(None),
            )
        ).first()
        if row is None:
            raise ApiError(404, "INVITATION_NOT_FOUND")
        self.invitation = invitation
        self.tenant, self.user, self.room, self.property = row
        self.contacts = list(
            db.scalars(select(ContactRow).where(ContactRow.tenant_id == self.user.id))
        )

    @property
    def status(self) -> InvitationLinkStatus:
        return _link_status(self.invitation, self.tenant.activated_at)

    @property
    def contacts_required(self) -> bool:
        return len(self.contacts) < MIN_CONTACTS

    def preview(self, db: Session) -> InvitationPreview:
        owner = db.get(UserAccount, self.property.owner_id)
        return InvitationPreview(
            status=self.status,
            role=self.role,
            inviter_name=owner.name,
            properties=[
                InvitationProperty(
                    name=self.property.name, address=self.property.address
                )
            ],
            room_number=self.room.number,
            expires_at=self.invitation.expires_at,
            name=self.user.name,
            emergency_contacts_required=self.contacts_required,
        )


class _ManagerLink:
    role = InvitationRole.MANAGER

    def __init__(self, db: Session, invitation: Invitation) -> None:
        record = db.get(Manager, invitation.manager_id)
        if record is None or record.deleted_at is not None:
            raise ApiError(404, "INVITATION_NOT_FOUND")
        self.invitation = invitation
        self.record = record
        self.user = db.get(UserAccount, record.user_id)
        self.owner = db.get(UserAccount, record.owner_id)

    @property
    def status(self) -> InvitationLinkStatus:
        return _link_status(self.invitation, self.record.activated_at)

    def preview(self, db: Session) -> InvitationPreview:
        assigned = db.scalars(
            select(Property)
            .join(ManagerAssignment, ManagerAssignment.property_id == Property.id)
            .where(
                ManagerAssignment.manager_id == self.record.user_id,
                Property.owner_id == self.record.owner_id,
                Property.deleted_at.is_(None),
            )
            .order_by(Property.name, Property.id)
        )
        return InvitationPreview(
            status=self.status,
            role=self.role,
            inviter_name=self.owner.name,
            properties=[
                InvitationProperty(name=p.name, address=p.address) for p in assigned
            ],
            room_number=None,
            expires_at=self.invitation.expires_at,
            name=self.user.name,
            emergency_contacts_required=False,
        )


def _find(db: Session, token: str) -> _TenantLink | _ManagerLink:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    invitation = db.scalars(
        select(Invitation).where(Invitation.token_hash == token_hash)
    ).first()
    if invitation is None:
        raise ApiError(404, "INVITATION_NOT_FOUND")
    if invitation.tenant_id is not None:
        return _TenantLink(db, invitation)
    return _ManagerLink(db, invitation)


def _require_usable(found: _TenantLink | _ManagerLink) -> None:
    if found.status == InvitationLinkStatus.USED:
        raise ApiError(409, "INVITATION_USED")
    if found.status == InvitationLinkStatus.EXPIRED:
        raise ApiError(409, "INVITATION_EXPIRED")


def preview_invitation(db: Session, token: str) -> InvitationPreview:
    """Describe an invitation link in any state.

    Raises 404 INVITATION_NOT_FOUND for an unknown token or a deleted invitee.
    """
    return _find(db, token).preview(db)


def activate_with_password(
    db: Session, data: InvitationPasswordActivationInput, sender: EmailSender
) -> AuthSession:
    """Complete the invited account with an email and password.

    Checks in order: link (404 INVITATION_NOT_FOUND, 409 INVITATION_USED, 409
    INVITATION_EXPIRED), email present (422 VALIDATION_FAILED), password rules
    (422 PASSWORD_TOO_COMMON), email not taken (409 EMAIL_ALREADY_REGISTERED),
    and for a Tenant, emergency contacts when fewer than two are stored (422
    VALIDATION_FAILED). A Manager's emergency contacts are ignored.
    Flushes, never commits; the caller's transaction makes it all-or-nothing.
    """
    found = _find(db, data.token)
    _require_usable(found)
    if data.email is None:
        raise ApiError(422, "VALIDATION_FAILED", field="email")
    name = data.name.strip()
    email = data.email.strip().lower()
    check_password_allowed(data.password, name=name, email=email)
    if find_by_email(db, email) is not None:
        raise ApiError(409, "EMAIL_ALREADY_REGISTERED", field="email")
    contacts = []
    if isinstance(found, _TenantLink) and found.contacts_required:
        if data.emergency_contacts is None:
            raise ApiError(422, "VALIDATION_FAILED", field="emergencyContacts")
        contacts = clean_contacts(data.emergency_contacts)

    now = datetime.now(UTC)
    user = found.user
    user.name = name
    user.email = email
    user.password_hash = hash_password(data.password)
    user.email_verified = False
    if isinstance(found, _TenantLink):
        found.tenant.activated_at = now
    else:
        found.record.activated_at = now
    found.invitation.used_at = now
    db.add_all(
        ContactRow(
            tenant_id=user.id,
            name=c.name,
            relationship=c.relationship,
            phone=c.phone,
            position=position,
        )
        for position, c in enumerate(contacts)
    )
    db.flush()
    tokens = start_session(db, user, data.device, LoginMethod.PASSWORD)
    send_code(db, user, sender)
    if isinstance(found, _ManagerLink):
        _notify_manager_activated(db, found.record)
    return AuthSession(**tokens.model_dump(), account=Account.from_user(user))


def _active_lease(db: Session, user: UserAccount) -> ActiveLeaseSummary | None:
    row = db.execute(
        select(Lease, Room, Property)
        .join(Room, Room.id == Lease.room_id)
        .join(Property, Property.id == Room.property_id)
        .where(Lease.tenant_id == user.id, Lease.ended_at.is_(None))
    ).first()
    if row is None:
        return None
    lease, room, property_ = row
    return ActiveLeaseSummary(
        property_name=property_.name,
        room_number=room.number,
        end_date=lease.end_date,
    )


def preview_acceptance(
    db: Session, token: str, caller: UserAccount
) -> InvitationAcceptancePreview:
    """Check whether the caller's account can accept an invitation.

    Raises 404 INVITATION_NOT_FOUND for an unknown token or a deleted invitee.
    The blocker is ROLE_MISMATCH when the caller's role differs from the
    invitation's, or ACTIVE_LEASE when a Tenant invitation meets a Tenant who
    already has an active lease.
    """
    found = _find(db, token)
    blocker = None
    active_lease = None
    if found.role != caller.role:
        blocker = InvitationBlocker.ROLE_MISMATCH
    elif isinstance(found, _TenantLink):
        active_lease = _active_lease(db, caller)
        if active_lease is not None:
            blocker = InvitationBlocker.ACTIVE_LEASE
    return InvitationAcceptancePreview(
        invitation=found.preview(db),
        account_name=caller.name,
        account_email=caller.email,
        account_role=caller.role,
        can_accept=found.status == InvitationLinkStatus.VALID and blocker is None,
        blocker=blocker,
        active_lease=active_lease,
    )


def accept_invitation(db: Session, token: str, caller: UserAccount) -> None:
    """Accept an invitation with the caller's existing account.

    Checks in order: link (404 INVITATION_NOT_FOUND, 409 INVITATION_USED, 409
    INVITATION_EXPIRED), role (409 INVITATION_ROLE_MISMATCH), then for a Tenant
    invitation an active lease (409 TENANT_HAS_ACTIVE_LEASE), for a Manager
    invitation an existing live record under the same Owner (409
    MANAGER_ALREADY_ADDED). Accepting a Tenant invitation is not available yet
    (501 NOT_IMPLEMENTED). For a Manager invitation the record and the
    assignments of the Owner's properties move to the caller. Flushes, never
    commits.
    """
    found = _find(db, token)
    _require_usable(found)
    if found.role != caller.role:
        raise ApiError(409, "INVITATION_ROLE_MISMATCH")
    if isinstance(found, _TenantLink):
        if _active_lease(db, caller) is not None:
            raise ApiError(409, "TENANT_HAS_ACTIVE_LEASE")
        raise ApiError(501, "NOT_IMPLEMENTED")

    record = found.record
    already_added = db.scalars(
        select(Manager).where(
            Manager.owner_id == record.owner_id,
            Manager.user_id == caller.id,
            Manager.deleted_at.is_(None),
        )
    ).first()
    if already_added is not None:
        raise ApiError(409, "MANAGER_ALREADY_ADDED")

    placeholder_id = record.user_id
    owned_properties = select(Property.id).where(Property.owner_id == record.owner_id)
    moved = list(
        db.scalars(
            select(ManagerAssignment).where(
                ManagerAssignment.manager_id == placeholder_id,
                ManagerAssignment.property_id.in_(owned_properties),
            )
        )
    )
    for assignment in moved:
        db.delete(assignment)
        if db.get(ManagerAssignment, (caller.id, assignment.property_id)) is None:
            db.add(
                ManagerAssignment(
                    manager_id=caller.id, property_id=assignment.property_id
                )
            )
    record.user_id = caller.id
    now = datetime.now(UTC)
    record.activated_at = now
    found.invitation.used_at = now
    db.flush()
    _notify_manager_activated(db, record)
