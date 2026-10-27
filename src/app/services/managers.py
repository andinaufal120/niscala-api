"""Adding, listing, reading, editing and deleting managers, and regenerating invitations."""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Invitation as InvitationRow
from app.models import Manager as ManagerRow
from app.models import ManagerAssignment, UserAccount, UserSession
from app.models import Property as PropertyRow
from app.schemas.auth import UserRole
from app.schemas.managers import (
    Manager,
    ManagerAccountStatus,
    ManagerInput,
    ManagerInvitation,
    ManagerList,
    ManagerProperty,
    ManagerSummary,
)
from app.services import invitations, sessions
from app.services.tenants import normalize_phone

logger = logging.getLogger(__name__)

type Found = tuple[ManagerRow, UserAccount]


def _invalid(field: str) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", field=field)


def _status(record: ManagerRow) -> ManagerAccountStatus:
    if record.activated_at is None:
        return ManagerAccountStatus.NOT_ACTIVATED
    return ManagerAccountStatus.ACTIVE


def _invitation(row: InvitationRow | None) -> ManagerInvitation | None:
    if row is None:
        return None
    now = datetime.now(UTC)
    unusable = row.used_at is not None or row.invalidated_at is not None
    expired = not unusable and row.expires_at <= now
    usable = not unusable and not expired
    return ManagerInvitation(
        url=invitations.invitation_url(invitations.reveal_token(row))
        if usable
        else None,
        created_at=row.created_at,
        expires_at=row.expires_at,
        expired=expired,
    )


def _properties(
    db: Session, owner: UserAccount, user_ids: Iterable[UUID]
) -> dict[UUID, list[ManagerProperty]]:
    """Map each account to the live properties of the owner it is assigned to."""
    rows = db.execute(
        select(ManagerAssignment.manager_id, PropertyRow)
        .join(PropertyRow, PropertyRow.id == ManagerAssignment.property_id)
        .where(
            ManagerAssignment.manager_id.in_(list(user_ids)),
            PropertyRow.owner_id == owner.id,
            PropertyRow.deleted_at.is_(None),
        )
        .order_by(PropertyRow.name, PropertyRow.id)
    )
    found: dict[UUID, list[ManagerProperty]] = {}
    for user_id, row in rows:
        found.setdefault(user_id, []).append(
            ManagerProperty(id=row.id, name=row.name, address=row.address)
        )
    return found


def _detail(db: Session, owner: UserAccount, found: Found) -> Manager:
    record, user = found
    invitation = None
    if record.activated_at is None:
        invitation = _invitation(
            db.scalars(
                select(InvitationRow)
                .where(InvitationRow.manager_id == record.id)
                .order_by(InvitationRow.created_at.desc(), InvitationRow.id.desc())
                .limit(1)
            ).first()
        )
    return Manager(
        id=record.id,
        name=user.name,
        nickname=record.nickname,
        phone=record.phone,
        email=user.email,
        account_status=_status(record),
        properties=_properties(db, owner, [user.id]).get(user.id, []),
        invitation=invitation,
    )


def _find(db: Session, owner: UserAccount, manager_id: UUID) -> Found:
    """Return the owner's live record with the id and its account.

    Raises 404 MANAGER_NOT_FOUND for an unknown, deleted or another owner's record.
    """
    row = db.execute(
        select(ManagerRow, UserAccount)
        .join(UserAccount, UserAccount.id == ManagerRow.user_id)
        .where(
            ManagerRow.id == manager_id,
            ManagerRow.owner_id == owner.id,
            ManagerRow.deleted_at.is_(None),
        )
    ).first()
    if row is None:
        raise ApiError(404, "MANAGER_NOT_FOUND")
    return tuple(row)


def _live_property_ids(
    db: Session, owner: UserAccount, property_ids: list[UUID]
) -> list[UUID]:
    """Check that the ids are distinct live properties of the owner.

    Raises 422 VALIDATION_FAILED for a duplicate and 404 PROPERTY_NOT_FOUND for
    the first id that is not a live property of the owner. View-only properties
    are allowed.
    """
    if len(set(property_ids)) != len(property_ids):
        raise _invalid("propertyIds")
    live = set(
        db.scalars(
            select(PropertyRow.id).where(
                PropertyRow.id.in_(property_ids),
                PropertyRow.owner_id == owner.id,
                PropertyRow.deleted_at.is_(None),
            )
        )
    )
    for index, property_id in enumerate(property_ids):
        if property_id not in live:
            raise ApiError(404, "PROPERTY_NOT_FOUND", field=f"propertyIds.{index}")
    return property_ids


def _nickname(data: ManagerInput) -> str | None:
    return (data.nickname or "").strip() or None


def create_manager(db: Session, owner: UserAccount, data: ManagerInput) -> Manager:
    """Add a manager to properties of the owner and invite them.

    Checks in order: phone (422 VALIDATION_FAILED), duplicate property ids (422
    VALIDATION_FAILED), properties of the owner (404 PROPERTY_NOT_FOUND).
    Creates the manager account, the owner's record and the assignments. A
    failure to create the invitation is logged and leaves the manager saved
    without one; any other failure saves nothing.
    """
    phone = normalize_phone(data.phone, "phone")
    property_ids = _live_property_ids(db, owner, data.property_ids)

    user = UserAccount(
        name=data.name,
        email=None,
        password_hash=None,
        role=UserRole.MANAGER,
        email_verified=False,
    )
    db.add(user)
    db.flush()
    record = ManagerRow(
        owner_id=owner.id, user_id=user.id, nickname=_nickname(data), phone=phone
    )
    db.add(record)
    db.flush()
    db.add_all(
        ManagerAssignment(manager_id=user.id, property_id=property_id)
        for property_id in property_ids
    )
    db.flush()
    try:
        with db.begin_nested():
            invitations.create_invitation(db, manager_id=record.id)
    except Exception:
        logger.exception("Could not create the invitation of manager %s", record.id)
    return _detail(db, owner, (record, user))


def list_managers(
    db: Session, owner: UserAccount, property_id: UUID | None
) -> ManagerList:
    """List the owner's managers by nickname else name, optionally for one property.

    Raises 404 PROPERTY_NOT_FOUND when the filter is not a live property of the owner.
    """
    conditions = []
    if property_id is not None:
        live = db.scalars(
            select(PropertyRow.id).where(
                PropertyRow.id == property_id,
                PropertyRow.owner_id == owner.id,
                PropertyRow.deleted_at.is_(None),
            )
        ).first()
        if live is None:
            raise ApiError(404, "PROPERTY_NOT_FOUND", field="propertyId")
        conditions.append(
            ManagerRow.user_id.in_(
                select(ManagerAssignment.manager_id).where(
                    ManagerAssignment.property_id == property_id
                )
            )
        )
    rows = [
        tuple(row)
        for row in db.execute(
            select(ManagerRow, UserAccount)
            .join(UserAccount, UserAccount.id == ManagerRow.user_id)
            .where(
                ManagerRow.owner_id == owner.id,
                ManagerRow.deleted_at.is_(None),
                *conditions,
            )
            .order_by(
                func.lower(func.coalesce(ManagerRow.nickname, UserAccount.name)),
                ManagerRow.id,
            )
        )
    ]
    properties = _properties(db, owner, [user.id for _, user in rows])
    return ManagerList(
        items=[
            ManagerSummary(
                id=record.id,
                name=user.name,
                nickname=record.nickname,
                phone=record.phone,
                email=user.email,
                account_status=_status(record),
                properties=properties.get(user.id, []),
            )
            for record, user in rows
        ]
    )


def get_manager(db: Session, owner: UserAccount, manager_id: UUID) -> Manager:
    """Return the owner's manager with the invitation while not activated.

    Raises 404 MANAGER_NOT_FOUND for an unknown, deleted or another owner's record.
    """
    return _detail(db, owner, _find(db, owner, manager_id))


def update_manager(
    db: Session, owner: UserAccount, manager_id: UUID, data: ManagerInput
) -> Manager:
    """Replace a manager's nickname, phone and assignments to the owner's properties.

    Checks in order: record (404 MANAGER_NOT_FOUND), phone, duplicate property
    ids (422 VALIDATION_FAILED), properties of the owner (404
    PROPERTY_NOT_FOUND), a changed name of an activated manager (422
    MANAGER_NAME_NOT_EDITABLE). A manager who has not activated is renamed.
    Assignments to the properties of other owners are never touched. A failure
    saves nothing.
    """
    record, user = _find(db, owner, manager_id)
    phone = normalize_phone(data.phone, "phone")
    wanted = set(_live_property_ids(db, owner, data.property_ids))
    if record.activated_at is None:
        user.name = data.name
    elif data.name != user.name:
        raise ApiError(422, "MANAGER_NAME_NOT_EDITABLE", field="name")

    record.nickname = _nickname(data)
    record.phone = phone
    held = set(
        db.scalars(
            select(ManagerAssignment.property_id)
            .join(PropertyRow, PropertyRow.id == ManagerAssignment.property_id)
            .where(
                ManagerAssignment.manager_id == user.id,
                PropertyRow.owner_id == owner.id,
            )
        )
    )
    if held - wanted:
        db.execute(
            delete(ManagerAssignment).where(
                ManagerAssignment.manager_id == user.id,
                ManagerAssignment.property_id.in_(held - wanted),
            )
        )
    db.add_all(
        ManagerAssignment(manager_id=user.id, property_id=property_id)
        for property_id in wanted - held
    )
    db.flush()
    return _detail(db, owner, (record, user))


def delete_manager(db: Session, owner: UserAccount, manager_id: UUID) -> None:
    """Remove a manager from the owner's properties; history is kept.

    Raises 404 MANAGER_NOT_FOUND for an unknown, deleted or another owner's
    record. Marks the record deleted, removes the account's assignments to the
    owner's properties and invalidates the record's unused invitations. When the
    account has no other live record, every session of the account ends. A
    failure saves nothing.
    """
    record, user = _find(db, owner, manager_id)
    now = datetime.now(UTC)
    record.deleted_at = now
    db.execute(
        delete(ManagerAssignment).where(
            ManagerAssignment.manager_id == user.id,
            ManagerAssignment.property_id.in_(
                select(PropertyRow.id).where(PropertyRow.owner_id == owner.id)
            ),
        )
    )
    db.execute(
        update(InvitationRow)
        .where(
            InvitationRow.manager_id == record.id,
            InvitationRow.used_at.is_(None),
            InvitationRow.invalidated_at.is_(None),
        )
        .values(invalidated_at=now)
    )
    other_live_record = db.scalars(
        select(ManagerRow.id)
        .where(
            ManagerRow.user_id == user.id,
            ManagerRow.deleted_at.is_(None),
            ManagerRow.id != record.id,
        )
        .limit(1)
    ).first()
    if other_live_record is None:
        open_sessions = db.scalars(
            select(UserSession).where(
                UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
            )
        ).all()
        for session in open_sessions:
            sessions.end_session(db, session)
    db.flush()


def regenerate_invitation(
    db: Session, owner: UserAccount, manager_id: UUID
) -> ManagerInvitation:
    """Create a new invitation for a manager, invalidating the old one.

    Checks in order: record (404 MANAGER_NOT_FOUND), manager already activated
    (409 MANAGER_ALREADY_ACTIVE). A failure leaves the previous invitation valid.
    """
    record, _ = _find(db, owner, manager_id)
    if record.activated_at is not None:
        raise ApiError(409, "MANAGER_ALREADY_ACTIVE")
    with db.begin_nested():
        row, _ = invitations.create_invitation(db, manager_id=record.id)
    return _invitation(row)
