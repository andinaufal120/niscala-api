"""Adding, listing, editing and deleting properties."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.access import accessible_properties, get_accessible_property
from app.errors import ApiError
from app.models import Lease, ManagerAssignment, Property, Room, UserAccount
from app.schemas.properties import (
    BankAccount,
    ManagerRef,
    PropertyInput,
    PropertySummary,
)
from app.schemas.properties import Property as PropertyDetail
from app.services.subscriptions import plan_limits


def _bank_account(row: Property) -> BankAccount | None:
    if row.bank_name is None:
        return None
    return BankAccount(
        bank_name=row.bank_name,
        account_number=row.bank_account_number or "",
        account_holder_name=row.bank_account_holder_name or "",
    )


def _managers_by_property(
    db: Session, property_ids: Iterable[UUID]
) -> dict[UUID, list[ManagerRef]]:
    rows = db.execute(
        select(ManagerAssignment.property_id, UserAccount.id, UserAccount.name)
        .join(UserAccount, UserAccount.id == ManagerAssignment.manager_id)
        .where(ManagerAssignment.property_id.in_(list(property_ids)))
        .order_by(UserAccount.name, UserAccount.id)
    )
    found: dict[UUID, list[ManagerRef]] = defaultdict(list)
    for property_id, manager_id, name in rows:
        found[property_id].append(ManagerRef(id=manager_id, name=name))
    return found


def _room_counts(db: Session, property_ids: Iterable[UUID]) -> dict[UUID, int]:
    rows = db.execute(
        select(Room.property_id, func.count())
        .where(Room.property_id.in_(list(property_ids)), Room.deleted_at.is_(None))
        .group_by(Room.property_id)
    )
    return {property_id: count for property_id, count in rows}


def _occupied_counts(db: Session, property_ids: Iterable[UUID]) -> dict[UUID, int]:
    """Count each property's live rooms that have an active lease."""
    rows = db.execute(
        select(Room.property_id, func.count())
        .join(Lease, Lease.room_id == Room.id)
        .where(
            Room.property_id.in_(list(property_ids)),
            Room.deleted_at.is_(None),
            Lease.ended_at.is_(None),
        )
        .group_by(Room.property_id)
    )
    return {property_id: count for property_id, count in rows}


def _detail(
    row: Property, managers: list[ManagerRef], room_count: int, occupied: int
) -> PropertyDetail:
    return PropertyDetail(
        id=row.id,
        name=row.name,
        address=row.address,
        bank_account=_bank_account(row),
        room_count=room_count,
        occupied_room_count=occupied,
        vacant_room_count=room_count - occupied,
        managers=managers,
        editable=not row.view_only,
    )


def _present(db: Session, row: Property) -> PropertyDetail:
    return _detail(
        row,
        _managers_by_property(db, [row.id])[row.id],
        _room_counts(db, [row.id]).get(row.id, 0),
        _occupied_counts(db, [row.id]).get(row.id, 0),
    )


def _ensure_name_free(
    db: Session, owner_id: UUID, name: str, excluding: UUID | None = None
) -> None:
    taken = select(Property.id).where(
        Property.owner_id == owner_id,
        Property.deleted_at.is_(None),
        func.lower(Property.name) == name.lower(),
    )
    if excluding is not None:
        taken = taken.where(Property.id != excluding)
    if db.scalars(taken.limit(1)).first() is not None:
        raise ApiError(409, "PROPERTY_NAME_TAKEN", field="name")


def _set_fields(row: Property, data: PropertyInput) -> None:
    row.name = data.name
    row.address = data.address
    bank = data.bank_account
    row.bank_name = bank and bank.bank_name
    row.bank_account_number = bank and bank.account_number
    row.bank_account_holder_name = bank and bank.account_holder_name


def create_property(
    db: Session, owner: UserAccount, data: PropertyInput
) -> PropertyDetail:
    """Add a property to the owner's account.

    Raises 409 PROPERTY_NAME_TAKEN when a live property of the owner has the
    name (ignoring case), then 403 PROPERTY_LIMIT_REACHED when the owner's plan
    allows no more properties. View-only properties count towards the limit.
    """
    _ensure_name_free(db, owner.id, data.name)
    limit = plan_limits(db, owner.id).max_properties
    held = db.scalar(
        select(func.count())
        .select_from(Property)
        .where(Property.owner_id == owner.id, Property.deleted_at.is_(None))
    )
    if limit is not None and (held or 0) >= limit:
        raise ApiError(403, "PROPERTY_LIMIT_REACHED")
    row = Property(owner_id=owner.id)
    _set_fields(row, data)
    db.add(row)
    db.flush()
    return _detail(row, [], 0, 0)


def list_properties(db: Session, user: UserAccount) -> list[PropertySummary]:
    """List the properties the user may access, ordered by name."""
    rows = db.scalars(accessible_properties(user)).all()
    managers = _managers_by_property(db, [row.id for row in rows])
    room_counts = _room_counts(db, [row.id for row in rows])
    occupied_counts = _occupied_counts(db, [row.id for row in rows])
    return [
        PropertySummary(
            id=row.id,
            name=row.name,
            address=row.address,
            room_count=room_counts.get(row.id, 0),
            occupied_room_count=occupied_counts.get(row.id, 0),
            managers=managers[row.id],
            editable=not row.view_only,
        )
        for row in rows
    ]


def get_property(db: Session, user: UserAccount, property_id: UUID) -> PropertyDetail:
    """Return a property the user may access (404 PROPERTY_NOT_FOUND otherwise)."""
    return _present(db, get_accessible_property(db, user, property_id))


def update_property(
    db: Session,
    owner: UserAccount,
    property_id: UUID,
    data: PropertyInput,
    reauthenticated: bool,
) -> PropertyDetail:
    """Replace a property's name, address and bank account.

    Checks in order: access (404 PROPERTY_NOT_FOUND), view-only (403
    PROPERTY_READ_ONLY), a changed bank account without `reauthenticated`
    (403 REAUTHENTICATION_REQUIRED), a name used by another live property of
    the owner (409 PROPERTY_NAME_TAKEN).
    """
    row = get_accessible_property(db, owner, property_id)
    if row.view_only:
        raise ApiError(403, "PROPERTY_READ_ONLY")
    if data.bank_account != _bank_account(row) and not reauthenticated:
        raise ApiError(403, "REAUTHENTICATION_REQUIRED")
    _ensure_name_free(db, owner.id, data.name, excluding=row.id)
    _set_fields(row, data)
    db.flush()
    return _present(db, row)


def delete_property(db: Session, owner: UserAccount, property_id: UUID) -> None:
    """Soft-delete a property and its rooms, and remove its manager assignments.

    Raises 404 PROPERTY_NOT_FOUND without access, then 409
    PROPERTY_HAS_ACTIVE_LEASE while any live room has an active lease.
    """
    row = get_accessible_property(db, owner, property_id)
    if _occupied_counts(db, [row.id]).get(row.id, 0) > 0:
        raise ApiError(409, "PROPERTY_HAS_ACTIVE_LEASE")
    now = datetime.now(UTC)
    row.deleted_at = now
    db.execute(
        update(Room)
        .where(Room.property_id == row.id, Room.deleted_at.is_(None))
        .values(deleted_at=now)
    )
    db.execute(delete(ManagerAssignment).where(ManagerAssignment.property_id == row.id))
