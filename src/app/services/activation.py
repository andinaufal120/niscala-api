"""Previewing and activating a tenant account through an invitation link."""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.email import EmailSender
from app.errors import ApiError
from app.models import EmergencyContact as ContactRow
from app.models import Invitation, Lease, Property, Room, Tenant, UserAccount
from app.schemas.auth import Account, AuthSession
from app.schemas.invitations import (
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

MIN_CONTACTS = 2


class _Found:
    def __init__(self, db: Session, token: str) -> None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = db.execute(
            select(Invitation, Tenant, UserAccount, Room, Property)
            .join(Tenant, Tenant.user_id == Invitation.tenant_id)
            .join(UserAccount, UserAccount.id == Tenant.user_id)
            .join(Lease, Lease.tenant_id == Tenant.user_id)
            .join(Room, Room.id == Lease.room_id)
            .join(Property, Property.id == Room.property_id)
            .where(
                Invitation.token_hash == token_hash,
                Tenant.deleted_at.is_(None),
                Lease.ended_at.is_(None),
            )
        ).first()
        if row is None:
            raise ApiError(404, "INVITATION_NOT_FOUND")
        self.invitation, self.tenant, self.user, self.room, self.property = row
        self.contacts = list(
            db.scalars(select(ContactRow).where(ContactRow.tenant_id == self.user.id))
        )

    @property
    def status(self) -> InvitationLinkStatus:
        invitation = self.invitation
        if (
            invitation.used_at is not None
            or invitation.invalidated_at is not None
            or self.tenant.activated_at is not None
        ):
            return InvitationLinkStatus.USED
        if invitation.expires_at <= datetime.now(UTC):
            return InvitationLinkStatus.EXPIRED
        return InvitationLinkStatus.VALID

    @property
    def contacts_required(self) -> bool:
        return len(self.contacts) < MIN_CONTACTS


def preview_invitation(db: Session, token: str) -> InvitationPreview:
    """Describe an invitation link in any state.

    Raises 404 INVITATION_NOT_FOUND for an unknown token or a deleted tenant.
    """
    found = _Found(db, token)
    owner = db.get(UserAccount, found.property.owner_id)
    return InvitationPreview(
        status=found.status,
        role=InvitationRole.TENANT,
        inviter_name=owner.name,
        properties=[
            InvitationProperty(name=found.property.name, address=found.property.address)
        ],
        room_number=found.room.number,
        expires_at=found.invitation.expires_at,
        name=found.user.name,
        emergency_contacts_required=found.contacts_required,
    )


def activate_with_password(
    db: Session, data: InvitationPasswordActivationInput, sender: EmailSender
) -> AuthSession:
    """Complete the invited tenant's account with an email and password.

    Checks in order: link (404 INVITATION_NOT_FOUND, 409 INVITATION_USED, 409
    INVITATION_EXPIRED), email present (422 VALIDATION_FAILED), password rules
    (422 PASSWORD_TOO_COMMON), email not taken (409 EMAIL_ALREADY_REGISTERED),
    emergency contacts when fewer than two are stored (422 VALIDATION_FAILED).
    Flushes, never commits; the caller's transaction makes it all-or-nothing.
    """
    found = _Found(db, data.token)
    if found.status == InvitationLinkStatus.USED:
        raise ApiError(409, "INVITATION_USED")
    if found.status == InvitationLinkStatus.EXPIRED:
        raise ApiError(409, "INVITATION_EXPIRED")
    if data.email is None:
        raise ApiError(422, "VALIDATION_FAILED", field="email")
    name = data.name.strip()
    email = data.email.strip().lower()
    check_password_allowed(data.password, name=name, email=email)
    if find_by_email(db, email) is not None:
        raise ApiError(409, "EMAIL_ALREADY_REGISTERED", field="email")
    contacts = []
    if found.contacts_required:
        if data.emergency_contacts is None:
            raise ApiError(422, "VALIDATION_FAILED", field="emergencyContacts")
        contacts = clean_contacts(data.emergency_contacts)

    now = datetime.now(UTC)
    user = found.user
    user.name = name
    user.email = email
    user.password_hash = hash_password(data.password)
    user.email_verified = False
    found.tenant.activated_at = now
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
    return AuthSession(**tokens.model_dump(), account=Account.from_user(user))
