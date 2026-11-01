"""Listing, reading, editing and deleting user accounts as an Admin, and confirming email changes."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.email import EmailSender
from app.errors import ApiError
from app.models import (
    EmailChangeRequest,
    Invitation,
    Lease,
    Manager,
    ManagerAssignment,
    Property,
    Room,
    Tenant,
    UserAccount,
    UserSession,
)
from app.schemas.auth import UserRole
from app.schemas.sessions import LoginMethod
from app.schemas.user_accounts import (
    AccountPropertyRef,
    AccountTenancy,
    UserAccountInput,
    UserAccountList,
    UserAccountStatus,
    UserAccountSummary,
)
from app.schemas.user_accounts import UserAccount as UserAccountDetail
from app.services import sessions
from app.services.invitations import email_change_url
from app.services.properties import count_active_leases, remove_property

EMAIL_CHANGE_LIFETIME = timedelta(days=7)

type Found = tuple[UserAccount, bool]


def _has_record(model: type[Tenant | Manager], *conditions) -> ColumnElement[bool]:
    return exists().where(model.user_id == UserAccount.id, *conditions)


def deleted_condition() -> ColumnElement[bool]:
    """Select accounts that are deleted, however the deletion was recorded.

    An account is deleted when it is marked so, when its Tenant record is
    deleted, or when it has Manager records and all of them are deleted.
    """
    return or_(
        UserAccount.deleted_at.is_not(None),
        _has_record(Tenant, Tenant.deleted_at.is_not(None)),
        and_(
            _has_record(Manager),
            ~_has_record(Manager, Manager.deleted_at.is_(None)),
        ),
    )


def is_deleted(db: Session, user: UserAccount) -> bool:
    """Return whether the account is deleted (see `deleted_condition`)."""
    return bool(db.scalar(select(deleted_condition()).where(UserAccount.id == user.id)))


def _activated_condition() -> ColumnElement[bool]:
    """Select accounts that are not a Tenant or Manager still waiting to activate."""
    return or_(
        UserAccount.role.not_in([UserRole.TENANT, UserRole.MANAGER]),
        and_(
            UserAccount.role == UserRole.TENANT,
            _has_record(Tenant, Tenant.activated_at.is_not(None)),
        ),
        and_(
            UserAccount.role == UserRole.MANAGER,
            _has_record(Manager, Manager.activated_at.is_not(None)),
        ),
    )


def _status(user: UserAccount, deleted: bool) -> UserAccountStatus:
    return UserAccountStatus.DELETED if deleted else UserAccountStatus(user.status)


def find_user_account(db: Session, user_id: UUID) -> Found:
    """Return an activated account with whether it is deleted.

    Raises 404 USER_ACCOUNT_NOT_FOUND for an unknown account or a Tenant or
    Manager that has not activated.
    """
    row = db.execute(
        select(UserAccount, deleted_condition()).where(
            UserAccount.id == user_id, _activated_condition()
        )
    ).first()
    if row is None:
        raise ApiError(404, "USER_ACCOUNT_NOT_FOUND")
    return row[0], row[1]


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_user_accounts(
    db: Session, email: str | None, role: UserRole | None, include_deleted: bool
) -> UserAccountList:
    """List activated accounts by name ignoring case, then email, then id.

    `email` matches any part of the current email ignoring case; `%` and `_`
    match themselves. Deleted accounts are left out unless `include_deleted`.
    """
    deleted = deleted_condition()
    query = select(UserAccount, deleted).where(_activated_condition())
    if email is not None:
        query = query.where(
            UserAccount.email.ilike(f"%{_escape_like(email)}%", escape="\\")
        )
    if role is not None:
        query = query.where(UserAccount.role == role)
    if not include_deleted:
        query = query.where(~deleted)
    rows = db.execute(
        query.order_by(func.lower(UserAccount.name), UserAccount.email, UserAccount.id)
    )
    return UserAccountList(
        items=[
            UserAccountSummary(
                id=user.id,
                name=user.name,
                email=user.email or "",
                role=user.role,
                status=_status(user, is_deleted),
            )
            for user, is_deleted in rows
        ]
    )


def _properties(db: Session, user: UserAccount) -> list[AccountPropertyRef]:
    query = select(Property.id, Property.name).where(Property.deleted_at.is_(None))
    if user.role == UserRole.OWNER:
        query = query.where(Property.owner_id == user.id)
    elif user.role == UserRole.MANAGER:
        query = query.where(
            Property.id.in_(
                select(ManagerAssignment.property_id).where(
                    ManagerAssignment.manager_id == user.id
                )
            )
        )
    else:
        return []
    rows = db.execute(query.order_by(Property.name, Property.id))
    return [AccountPropertyRef(id=id_, name=name) for id_, name in rows]


def _tenancy(db: Session, user: UserAccount) -> AccountTenancy | None:
    if user.role != UserRole.TENANT:
        return None
    row = db.execute(
        select(Property.name, Room.number, Lease.end_date)
        .join(Room, Room.property_id == Property.id)
        .join(Lease, Lease.room_id == Room.id)
        .where(Lease.tenant_id == user.id, Lease.ended_at.is_(None))
    ).first()
    if row is None:
        return None
    return AccountTenancy(
        property_name=row[0], room_number=row[1], lease_end_date=row[2]
    )


def _open_change(db: Session, user_id: UUID) -> EmailChangeRequest | None:
    """Return the newest request that is neither used, replaced nor expired."""
    return db.scalars(
        select(EmailChangeRequest)
        .where(
            EmailChangeRequest.user_id == user_id,
            EmailChangeRequest.used_at.is_(None),
            EmailChangeRequest.replaced_at.is_(None),
            EmailChangeRequest.expires_at > datetime.now(UTC),
        )
        .order_by(EmailChangeRequest.created_at.desc(), EmailChangeRequest.id.desc())
        .limit(1)
    ).first()


def _detail(db: Session, found: Found) -> UserAccountDetail:
    user, deleted = found
    pending = _open_change(db, user.id)
    last_login = db.scalar(
        select(func.max(UserSession.created_at)).where(UserSession.user_id == user.id)
    )
    tenancy = _tenancy(db, user)
    if user.role == UserRole.OWNER:
        lease_count = count_active_leases(db, user.id)
    else:
        lease_count = int(tenancy is not None)
    return UserAccountDetail(
        id=user.id,
        name=user.name,
        email=user.email or "",
        pending_email=pending and pending.new_email,
        pending_email_expires_at=pending and pending.expires_at,
        role=user.role,
        status=_status(user, deleted),
        registered_at=user.created_at,
        last_login_at=last_login,
        login_methods=[LoginMethod.PASSWORD] if user.password_hash else [],
        properties=_properties(db, user),
        active_lease_count=lease_count,
        tenancy=tenancy,
    )


def get_user_account(db: Session, user_id: UUID) -> UserAccountDetail:
    """Return an activated account, deleted ones included.

    Raises 404 USER_ACCOUNT_NOT_FOUND for an unknown account or a Tenant or
    Manager that has not activated.
    """
    return _detail(db, find_user_account(db, user_id))


def _email_taken(db: Session, email: str, excluding: UUID) -> bool:
    """Return whether another account, deleted ones included, has the email."""
    return (
        db.scalars(
            select(UserAccount.id)
            .where(UserAccount.email == email, UserAccount.id != excluding)
            .limit(1)
        ).first()
        is not None
    )


def _close_open_changes(db: Session, user_id: UUID) -> None:
    db.execute(
        update(EmailChangeRequest)
        .where(
            EmailChangeRequest.user_id == user_id,
            EmailChangeRequest.used_at.is_(None),
            EmailChangeRequest.replaced_at.is_(None),
        )
        .values(replaced_at=datetime.now(UTC))
    )


def update_user_account(
    db: Session,
    caller: UserAccount,
    found: Found,
    data: UserAccountInput,
    sender: EmailSender,
) -> UserAccountDetail:
    """Change an account's name and status at once and handle its email.

    `found` comes from `find_user_account`, which raises 404
    USER_ACCOUNT_NOT_FOUND. Checks in order: deleted (409
    USER_ACCOUNT_DELETED), the caller deactivating themselves (409
    CANNOT_MODIFY_OWN_ACCOUNT), an email used by another account, deleted ones
    included (409 EMAIL_ALREADY_REGISTERED); a refusal saves nothing.
    Deactivating ends every session of the account. An email other than the
    current one starts a pending change that replaces any earlier one: the
    confirmation link goes to the new address and a notice to the current one.
    The current email cancels a pending change and sends nothing.
    """
    user, deleted = found
    if deleted:
        raise ApiError(409, "USER_ACCOUNT_DELETED")
    if user.id == caller.id and data.status == UserAccountStatus.INACTIVE:
        raise ApiError(409, "CANNOT_MODIFY_OWN_ACCOUNT")
    new_email = data.email.strip().lower()
    changes_email = new_email != user.email
    if changes_email and _email_taken(db, new_email, user.id):
        raise ApiError(409, "EMAIL_ALREADY_REGISTERED", field="email")

    user.name = data.name
    user.status = data.status
    if data.status == UserAccountStatus.INACTIVE:
        sessions.end_all_sessions(db, user.id)
    _close_open_changes(db, user.id)
    if changes_email:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        db.add(
            EmailChangeRequest(
                user_id=user.id,
                new_email=new_email,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                created_at=now,
                expires_at=now + EMAIL_CHANGE_LIFETIME,
            )
        )
        sender.send_email_change_link(new_email, email_change_url(token))
        sender.send_email_change_notice(user.email, new_email)
    db.flush()
    return _detail(db, (user, False))


def confirm_email_change(db: Session, token: str) -> None:
    """Make the requested email the login email of its account.

    Raises 404 EMAIL_CHANGE_NOT_FOUND for an unknown token or a deleted
    account, 409 EMAIL_CHANGE_USED for a link already used, replaced or
    cancelled, 409 EMAIL_CHANGE_EXPIRED for an old link, then 409
    EMAIL_ALREADY_REGISTERED when another account took the email meanwhile
    (the link stays unused). The email's verified state is left as it was.
    """
    request = db.scalars(
        select(EmailChangeRequest).where(
            EmailChangeRequest.token_hash == hashlib.sha256(token.encode()).hexdigest()
        )
    ).one_or_none()
    user = request and db.get(UserAccount, request.user_id)
    if user is None or is_deleted(db, user):
        raise ApiError(404, "EMAIL_CHANGE_NOT_FOUND")
    if request.used_at is not None or request.replaced_at is not None:
        raise ApiError(409, "EMAIL_CHANGE_USED")
    now = datetime.now(UTC)
    if request.expires_at <= now:
        raise ApiError(409, "EMAIL_CHANGE_EXPIRED")
    if _email_taken(db, request.new_email, user.id):
        raise ApiError(409, "EMAIL_ALREADY_REGISTERED", field="email")
    user.email = request.new_email
    request.used_at = now


def delete_user_account(db: Session, caller: UserAccount, user_id: UUID) -> None:
    """Soft-delete an account, end its sessions and delete what it owns or works for.

    Checks in order: account (404 USER_ACCOUNT_NOT_FOUND), the caller's own
    account (409 CANNOT_MODIFY_OWN_ACCOUNT), already deleted (409
    USER_ACCOUNT_DELETED), an Owner whose properties have an active lease (409
    OWNER_HAS_ACTIVE_LEASE), a Tenant with an active lease (409
    TENANT_HAS_ACTIVE_LEASE). An Owner's properties are deleted as in property
    deletion, a Manager loses every assignment and record, a Tenant's record is
    deleted. A refusal saves nothing.
    """
    user, deleted = find_user_account(db, user_id)
    if user.id == caller.id:
        raise ApiError(409, "CANNOT_MODIFY_OWN_ACCOUNT")
    if deleted:
        raise ApiError(409, "USER_ACCOUNT_DELETED")
    if user.role == UserRole.OWNER and count_active_leases(db, user.id) > 0:
        raise ApiError(409, "OWNER_HAS_ACTIVE_LEASE")
    if user.role == UserRole.TENANT and _tenancy(db, user) is not None:
        raise ApiError(409, "TENANT_HAS_ACTIVE_LEASE")

    now = datetime.now(UTC)
    user.deleted_at = now
    sessions.end_all_sessions(db, user.id)
    if user.role == UserRole.OWNER:
        for row in db.scalars(
            select(Property).where(
                Property.owner_id == user.id, Property.deleted_at.is_(None)
            )
        ).all():
            remove_property(db, row)
    elif user.role == UserRole.MANAGER:
        records = select(Manager.id).where(Manager.user_id == user.id)
        db.execute(
            delete(ManagerAssignment).where(ManagerAssignment.manager_id == user.id)
        )
        db.execute(
            update(Invitation)
            .where(
                Invitation.manager_id.in_(records),
                Invitation.used_at.is_(None),
                Invitation.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )
        db.execute(
            update(Manager)
            .where(Manager.user_id == user.id, Manager.deleted_at.is_(None))
            .values(deleted_at=now)
        )
    elif user.role == UserRole.TENANT:
        db.execute(
            update(Tenant)
            .where(Tenant.user_id == user.id, Tenant.deleted_at.is_(None))
            .values(deleted_at=now)
        )
    db.flush()
